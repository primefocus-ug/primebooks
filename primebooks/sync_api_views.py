# primebooks/sync_api_views.py
"""
Server-side API endpoints for desktop sync
✅ Provides data download endpoints
✅ Handles bulk data export for offline use
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.apps import apps
from django.core import serializers
from django_tenants.utils import schema_context
from primebooks.authentication import TenantAwareJWTAuthentication
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