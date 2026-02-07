# primebooks/sync_api_views.py
"""
Server-side API endpoints for desktop sync
✅ Provides data download endpoints
✅ Handles bulk data export for offline use
✅ Handles incremental sync (changes only)
✅ Handles upload of local changes
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

logger = logging.getLogger(__name__)

# Model configuration for sync
SYNC_MODEL_CONFIG = {
    'company.SubscriptionPlan': {'dependencies': []},
    'company.Company': {'dependencies': ['company.SubscriptionPlan']},
    'accounts.Role': {'dependencies': ['company.Company']},
    'accounts.CustomUser': {
        'dependencies': ['company.Company', 'accounts.Role'],
        'exclude_fields': ['password', 'backup_codes'],
    },
    'stores.Store': {
        'dependencies': ['company.Company'],
        'exclude_fields': ['logo', 'store_efris_private_key'],
    },
    'stores.StoreAccess': {'dependencies': ['stores.Store', 'accounts.CustomUser']},
    'inventory.Category': {'dependencies': ['company.Company']},
    'inventory.Supplier': {'dependencies': []},
    'inventory.Product': {
        'dependencies': ['inventory.Category', 'inventory.Supplier'],
        'exclude_fields': ['image'],
    },
    'inventory.Stock': {'dependencies': ['inventory.Product', 'stores.Store']},
    'customers.Customer': {'dependencies': ['stores.Store', 'accounts.CustomUser']},
    'sales.Sale': {'dependencies': ['customers.Customer', 'stores.Store', 'accounts.CustomUser']},
    'sales.SaleItem': {'dependencies': ['sales.Sale', 'inventory.Product']},
    'invoices.Invoice': {'dependencies': ['sales.Sale', 'stores.Store']},
}


class BulkDataDownloadView(APIView):
    """
    Download ALL data for a tenant
    ✅ Returns complete dataset for offline use
    """
    authentication_classes = [TenantAwareJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            # Get schema from JWT token
            token = request.auth
            schema_name = token.get('schema_name')
            company_id = token.get('company_id')

            logger.info(f"📥 Bulk download request for schema: {schema_name}")

            # Collect all data
            all_data = {}
            total_records = 0

            with schema_context(schema_name):
                for model_name in SYNC_MODEL_CONFIG.keys():
                    try:
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
    """
    authentication_classes = [TenantAwareJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
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

            with schema_context(schema_name):
                for model_name in SYNC_MODEL_CONFIG.keys():
                    try:
                        model = apps.get_model(model_name)
                        config = SYNC_MODEL_CONFIG.get(model_name, {})
                        exclude_fields = config.get('exclude_fields', [])

                        # Build queryset
                        queryset = model.objects.all()

                        # Filter by modification time
                        if hasattr(model, 'modified_at'):
                            queryset = queryset.filter(modified_at__gte=since_datetime)
                        elif hasattr(model, 'updated_at'):
                            queryset = queryset.filter(updated_at__gte=since_datetime)
                        elif hasattr(model, 'created_at'):
                            queryset = queryset.filter(created_at__gte=since_datetime)
                        else:
                            # No timestamp field - skip
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
    ✅ Handles create/update with conflict resolution
    """
    authentication_classes = [TenantAwareJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            # Get data from request
            changes = request.data.get('changes', {})
            tenant_id = request.data.get('tenant_id')
            schema_name = request.data.get('schema_name')
            last_sync = request.data.get('last_sync')

            # Verify schema from token matches request
            token = request.auth
            token_schema = token.get('schema_name')

            if token_schema != schema_name:
                return Response(
                    {'success': False, 'error': 'Schema mismatch'},
                    status=status.HTTP_403_FORBIDDEN
                )

            logger.info(f"📤 Upload request for schema: {schema_name}")
            logger.info(f"  Changes: {len(changes)} models")
            logger.info(f"  Last sync: {last_sync}")

            if not changes:
                return Response({
                    'success': True,
                    'message': 'No changes to upload'
                })

            # Import sync functionality
            from primebooks.sync import SyncManager

            # Apply changes to server database
            total_created = 0
            total_updated = 0
            errors = []

            with schema_context(schema_name):
                for model_name, records in changes.items():
                    try:
                        # Use SyncManager's apply_model_data method
                        # Note: We need the actual token string, not the JWT object
                        # The token is already validated by authentication_classes
                        sync_manager = SyncManager(
                            tenant_id=tenant_id,
                            schema_name=schema_name,
                            auth_token=request.META.get('HTTP_AUTHORIZATION', '').replace('Bearer ', '')
                        )

                        created, updated = sync_manager.apply_model_data(model_name, records)
                        total_created += created
                        total_updated += updated

                        logger.info(f"  ✅ {model_name}: {created} created, {updated} updated")

                    except Exception as e:
                        error_msg = f"Error processing {model_name}: {str(e)}"
                        logger.error(f"  ❌ {error_msg}")
                        errors.append(error_msg)

            if errors:
                logger.warning(f"⚠️  Upload completed with {len(errors)} errors")
                return Response({
                    'success': True,
                    'message': f'Upload completed with errors',
                    'created': total_created,
                    'updated': total_updated,
                    'errors': errors
                }, status=status.HTTP_207_MULTI_STATUS)
            else:
                logger.info(f"✅ Upload complete: {total_created} created, {total_updated} updated")
                return Response({
                    'success': True,
                    'message': 'Upload successful',
                    'created': total_created,
                    'updated': total_updated
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