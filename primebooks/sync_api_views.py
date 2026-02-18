# primebooks/sync_api_views.py
"""
Server-side API endpoints for desktop sync
✅ Provides data download endpoints
✅ Handles bulk data export for offline use
✅ Handles incremental sync (changes only)
✅ Handles upload of local changes
✅ FIXED: Proper ForeignKey handling (instances not IDs)
✅ FIXED: Schema locking throughout entire operation
✅ FIXED: Skips public schema models in tenant sync
✅ FIXED: ID sequence handling - server generates IDs, not desktop
✅ FIXED: Signal suppression to prevent notification/audit log creation during sync
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
from primebooks.sync import SYNC_MODEL_CONFIG, suppress_signals  # ✅ ADDED suppress_signals

logger = logging.getLogger(__name__)

# ============================================================================
# PUBLIC SCHEMA MODELS - These should NOT be synced to tenant schemas
# ============================================================================
PUBLIC_SCHEMA_MODELS = [
    'company.Company',
    'company.SubscriptionPlan',
    'company.Domain',
]


class BulkDataDownloadView(APIView):
    """
    Download ALL data for a tenant
    ✅ Returns complete dataset for offline use
    ✅ Skips public schema models
    """
    authentication_classes = [TenantAwareJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            from django.db import connection

            # Get schema from JWT token
            token = request.auth
            schema_name = token.get('schema_name')
            company_id = token.get('company_id')

            logger.info(f"📥 Bulk download request for schema: {schema_name}")

            # Collect all data
            all_data = {}
            total_records = 0

            # ✅ Lock schema for entire operation
            with schema_context(schema_name):
                logger.info(f"   Schema locked: {connection.schema_name}")

                for model_name in SYNC_MODEL_CONFIG.keys():
                    try:
                        # ✅ Verify schema hasn't switched
                        if connection.schema_name != schema_name:
                            logger.error(f"❌ Schema switched to {connection.schema_name} during {model_name}!")
                            continue

                        # ✅ Skip public schema models
                        if model_name in PUBLIC_SCHEMA_MODELS:
                            logger.debug(f"  ⏭️  Skipping public schema model: {model_name}")
                            continue

                        model = apps.get_model(model_name)
                        config = SYNC_MODEL_CONFIG[model_name]
                        exclude_fields = config.get('exclude_fields', [])

                        # Get all records
                        queryset = model.objects.all()
                        count = queryset.count()

                        if count > 0:
                            # Serialize
                            data = serializers.serialize('json', queryset)
                            records = json.loads(data)

                            # Remove excluded fields
                            if exclude_fields:
                                for record in records:
                                    for field in exclude_fields:
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
    Download only changed data since last sync
    ✅ Efficient incremental sync
    ✅ Skips public schema models
    """
    authentication_classes = [TenantAwareJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            from django.db import connection

            # Get parameters
            since = request.query_params.get('since')
            if not since:
                return Response(
                    {'error': 'Missing "since" parameter'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Parse datetime
            try:
                since_datetime = datetime.fromisoformat(since)
            except ValueError:
                return Response(
                    {'error': 'Invalid datetime format. Use ISO format.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Get schema from token
            token = request.auth
            schema_name = token.get('schema_name')

            if not schema_name:
                return Response(
                    {'error': 'No schema_name in token'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            logger.info(f"📥 Changes download request for schema: {schema_name} since {since}")

            changes = {}
            total_changed = 0

            # ✅ Lock schema for entire operation
            with schema_context(schema_name):
                logger.info(f"   Schema locked: {connection.schema_name}")

                for model_name in SYNC_MODEL_CONFIG.keys():
                    try:
                        # ✅ Verify schema hasn't switched
                        if connection.schema_name != schema_name:
                            logger.error(f"❌ Schema switched during {model_name}!")
                            continue

                        # ✅ Skip public schema models
                        if model_name in PUBLIC_SCHEMA_MODELS:
                            continue

                        model = apps.get_model(model_name)
                        config = SYNC_MODEL_CONFIG.get(model_name, {})
                        exclude_fields = config.get('exclude_fields', [])

                        # Build queryset
                        queryset = model.objects.all()

                        if hasattr(model, 'modified_at'):
                            queryset = queryset.filter(modified_at__gte=since_datetime)
                        elif hasattr(model, 'updated_at'):
                            queryset = queryset.filter(updated_at__gte=since_datetime)
                        elif hasattr(model, 'last_updated'):  # ← Stock uses this
                            queryset = queryset.filter(last_updated__gte=since_datetime)
                        elif hasattr(model, 'created_at'):
                            queryset = queryset.filter(created_at__gte=since_datetime)
                        else:
                            continue

                        if queryset.exists():
                            # Serialize
                            data = serializers.serialize('json', queryset)
                            records = json.loads(data)

                            # Remove excluded fields
                            if exclude_fields:
                                for record in records:
                                    for field in exclude_fields:
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
    Upload local changes from desktop to server
    ✅ Handles ForeignKey as instances (not IDs)
    ✅ Handles ManyToMany fields correctly
    ✅ Schema locked for entire operation
    ✅ Skips public schema models
    ✅ Resets sequences after upload
    ✅ Returns ID mappings for offline records
    ✅ Suppresses signals during sync
    ✅ Delta-based Stock updates — preserves concurrent online sales
    """
    authentication_classes = [TenantAwareJWTAuthentication]
    permission_classes = [IsAuthenticated]

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

    def post(self, request):
        try:
            from decimal import Decimal
            from django.db import connection
            from django.db.models import F
            from django.core.exceptions import ValidationError

            changes = request.data.get('changes', {})
            tenant_id = request.data.get('tenant_id')
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
                return Response({
                    'success': True,
                    'message': 'No changes to upload'
                })

            total_created = 0
            total_updated = 0
            total_skipped = 0
            errors = []
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
                                error_msg = f"Schema switched to {connection.schema_name}!"
                                logger.error(f"❌ {error_msg}")
                                errors.append(error_msg)
                                continue

                            if model_name in UPLOAD_PUBLIC_SCHEMA_MODELS:
                                logger.info(f"  ⏭️  Skipping public schema model: {model_name}")
                                total_skipped += len(records)
                                continue

                            model = apps.get_model(model_name)
                            is_stock_model = model._meta.label == 'inventory.Stock'
                            model_mappings = {}

                            logger.info(f"  Processing {model_name}: {len(records)} records")

                            for record in records:
                                try:
                                    desktop_id = record['pk']
                                    fields = record['fields']

                                    # ✅ Extract Stock delta before any field processing
                                    quantity_delta = None
                                    if is_stock_model:
                                        quantity_delta = fields.pop('_quantity_delta', None)

                                    fields.pop('id', None)

                                    m2m_fields = {}
                                    processed_fields = {}

                                    for field_name, value in fields.items():
                                        try:
                                            # ✅ Skip internal sync metadata fields
                                            if field_name.startswith('_'):
                                                continue

                                            field = model._meta.get_field(field_name)

                                            if field.many_to_many:
                                                m2m_fields[field_name] = value
                                                continue

                                            if field.many_to_one and value is not None:
                                                related_model = field.related_model
                                                related_table = related_model._meta.db_table

                                                if related_table in [
                                                    'company_company',
                                                    'company_subscriptionplan'
                                                ]:
                                                    logger.debug(f"      Skipping public FK: {field_name}")
                                                    continue

                                                try:
                                                    related_instance = related_model.objects.get(pk=value)
                                                    processed_fields[field_name] = related_instance
                                                except related_model.DoesNotExist:
                                                    logger.debug(
                                                        f"      Skipping {field_name}={value} - not found"
                                                    )
                                                    continue

                                            elif (hasattr(field, 'get_internal_type') and
                                                  field.get_internal_type() == 'DecimalField'):
                                                if value is not None and isinstance(value, str):
                                                    processed_fields[field_name] = Decimal(value)
                                                else:
                                                    processed_fields[field_name] = value

                                            else:
                                                processed_fields[field_name] = value

                                        except Exception as e:
                                            logger.debug(f"      Skipping field {field_name}: {e}")
                                            continue

                                    is_offline = isinstance(desktop_id, int) and desktop_id < 0

                                    try:
                                        if is_offline:
                                            # Offline record — create with server ID
                                            unique_lookup = self._build_unique_lookup(
                                                model, processed_fields
                                            )

                                            if unique_lookup:
                                                try:
                                                    obj = model.objects.get(**unique_lookup)
                                                    # ✅ Stock delta on offline record
                                                    if is_stock_model and quantity_delta is not None:
                                                        model.objects.filter(pk=obj.pk).update(
                                                            quantity=F('quantity') + quantity_delta
                                                        )
                                                        logger.info(
                                                            f"      ✅ Stock {obj.pk}: "
                                                            f"delta {quantity_delta:+.3f} applied"
                                                        )
                                                        non_qty_fields = {
                                                            k: v for k, v in processed_fields.items()
                                                            if k != 'quantity'
                                                        }
                                                        for f, v in non_qty_fields.items():
                                                            setattr(obj, f, v)
                                                        if non_qty_fields:
                                                            obj.save()
                                                    else:
                                                        for f, v in processed_fields.items():
                                                            setattr(obj, f, v)
                                                        obj.save()

                                                    model_mappings[str(desktop_id)] = obj.pk
                                                    total_updated += 1
                                                    logger.info(
                                                        f"      ✅ Updated existing: "
                                                        f"{desktop_id} → {obj.pk}"
                                                    )
                                                except model.DoesNotExist:
                                                    obj = model(**processed_fields)
                                                    obj.save()
                                                    model_mappings[str(desktop_id)] = obj.pk
                                                    total_created += 1
                                                    logger.info(
                                                        f"      ✅ Created offline: "
                                                        f"{desktop_id} → {obj.pk}"
                                                    )
                                            else:
                                                obj = model(**processed_fields)
                                                obj.save()
                                                model_mappings[str(desktop_id)] = obj.pk
                                                total_created += 1
                                                logger.info(
                                                    f"      ✅ Created offline: "
                                                    f"{desktop_id} → {obj.pk}"
                                                )

                                            for field_name, value in m2m_fields.items():
                                                if value:
                                                    getattr(obj, field_name).set(value)

                                        else:
                                            # Online record — update or create with same ID
                                            try:
                                                obj = model.objects.get(pk=desktop_id)

                                                if is_stock_model and quantity_delta is not None:
                                                    # ✅ Delta-based Stock update
                                                    # Preserves concurrent online sales
                                                    if quantity_delta != 0:
                                                        model.objects.filter(pk=desktop_id).update(
                                                            quantity=F('quantity') + quantity_delta
                                                        )
                                                        logger.info(
                                                            f"      ✅ Stock {desktop_id}: "
                                                            f"delta {quantity_delta:+.3f} applied"
                                                        )
                                                    # Update non-quantity fields normally
                                                    non_qty_fields = {
                                                        k: v for k, v in processed_fields.items()
                                                        if k != 'quantity'
                                                    }
                                                    for f, v in non_qty_fields.items():
                                                        setattr(obj, f, v)
                                                    if non_qty_fields:
                                                        obj.save()

                                                elif is_stock_model and quantity_delta is None:
                                                    # No baseline stored (first sync) — overwrite
                                                    logger.info(
                                                        f"      ⚠️  Stock {desktop_id}: "
                                                        f"no delta baseline, overwriting"
                                                    )
                                                    for f, v in processed_fields.items():
                                                        setattr(obj, f, v)
                                                    obj.save()

                                                else:
                                                    # All other models — normal update
                                                    for f, v in processed_fields.items():
                                                        setattr(obj, f, v)
                                                    obj.save()

                                                for field_name, value in m2m_fields.items():
                                                    if value:
                                                        getattr(obj, field_name).set(value)

                                                total_updated += 1
                                                logger.debug(f"      ✅ Updated: {desktop_id}")

                                            except model.DoesNotExist:
                                                obj = model(pk=desktop_id, **processed_fields)
                                                obj.save()

                                                for field_name, value in m2m_fields.items():
                                                    if value:
                                                        getattr(obj, field_name).set(value)

                                                total_created += 1
                                                logger.info(f"      ✅ Created: {desktop_id}")

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
                                                f"      ⚠️  Validation error for "
                                                f"{desktop_id}: {error_dict}"
                                            )
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
                'id_mappings': id_mappings,
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
    Download data for a specific model
    ✅ Allows incremental sync
    """
    authentication_classes = [TenantAwareJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, model_name):
        try:
            token = request.auth
            schema_name = token.get('schema_name')

            logger.info(f"📥 Download request for {model_name} in schema: {schema_name}")

            # Get query parameters
            since = request.GET.get('since')  # Optional: for incremental sync

            with schema_context(schema_name):
                try:
                    model = apps.get_model(model_name)
                    config = SYNC_MODEL_CONFIG.get(model_name, {})
                    exclude_fields = config.get('exclude_fields', [])

                    # Build queryset
                    queryset = model.objects.all()

                    # Filter by timestamp if provided
                    if since:
                        if hasattr(model, 'modified_at'):
                            queryset = queryset.filter(modified_at__gte=since)
                        elif hasattr(model, 'updated_at'):
                            queryset = queryset.filter(updated_at__gte=since)

                    count = queryset.count()

                    # Serialize
                    data = serializers.serialize('json', queryset)
                    records = json.loads(data)

                    # Remove excluded fields
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
    """
    Get sync status and statistics
    """
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
                    except:
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