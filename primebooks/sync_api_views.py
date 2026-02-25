# primebooks/sync_api_views.py
"""
Server-side API endpoints for desktop sync
✅ Provides data download endpoints
✅ Handles bulk data export for offline use
✅ Handles incremental sync (changes only)
✅ Handles upload of local changes
✅ FIXED: Uses sync_id (UUID) for all record lookups — no more ID conflicts
✅ FIXED: ForeignKeys resolved via sync_id, not integer PK
✅ FIXED: Schema locking throughout entire operation
✅ FIXED: Skips public schema models in tenant sync
✅ FIXED: Signal suppression to prevent notification/audit log creation during sync
✅ FIXED: ID sequence handling — server generates IDs, desktop uses sync_id to reference
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.apps import apps
from django.core import serializers
from django_tenants.utils import schema_context
from primebooks.authentication import TenantAwareJWTAuthentication
from datetime import datetime
import logging
import json
import uuid

from primebooks.sync import SYNC_MODEL_CONFIG, suppress_signals

logger = logging.getLogger(__name__)

# ============================================================================
# PUBLIC SCHEMA MODELS - These should NOT be synced to tenant schemas
# ============================================================================
PUBLIC_SCHEMA_MODELS = [
    'company.Company',
    'company.SubscriptionPlan',
    'company.Domain',
]


def _model_has_sync_id(model):
    """Check if a model has a sync_id field"""
    return hasattr(model, 'sync_id') or any(
        f.name == 'sync_id' for f in model._meta.get_fields()
    )


def _resolve_fk_by_sync_id(related_model, value):
    """
    Resolve a ForeignKey value to a model instance.
    Tries sync_id (UUID) first, then falls back to integer PK.
    Returns the instance or None.
    """
    if value is None:
        return None

    # Try UUID sync_id lookup first
    if _model_has_sync_id(related_model):
        try:
            uid = uuid.UUID(str(value)) if not isinstance(value, uuid.UUID) else value
            return related_model.objects.get(sync_id=uid)
        except (related_model.DoesNotExist, ValueError, AttributeError):
            pass

    # Fallback: integer PK lookup (for records that predate sync_id)
    try:
        return related_model.objects.get(pk=value)
    except (related_model.DoesNotExist, ValueError):
        return None


class BulkDataDownloadView(APIView):
    """
    Download ALL data for a tenant.
    ✅ Returns complete dataset for offline use.
    ✅ Includes sync_id in every record so desktop can reference safely.
    ✅ Skips public schema models.
    """
    authentication_classes = [TenantAwareJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            from django.db import connection

            token = request.auth
            schema_name = token.get('schema_name')
            company_id = token.get('company_id')

            logger.info(f"📥 Bulk download request for schema: {schema_name}")

            all_data = {}
            total_records = 0

            with schema_context(schema_name):
                logger.info(f"   Schema locked: {connection.schema_name}")

                for model_name in SYNC_MODEL_CONFIG.keys():
                    try:
                        if connection.schema_name != schema_name:
                            logger.error(f"❌ Schema switched to {connection.schema_name} during {model_name}!")
                            continue

                        if model_name in PUBLIC_SCHEMA_MODELS:
                            logger.debug(f"  ⏭️  Skipping public schema model: {model_name}")
                            continue

                        model = apps.get_model(model_name)
                        config = SYNC_MODEL_CONFIG[model_name]
                        exclude_fields = config.get('exclude_fields', [])

                        queryset = model.objects.all()
                        count = queryset.count()

                        if count > 0:
                            data = serializers.serialize('json', queryset)
                            records = json.loads(data)

                            # Remove excluded fields but ALWAYS keep sync_id.
                            # Special case: password must never arrive blank —
                            # replace with unusable placeholder so the field
                            # passes NOT NULL checks on desktop without exposing
                            # the real hash. Desktop users authenticate via the
                            # server anyway, not local password checks.
                            safe_excludes = [f for f in exclude_fields if f != 'sync_id']
                            if safe_excludes:
                                for record in records:
                                    for field in safe_excludes:
                                        if field == 'password':
                                            record['fields']['password'] = '!desktop-no-local-login'
                                        else:
                                            record['fields'].pop(field, None)

                            all_data[model_name] = records
                            total_records += count
                            logger.info(f"  ✅ {model_name}: {count} records")
                        else:
                            logger.debug(f"  ⊘ {model_name}: 0 records")

                    except LookupError:
                        logger.warning(f"  ⚠️  Model not found: {model_name}")
                    except Exception as e:
                        logger.error(f"  ❌ Error exporting {model_name}: {e}")

            logger.info(f"✅ Bulk download complete: {total_records} total records from {len(all_data)} models")

            return Response({
                'success': True,
                'schema_name': schema_name,
                'company_id': company_id,
                'total_models': len(all_data),
                'total_records': total_records,
                'data': all_data,
            })

        except Exception as e:
            logger.error(f"❌ Bulk download failed: {e}", exc_info=True)
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ChangesDownloadView(APIView):
    """
    Download only changed data since last sync.
    ✅ Efficient incremental sync.
    ✅ sync_id always included so desktop can match records reliably.
    ✅ Skips public schema models.
    """
    authentication_classes = [TenantAwareJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            from django.db import connection
            from django.utils import timezone as tz

            since = request.query_params.get('since')
            if not since:
                return Response(
                    {'error': 'Missing "since" parameter'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                since_datetime = datetime.fromisoformat(since)
                # Make timezone-aware if naive, so ORM comparisons don't TypeError
                if since_datetime.tzinfo is None:
                    since_datetime = tz.make_aware(since_datetime)
            except ValueError:
                return Response(
                    {'error': 'Invalid datetime format. Use ISO format.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            token = request.auth
            schema_name = token.get('schema_name')

            if not schema_name:
                return Response(
                    {'error': 'No schema_name in token'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            logger.info(f"📥 Changes download for schema: {schema_name} since {since}")

            changes = {}
            total_changed = 0

            with schema_context(schema_name):
                logger.info(f"   Schema locked: {connection.schema_name}")

                for model_name in SYNC_MODEL_CONFIG.keys():
                    try:
                        if connection.schema_name != schema_name:
                            logger.error(f"❌ Schema switched during {model_name}!")
                            continue

                        if model_name in PUBLIC_SCHEMA_MODELS:
                            continue

                        model = apps.get_model(model_name)
                        config = SYNC_MODEL_CONFIG.get(model_name, {})
                        exclude_fields = config.get('exclude_fields', [])

                        queryset = model.objects.all()

                        if hasattr(model, 'modified_at'):
                            queryset = queryset.filter(modified_at__gte=since_datetime)
                        elif hasattr(model, 'updated_at'):
                            queryset = queryset.filter(updated_at__gte=since_datetime)
                        elif hasattr(model, 'last_updated'):
                            queryset = queryset.filter(last_updated__gte=since_datetime)
                        elif hasattr(model, 'created_at'):
                            queryset = queryset.filter(created_at__gte=since_datetime)
                        else:
                            continue

                        if queryset.exists():
                            data = serializers.serialize('json', queryset)
                            records = json.loads(data)

                            # Never exclude sync_id — it's the stable identifier
                            # Password placeholder: same as bulk download path.
                            safe_excludes = [f for f in exclude_fields if f != 'sync_id']
                            if safe_excludes:
                                for record in records:
                                    for field in safe_excludes:
                                        if field == 'password':
                                            record['fields']['password'] = '!desktop-no-local-login'
                                        else:
                                            record['fields'].pop(field, None)

                            changes[model_name] = records
                            total_changed += len(records)
                            logger.info(f"  Found {len(records)} changed {model_name} records")

                    except LookupError:
                        logger.warning(f"  Model not found: {model_name}")
                        continue
                    except Exception as e:
                        logger.error(f"  Error processing {model_name}: {e}")
                        continue

            logger.info(f"✅ Returning {total_changed} changed records across {len(changes)} models")

            return Response({
                'success': True,
                'data': changes,
                'total_records': total_changed,
                'since': since
            })

        except Exception as e:
            logger.error(f"❌ Changes download error: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

class UploadChangesView(APIView):
    """
    Upload local changes from desktop to server.

    ✅ sync_id is the SINGLE SOURCE OF TRUTH for record identity
    ✅ ForeignKeys are resolved via sync_id (UUID) not integer PK
    ✅ Offline records (negative desktop_id OR no server PK) use sync_id to find/create
    ✅ Online records updated via sync_id lookup — no integer PK collisions
    ✅ Returns sync_id → server_id mappings so desktop can update local references
    ✅ Delta-based Stock updates — preserves concurrent online sales
    ✅ Schema locked for entire operation
    ✅ Signals suppressed during sync
    ✅ Sequences reset after upload
    """
    authentication_classes = [TenantAwareJWTAuthentication]
    permission_classes = [IsAuthenticated]

    # -------------------------------------------------------------------------
    # Unique field fallbacks (used when a model has no sync_id yet)
    # -------------------------------------------------------------------------
    def _get_unique_lookup_fields(self, model):
        model_name = model._meta.model_name
        unique_lookups = {
            'customuser': ['username'],
            'role': ['name'],
            'store': ['name'],
            'storeaccess': ['user', 'store'],
            'category': ['name'],
            'supplier': ['name'],
            'product': ['sku'],
            'stock': ['product', 'store'],
            'stockmovement': ['movement_number'],
            'customer': ['phone'],
            'sale': ['receipt_number'],
            'saleitem': ['sale', 'product'],
            'payment': ['sale', 'payment_method', 'created_at'],
        }
        return unique_lookups.get(model_name, [])

    def _build_unique_lookup(self, model, fields):
        unique_fields = self._get_unique_lookup_fields(model)
        if not unique_fields:
            return None
        lookup = {}
        for field_name in unique_fields:
            if field_name in fields:
                lookup[field_name] = fields[field_name]
            else:
                return None
        return lookup

    # -------------------------------------------------------------------------
    # Sequence reset (unchanged from original)
    # -------------------------------------------------------------------------
    def _reset_sequences(self, schema_name):
        from django.db import connection
        logger.info(f"Resetting sequences for schema: {schema_name}")
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT s.sequencename, c.relname, a.attname
                    FROM pg_sequences s
                    JOIN pg_class seq_cls
                        ON seq_cls.relname = s.sequencename
                        AND seq_cls.relnamespace = (
                            SELECT oid FROM pg_namespace WHERE nspname = %s
                        )
                    JOIN pg_depend dep
                        ON dep.objid = seq_cls.oid
                        AND dep.classid = 'pg_class'::regclass
                        AND dep.deptype = 'a'
                    JOIN pg_attribute a
                        ON a.attrelid = dep.refobjid
                        AND a.attnum = dep.refobjsubid
                    JOIN pg_class c ON c.oid = dep.refobjid
                    WHERE s.schemaname = %s
                    ORDER BY s.sequencename;
                """, [schema_name, schema_name])

                rows = cursor.fetchall()

                if not rows:
                    cursor.execute(
                        "SELECT sequencename FROM pg_sequences "
                        "WHERE schemaname = %s ORDER BY sequencename;",
                        [schema_name]
                    )
                    rows = []
                    for (sname,) in cursor.fetchall():
                        parts = sname.rsplit("_", 2)
                        if len(parts) == 3 and parts[2] == "seq":
                            rows.append((sname, parts[0], parts[1]))
                        else:
                            rows.append((sname, sname.replace("_id_seq", ""), "id"))

                reset_count = skipped_count = 0
                for seq_name, table_name, col_name in rows:
                    try:
                        cursor.execute(
                            "SELECT to_regclass(%s)",
                            [f"{schema_name}.{table_name}"]
                        )
                        if cursor.fetchone()[0] is None:
                            skipped_count += 1
                            continue
                        cursor.execute(
                            f'SELECT COALESCE(MAX("{col_name}"), 0) '
                            f'FROM "{schema_name}"."{table_name}";'
                        )
                        max_val = cursor.fetchone()[0]
                        cursor.execute(
                            f'SELECT setval(\'"{schema_name}"."{seq_name}"\', '
                            f'GREATEST(%s, 1), true);',
                            [max_val]
                        )
                        reset_count += 1
                    except Exception as e:
                        logger.warning(f"  Skipped {seq_name}: {str(e)[:120]}")
                        skipped_count += 1

                logger.info(f"Sequences reset: {reset_count} done, {skipped_count} skipped")

        except Exception as e:
            logger.error(f"_reset_sequences failed: {e}", exc_info=True)

    # -------------------------------------------------------------------------
    # FK resolution — the key upgrade
    # -------------------------------------------------------------------------
    def _resolve_field_value(self, model, field_name, value):
        """
        Resolve a single field value.
        - ManyToMany  → returned separately
        - ForeignKey  → resolved via sync_id first, then PK fallback
        - Decimal     → cast from string
        - Internal _* → skipped
        Returns (field_type, resolved_value) where field_type is one of:
            'skip'        — field should be omitted (internal field, unknown field)
            'skip_record' — the FK is required but unresolvable; caller must skip the whole record
            'm2m'         — set after save
            'fk'          — resolved FK instance
            'value'       — plain scalar value
        """
        from decimal import Decimal

        if field_name.startswith('_'):
            return 'skip', None

        try:
            field = model._meta.get_field(field_name)
        except Exception:
            return 'skip', None

        if field.many_to_many:
            return 'm2m', value

        if field.many_to_one and value is not None:
            related_model = field.related_model
            related_table = related_model._meta.db_table

            # Never try to resolve public schema FKs in tenant schema
            if related_table in ('company_company', 'company_subscriptionplan'):
                return 'skip', None

            instance = _resolve_fk_by_sync_id(related_model, value)
            if instance is not None:
                return 'fk', instance

            # FK not resolved — check if the field allows NULL
            if field.null:
                logger.debug(f"      FK {field_name}={value} not resolved — nulling nullable field")
                return 'value', None
            else:
                # Required FK missing — the whole record must be skipped to avoid
                # a NOT NULL constraint error or silent data corruption.
                logger.warning(
                    f"      FK {field_name}={value} not resolved and field is NOT NULL "
                    f"— skipping record"
                )
                return 'skip_record', None

        if (hasattr(field, 'get_internal_type') and
                field.get_internal_type() == 'DecimalField'):
            if value is not None and isinstance(value, str):
                return 'value', Decimal(value)
            return 'value', value

        return 'value', value


def _process_fields(self, model, raw_fields):
    """
    Separate raw fields into processed_fields and m2m_fields.
    FKs are resolved to instances using sync_id.
    Returns (processed, m2m, should_skip) where should_skip=True means
    a required FK was unresolvable and this record must not be saved.
    """
    processed = {}
    m2m = {}

    for field_name, value in raw_fields.items():
        kind, resolved = self._resolve_field_value(model, field_name, value)
        if kind == 'skip':
            continue
        elif kind == 'skip_record':
            # Propagate: tell the caller to skip the entire record
            return {}, {}, True
        elif kind == 'm2m':
            m2m[field_name] = value  # set after save
        else:
            processed[field_name] = resolved

    return processed, m2m, False

    # -------------------------------------------------------------------------
    # Core upload logic
    # -------------------------------------------------------------------------
    def _find_existing(self, model, record_sync_id, desktop_id, processed_fields):
        """
        Find an existing server record using sync_id → unique fields → pk (in that order).
        Returns the object or None.
        """
        # 1. sync_id lookup (preferred)
        if record_sync_id and _model_has_sync_id(model):
            try:
                return model.objects.get(sync_id=record_sync_id)
            except model.DoesNotExist:
                pass

        # 2. Business-key lookup (e.g. receipt_number, sku)
        unique_lookup = self._build_unique_lookup(model, processed_fields)
        if unique_lookup:
            try:
                return model.objects.get(**unique_lookup)
            except model.DoesNotExist:
                pass

        # 3. Integer PK fallback (only for positive / online IDs)
        if isinstance(desktop_id, int) and desktop_id > 0:
            try:
                return model.objects.get(pk=desktop_id)
            except model.DoesNotExist:
                pass

        return None

    def _apply_stock_delta(self, model, obj, quantity_delta, non_qty_fields):
        """Apply delta-based stock update safely."""
        from django.db.models import F
        if quantity_delta is not None and quantity_delta != 0:
            model.objects.filter(pk=obj.pk).update(
                quantity=F('quantity') + quantity_delta
            )
            logger.info(f"      ✅ Stock {obj.pk}: delta {quantity_delta:+.3f} applied")

        if non_qty_fields:
            for f, v in non_qty_fields.items():
                setattr(obj, f, v)
            obj.save()

    def post(self, request):
        try:
            from django.db import connection
            from django.core.exceptions import ValidationError

            changes = request.data.get('changes', {})
            schema_name = request.data.get('schema_name')

            token = request.auth
            token_schema = token.get('schema_name')

            if token_schema != schema_name:
                return Response(
                    {'success': False, 'error': 'Schema mismatch'},
                    status=status.HTTP_403_FORBIDDEN
                )

            logger.info(f"📤 Upload request for schema: {schema_name}")
            logger.info(f"  Received {len(changes)} model types")

            if not changes:
                return Response({'success': True, 'message': 'No changes to upload'})

            total_created = 0
            total_updated = 0
            total_skipped = 0
            errors = []
            # sync_id → server integer PK mappings returned to desktop
            id_mappings = {}

            UPLOAD_PUBLIC_SCHEMA_MODELS = [
                'company.Company',
                'company.SubscriptionPlan',
                'company.Domain',
            ]

            with suppress_signals():
                logger.info("🔇 Signals suppressed")

                with schema_context(schema_name):
                    logger.info(f"   Schema locked: {connection.schema_name}")

                    for model_name, records in changes.items():
                        try:
                            if connection.schema_name != schema_name:
                                msg = f"Schema switched to {connection.schema_name}!"
                                logger.error(f"❌ {msg}")
                                errors.append(msg)
                                continue

                            if model_name in UPLOAD_PUBLIC_SCHEMA_MODELS:
                                logger.info(f"  ⏭️  Skipping public schema model: {model_name}")
                                total_skipped += len(records)
                                continue

                            model = apps.get_model(model_name)
                            is_stock_model = model._meta.label == 'inventory.Stock'
                            has_sync_id = _model_has_sync_id(model)
                            model_mappings = {}

                            logger.info(f"  Processing {model_name}: {len(records)} records "
                                        f"(sync_id={'yes' if has_sync_id else 'no'})")

                            for record in records:
                                try:
                                    desktop_id = record.get('pk')
                                    fields = dict(record.get('fields', {}))

                                    # Pull sync_id from fields (desktop sends it)
                                    record_sync_id_raw = fields.pop('sync_id', None)
                                    record_sync_id = None
                                    if record_sync_id_raw:
                                        try:
                                            record_sync_id = uuid.UUID(str(record_sync_id_raw))
                                        except ValueError:
                                            pass

                                    # Pull Stock delta before field processing
                                    quantity_delta = None
                                    if is_stock_model:
                                        quantity_delta = fields.pop('_quantity_delta', None)

                                    # Drop raw integer id field
                                    fields.pop('id', None)

                                    # Resolve all fields
                                    processed_fields, m2m_fields, skip_record = self._process_fields(model, fields)
                                    if skip_record:
                                        total_skipped += 1
                                        continue

                                    # Determine if this is an offline (new) record
                                    is_offline = (
                                        (isinstance(desktop_id, int) and desktop_id < 0)
                                        or record_sync_id is None
                                    )

                                    # -------------------------------------------------------
                                    # Find existing server record
                                    # -------------------------------------------------------
                                    existing = self._find_existing(
                                        model, record_sync_id, desktop_id, processed_fields
                                    )

                                    try:
                                        if existing:
                                            obj = existing

                                            # Stamp sync_id if missing on old record
                                            if has_sync_id and record_sync_id and not obj.sync_id:
                                                obj.sync_id = record_sync_id

                                            if is_stock_model:
                                                if quantity_delta is not None:
                                                    non_qty = {k: v for k, v in processed_fields.items()
                                                                if k != 'quantity'}
                                                    self._apply_stock_delta(
                                                        model, obj, quantity_delta, non_qty
                                                    )
                                                else:
                                                    logger.info(
                                                        f"      ⚠️  Stock {obj.pk}: "
                                                        f"no delta baseline, overwriting"
                                                    )
                                                    for f, v in processed_fields.items():
                                                        setattr(obj, f, v)
                                                    obj.save()
                                            else:
                                                for f, v in processed_fields.items():
                                                    setattr(obj, f, v)
                                                obj.save()

                                            for field_name, value in m2m_fields.items():
                                                if value:
                                                    getattr(obj, field_name).set(value)

                                            total_updated += 1
                                            logger.debug(
                                                f"      ✅ Updated: {model_name} "
                                                f"sync_id={record_sync_id} → pk={obj.pk}"
                                            )

                                        else:
                                            # Create new record
                                            # Assign sync_id so it's stable forever
                                            if has_sync_id:
                                                processed_fields['sync_id'] = (
                                                    record_sync_id or uuid.uuid4()
                                                )

                                            obj = model(**processed_fields)
                                            obj.save()

                                            for field_name, value in m2m_fields.items():
                                                if value:
                                                    getattr(obj, field_name).set(value)

                                            total_created += 1
                                            logger.info(
                                                f"      ✅ Created: {model_name} "
                                                f"sync_id={processed_fields.get('sync_id')} "
                                                f"→ pk={obj.pk}"
                                            )

                                        # Always map sync_id → server pk so desktop
                                        # can update its local FK references
                                        stable_key = (
                                            str(record_sync_id)
                                            if record_sync_id
                                            else str(desktop_id)
                                        )
                                        model_mappings[stable_key] = {
                                            'server_id': obj.pk,
                                            'sync_id': str(obj.sync_id) if has_sync_id and obj.sync_id else None,
                                        }

                                    except ValidationError as e:
                                        error_dict = (
                                            e.message_dict
                                            if hasattr(e, 'message_dict')
                                            else {}
                                        )
                                        error_str = str(error_dict)
                                        if any(x in error_str.lower() for x in [
                                            'choice', 'constraint', 'efris',
                                            'password', 'either product or service'
                                        ]):
                                            logger.debug(
                                                f"      ⚠️  Validation skip "
                                                f"{desktop_id}: {error_dict}"
                                            )
                                            total_skipped += 1
                                            continue
                                        raise

                                except Exception as e:
                                    error_msg = f"{model_name}:{desktop_id} - {str(e)}"
                                    logger.error(f"      ❌ {error_msg}")
                                    errors.append(error_msg)

                            if model_mappings:
                                id_mappings[model_name] = model_mappings

                        except LookupError:
                            logger.warning(f"  ⚠️  Model not found: {model_name}")
                        except Exception as e:
                            logger.error(f"  ❌ Error processing {model_name}: {e}")
                            errors.append(f"{model_name}: {str(e)}")

                    logger.info(
                        f"✅ Upload complete: {total_created} created, "
                        f"{total_updated} updated, {total_skipped} skipped"
                    )

                    if total_created > 0 or total_updated > 0:
                        logger.info("🔧 Resetting sequences after upload")
                        self._reset_sequences(schema_name)

                logger.info("🔊 Signals restored")

            return Response({
                'success': True,
                'created': total_created,
                'updated': total_updated,
                'skipped': total_skipped,
                'id_mappings': id_mappings,   # sync_id → {server_id, sync_id}
                'errors': errors[:10] if errors else []
            })

        except Exception as e:
            logger.error(f"❌ Upload error: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ModelDataDownloadView(APIView):
    """
    Download data for a specific model.
    ✅ sync_id always included.
    ✅ Allows incremental sync.
    """
    authentication_classes = [TenantAwareJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, model_name):
        try:
            token = request.auth
            schema_name = token.get('schema_name')

            logger.info(f"📥 Download request for {model_name} in schema: {schema_name}")

            since = request.GET.get('since')

            with schema_context(schema_name):
                try:
                    model = apps.get_model(model_name)
                    config = SYNC_MODEL_CONFIG.get(model_name, {})
                    exclude_fields = [
                        f for f in config.get('exclude_fields', []) if f != 'sync_id'
                    ]

                    queryset = model.objects.all()

                    if since:
                        if hasattr(model, 'modified_at'):
                            queryset = queryset.filter(modified_at__gte=since)
                        elif hasattr(model, 'updated_at'):
                            queryset = queryset.filter(updated_at__gte=since)

                    count = queryset.count()

                    data = serializers.serialize('json', queryset)
                    records = json.loads(data)

                    if exclude_fields:
                        for record in records:
                            for field in exclude_fields:
                                record['fields'].pop(field, None)

                    logger.info(f"✅ Downloaded {count} {model_name} records")

                    return Response({
                        'success': True,
                        'model': model_name,
                        'count': count,
                        'records': records,
                    })

                except LookupError:
                    return Response({
                        'success': False,
                        'error': f'Model not found: {model_name}'
                    }, status=status.HTTP_404_NOT_FOUND)

        except Exception as e:
            logger.error(f"❌ Model download failed: {e}", exc_info=True)
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SyncStatusView(APIView):
    """Get sync status and statistics."""
    authentication_classes = [TenantAwareJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            token = request.auth
            schema_name = token.get('schema_name')

            stats = {}
            total_records = 0

            with schema_context(schema_name):
                for model_name in SYNC_MODEL_CONFIG.keys():
                    if model_name in PUBLIC_SCHEMA_MODELS:
                        continue
                    try:
                        model = apps.get_model(model_name)
                        count = model.objects.count()
                        stats[model_name] = count
                        total_records += count
                    except Exception:
                        stats[model_name] = 0

            return Response({
                'success': True,
                'schema_name': schema_name,
                'total_records': total_records,
                'model_stats': stats,
            })

        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)