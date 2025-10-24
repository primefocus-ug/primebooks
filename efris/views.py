from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.utils.decorators import method_decorator
from django.views.generic import View
from .websocket_manager import websocket_manager
from company.models import Company


class EFRISWebSocketStatusView(View):
    """API endpoint for WebSocket status information"""

    @method_decorator(login_required)
    def get(self, request, company_id):
        try:
            # Verify user has access to company
            company = Company.objects.get(pk=company_id)
            if not (company.owner == request.user or
                    request.user in company.users.all() or
                    request.user in company.staff.all()):
                return JsonResponse({'error': 'Access denied'}, status=403)

            # Get connection statistics
            stats = websocket_manager.get_connection_stats(company_id)
            connections = websocket_manager.get_active_connections(company_id)

            return JsonResponse({
                'company_id': company_id,
                'company_name': company.display_name,
                'websocket_stats': stats,
                'active_connections': len(connections),
                'connection_details': [
                    {
                        'user_id': conn.get('user_id'),
                        'connected_at': conn.get('connected_at'),
                        'user_agent': conn.get('user_agent', '')[:100]  # Truncate
                    }
                    for conn in connections[:10]  # Limit to 10 for performance
                ]
            })

        except Company.DoesNotExist:
            return JsonResponse({'error': 'Company not found'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["POST"])
@login_required
def test_websocket_broadcast(request, company_id):
    """Test endpoint to broadcast a message via WebSocket"""
    try:
        company = Company.objects.get(pk=company_id)

        # Verify access
        if not (company.owner == request.user or
                request.user in company.users.all() or
                request.user in company.staff.all()):
            return JsonResponse({'error': 'Access denied'}, status=403)

        # Send test notification
        success = websocket_manager.send_notification(
            company_id,
            "Test Message",
            f"Test message sent by {request.user.get_full_name() or request.user.username} at {timezone.now()}",
            "info",
            "normal",
            {'sent_by': request.user.id, 'test': True}
        )

        return JsonResponse({
            'success': success,
            'message': 'Test broadcast sent' if success else 'Failed to send broadcast'
        })

    except Company.DoesNotExist:
        return JsonResponse({'error': 'Company not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)



# from rest_framework.views import APIView
# from rest_framework.response import Response
# from rest_framework import status
# from rest_framework.decorators import api_view, permission_classes
# from rest_framework.permissions import IsAuthenticated
# from django.shortcuts import get_object_or_404
# from django.http import JsonResponse
# from django.views.decorators.csrf import csrf_exempt
# from django.utils.decorators import method_decorator
# from django.db import transaction
# from django.core.paginator import Paginator
# import logging
# from django.shortcuts import render
# from django.contrib.auth.decorators import login_required
# from django.http import JsonResponse
# from django.views.decorators.http import require_http_methods
# from cryptography import x509
# from cryptography.x509.oid import NameOID
# from cryptography.hazmat.primitives import serialization, hashes
# from cryptography.hazmat.primitives.asymmetric import rsa
# import base64
# import hashlib
# from datetime import timedelta
# from django.utils import timezone
#
# from .services import (
#     EnhancedEFRISAPIClient,
#     EFRISInvoiceService,
#     EFRISProductService,
#     EFRISHealthChecker,
#     EFRISConfigurationWizard,
#     setup_efris_for_company,
#     validate_efris_configuration,
#     SecurityManager
# )
# from .models import EFRISConfiguration, EFRISAPILog, FiscalizationAudit, EFRISDigitalKey, EFRISSystemDictionary, EFRISNotification, EFRISErrorPattern
# from .tasks import fiscalize_invoice_task, sync_system_dictionaries_task, upload_products_task
# from company.models import Company
# from invoices.models import Invoice
# from inventory.models import Product
#
# logger = logging.getLogger(__name__)
#
#
# class EFRISConfigurationView(APIView):
#     """EFRIS Configuration Management"""
#     permission_classes = [IsAuthenticated]
#
#     def get(self, request):
#         """Get EFRIS configuration for user's company"""
#         try:
#             company = request.user.company
#
#             try:
#                 config = EFRISConfiguration.objects.get(company=company)
#
#                 # Validate configuration
#                 is_valid, errors = validate_efris_configuration(company)
#
#                 return Response({
#                     'success': True,
#                     'configuration': {
#                         'environment': config.environment,
#                         'mode': config.mode,
#                         'is_initialized': config.is_initialized,
#                         'is_active': config.is_active,
#                         'last_test_connection': config.last_test_connection,
#                         'test_connection_success': config.test_connection_success,
#                         'device_mac': config.device_mac,
#                         'device_number': config.device_number,
#                         'certificate_expires_at': config.certificate_expires_at,
#                         'last_dictionary_sync': config.last_dictionary_sync
#                     },
#                     'validation': {
#                         'is_valid': is_valid,
#                         'errors': errors
#                     },
#                     'company_settings': {
#                         'efris_enabled': company.efris_enabled,
#                         'efris_is_production': company.efris_is_production,
#                         'efris_integration_mode': company.efris_integration_mode,
#                         'efris_auto_fiscalize_sales': company.efris_auto_fiscalize_sales,
#                         'efris_auto_sync_products': company.efris_auto_sync_products
#                     }
#                 })
#
#             except EFRISConfiguration.DoesNotExist:
#                 return Response({
#                     'success': False,
#                     'error': 'EFRIS configuration not found',
#                     'configuration': None
#                 })
#
#         except Exception as e:
#             logger.error(f"Failed to get EFRIS configuration: {e}")
#             return Response({
#                 'success': False,
#                 'error': str(e)
#             }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
#
#     def post(self, request):
#         """Create or update EFRIS configuration"""
#         try:
#             company = request.user.company
#             data = request.data
#
#             with transaction.atomic():
#                 config, created = EFRISConfiguration.objects.get_or_create(
#                     company=company,
#                     defaults={
#                         'environment': data.get('environment', 'sandbox'),
#                         'mode': data.get('mode', 'online'),
#                         'device_mac': data.get('device_mac', 'FFFFFFFFFFFF'),
#                         'app_id': 'AP04',
#                         'version': '1.1.20191201'
#                     }
#                 )
#
#                 # Update configuration
#                 if not created:
#                     for field in ['environment', 'mode', 'device_mac', 'timeout_seconds']:
#                         if field in data:
#                             setattr(config, field, data[field])
#
#                 # Set API URL based on environment
#                 if data.get('environment') == 'production':
#                     config.api_base_url = 'https://efrisws.ura.go.ug/ws/taapp/getInformation'
#                 else:
#                     config.api_base_url = 'https://efristest.ura.go.ug/efrisws/ws/taapp/getInformation'
#
#                 config.save()
#
#                 # Update company EFRIS settings
#                 company_updates = {}
#                 efris_fields = [
#                     'efris_enabled', 'efris_is_production', 'efris_integration_mode',
#                     'efris_auto_fiscalize_sales', 'efris_auto_sync_products'
#                 ]
#
#                 for field in efris_fields:
#                     if field in data:
#                         company_updates[field] = data[field]
#
#                 if company_updates:
#                     for field, value in company_updates.items():
#                         setattr(company, field, value)
#                     company.save()
#
#                 return Response({
#                     'success': True,
#                     'message': 'Configuration updated successfully' if not created else 'Configuration created successfully' if not created else 'Configuration created successfully',
#                     'created': created
#                 })
#
#         except Exception as e:
#             logger.error(f"Failed to save EFRIS configuration: {e}")
#             return Response({
#                 'success': False,
#                 'error': str(e)
#             }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
#
#
# class EFRISHealthCheckView(APIView):
#     """EFRIS System Health Check"""
#     permission_classes = [IsAuthenticated]
#
#     def get(self, request):
#         """Perform EFRIS health check"""
#         try:
#             company = request.user.company
#             health_checker = EFRISHealthChecker(company)
#             health_status = health_checker.check_system_health()
#
#             return Response({
#                 'success': True,
#                 'health_status': health_status
#             })
#
#         except Exception as e:
#             logger.error(f"Health check failed: {e}")
#             return Response({
#                 'success': False,
#                 'error': str(e)
#             }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
#
#
# class InvoiceFiscalizationView(APIView):
#     """Invoice Fiscalization Management"""
#     permission_classes = [IsAuthenticated]
#
#     def post(self, request, invoice_id):
#         """Fiscalize a single invoice"""
#         try:
#             invoice = get_object_or_404(Invoice, id=invoice_id)
#
#             # Check permissions
#             if not request.user.can_fiscalize(invoice.store):
#                 return Response({
#                     'success': False,
#                     'error': 'You do not have permission to fiscalize invoices for this store'
#                 }, status=status.HTTP_403_FORBIDDEN)
#
#             # Get company from invoice
#             company = invoice.store.branch.company if invoice.store else request.user.company
#
#             # Check if async processing is requested
#             async_processing = request.data.get('async', False)
#
#             if async_processing:
#                 # Queue for async processing
#                 task = fiscalize_invoice_task.delay(company.id, invoice.id, request.user.id if request.user.is_authenticated else None)
#
#                 return Response({
#                     'success': True,
#                     'message': 'Invoice queued for fiscalization',
#                     'task_id': task.id,
#                     'async': True
#                 })
#             else:
#                 # Process synchronously
#                 invoice_service = EFRISInvoiceService(company)
#                 success, message = invoice_service.fiscalize_invoice(invoice, request.user)
#
#                 return Response({
#                     'success': success,
#                     'message': message,
#                     'fiscal_number': invoice.fiscal_document_number if success else None,
#                     'verification_code': invoice.verification_code if success else None
#                 })
#
#         except Exception as e:
#             logger.error(f"Invoice fiscalization failed: {e}")
#             return Response({
#                 'success': False,
#                 'error': str(e)
#             }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
#
#
# class BulkInvoiceFiscalizationView(APIView):
#     """Bulk Invoice Fiscalization"""
#     permission_classes = [IsAuthenticated]
#
#     def post(self, request):
#         """Fiscalize multiple invoices"""
#         try:
#             invoice_ids = request.data.get('invoice_ids', [])
#
#             if not invoice_ids:
#                 return Response({
#                     'success': False,
#                     'error': 'No invoice IDs provided'
#                 }, status=status.HTTP_400_BAD_REQUEST)
#
#             # Validate invoices exist and user has permission
#             invoices = Invoice.objects.filter(id__in=invoice_ids).select_related('store')
#
#             for invoice in invoices:
#                 if not request.user.can_fiscalize(invoice.store):
#                     return Response({
#                         'success': False,
#                         'error': f'No permission to fiscalize invoice {invoice.invoice_number}'
#                     }, status=status.HTTP_403_FORBIDDEN)
#
#             company = request.user.company
#             invoice_service = EFRISInvoiceService(company)
#
#             # Process bulk fiscalization
#             results = invoice_service.bulk_fiscalize_invoices(list(invoices), request.user)
#
#             return Response({
#                 'success': results['success'],
#                 'message': results['message'],
#                 'results': results
#             })
#
#         except Exception as e:
#             logger.error(f"Bulk fiscalization failed: {e}")
#             return Response({
#                 'success': False,
#                 'error': str(e)
#             }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
#
#
# class ProductUploadView(APIView):
#     """Product Upload to EFRIS"""
#     permission_classes = [IsAuthenticated]
#
#     def post(self, request):
#         """Upload products to EFRIS"""
#         try:
#             company = request.user.company
#             product_ids = request.data.get('product_ids', [])
#             async_processing = request.data.get('async', False)
#
#             if async_processing:
#                 # Queue for async processing
#                 task = upload_products_task.delay(company.id, product_ids)
#
#                 return Response({
#                     'success': True,
#                     'message': 'Products queued for upload',
#                     'task_id': task.id,
#                     'async': True
#                 })
#             else:
#                 # Get products
#                 if product_ids:
#                     products = Product.objects.filter(id__in=product_ids, is_active=True)
#                 else:
#                     products = Product.objects.filter(
#                         efris_is_uploaded=False,
#                         efris_auto_sync_enabled=True,
#                         is_active=True
#                     )[:50]
#
#                 if not products.exists():
#                     return Response({
#                         'success': True,
#                         'message': 'No products to upload',
#                         'uploaded_count': 0
#                     })
#
#                 # Upload products
#                 product_service = EFRISProductService(company)
#                 success, message = product_service.upload_products(list(products))
#
#                 return Response({
#                     'success': success,
#                     'message': message,
#                     'uploaded_count': products.count() if success else 0
#                 })
#
#         except Exception as e:
#             logger.error(f"Product upload failed: {e}")
#             return Response({
#                 'success': False,
#                 'error': str(e)
#             }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
#
#
# class EFRISLogsView(APIView):
#     """EFRIS API Logs"""
#     permission_classes = [IsAuthenticated]
#
#     def get(self, request):
#         """Get EFRIS API logs"""
#         try:
#             company = request.user.company
#
#             # Pagination
#             page = int(request.GET.get('page', 1))
#             per_page = min(int(request.GET.get('per_page', 20)), 100)
#
#             # Filters
#             interface_code = request.GET.get('interface_code')
#             status_filter = request.GET.get('status')
#             start_date = request.GET.get('start_date')
#             end_date = request.GET.get('end_date')
#
#             # Base queryset
#             logs = EFRISAPILog.objects.filter(company=company).order_by('-request_time')
#
#             # Apply filters
#             if interface_code:
#                 logs = logs.filter(interface_code=interface_code)
#             if status_filter:
#                 logs = logs.filter(status=status_filter)
#             if start_date:
#                 logs = logs.filter(request_time__date__gte=start_date)
#             if end_date:
#                 logs = logs.filter(request_time__date__lte=end_date)
#
#             # Paginate
#             paginator = Paginator(logs, per_page)
#             page_obj = paginator.get_page(page)
#
#             # Format response
#             log_data = []
#             for log in page_obj:
#                 log_data.append({
#                     'id': log.id,
#                     'interface_code': log.interface_code,
#                     'status': log.status,
#                     'return_code': log.return_code,
#                     'return_message': log.return_message,
#                     'duration_ms': log.duration_ms,
#                     'request_time': log.request_time,
#                     'response_time': log.response_time,
#                     'invoice_id': log.invoice.id if log.invoice else None,
#                     'product_id': log.product.id if log.product else None
#                 })
#
#             return Response({
#                 'success': True,
#                 'logs': log_data,
#                 'pagination': {
#                     'current_page': page_obj.number,
#                     'total_pages': paginator.num_pages,
#                     'total_count': paginator.count,
#                     'per_page': per_page,
#                     'has_next': page_obj.has_next(),
#                     'has_previous': page_obj.has_previous()
#                 }
#             })
#
#         except Exception as e:
#             logger.error(f"Failed to get EFRIS logs: {e}")
#             return Response({
#                 'success': False,
#                 'error': str(e)
#             }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
#
#
# class EFRISSetupWizardView(APIView):
#     """EFRIS Setup Wizard"""
#     permission_classes = [IsAuthenticated]
#
#     def get(self, request):
#         """Get setup checklist and wizard info"""
#         try:
#             company = request.user.company
#             wizard = EFRISConfigurationWizard(company)
#             checklist = wizard.generate_setup_checklist()
#
#             return Response({
#                 'success': True,
#                 'checklist': checklist
#             })
#
#         except Exception as e:
#             logger.error(f"Setup wizard failed: {e}")
#             return Response({
#                 'success': False,
#                 'error': str(e)
#             }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
#
#     def post(self, request):
#         """Run complete EFRIS setup"""
#         try:
#             company = request.user.company
#             setup_result = setup_efris_for_company(company)
#
#             return Response({
#                 'success': setup_result['success'],
#                 'message': setup_result.get('message', 'Setup completed'),
#                 'steps_completed': setup_result.get('steps_completed', []),
#                 'errors': setup_result.get('errors', []),
#                 'warnings': setup_result.get('warnings', []),
#                 'health_status': setup_result.get('health_status')
#             })
#
#         except Exception as e:
#             logger.error(f"EFRIS setup failed: {e}")
#             return Response({
#                 'success': False,
#                 'error': str(e)
#             }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
#
#
# @api_view(['POST'])
# @permission_classes([IsAuthenticated])
# def test_efris_connection(request):
#     """Test EFRIS API connection"""
#     try:
#         company = request.user.company
#
#         with EnhancedEFRISAPIClient(company) as client:
#             # Test server time
#             response = client.get_server_time()
#
#             if response.success:
#                 return Response({
#                     'success': True,
#                     'message': 'Connection test successful',
#                     'server_time': response.data.get('serverTime') if response.data else None,
#                     'duration_ms': response.duration_ms
#                 })
#             else:
#                 return Response({
#                     'success': False,
#                     'message': f'Connection test failed: {response.error_message}',
#                     'error_code': response.error_code
#                 })
#
#     except Exception as e:
#         logger.error(f"Connection test failed: {e}")
#         return Response({
#             'success': False,
#             'error': str(e)
#         }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
#
#
# @api_view(['POST'])
# @permission_classes([IsAuthenticated])
# def sync_efris_dictionaries(request):
#     """Sync EFRIS system dictionaries"""
#     try:
#         company = request.user.company
#
#         task = sync_system_dictionaries_task.delay(company.id)
#
#         return Response({
#             'success': True,
#             'message': 'Dictionary sync queued',
#             'task_id': task.id
#         })
#
#     except Exception as e:
#         logger.error(f"Dictionary sync failed: {e}")
#         return Response({
#             'success': False,
#             'error': str(e)
#         }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
#
#
# @api_view(['GET'])
# @permission_classes([IsAuthenticated])
# def get_fiscalization_audit(request, invoice_id):
#     """Get fiscalization audit trail for an invoice"""
#     try:
#         invoice = get_object_or_404(Invoice, id=invoice_id)
#
#         # Check permissions
#         if invoice.store and not request.user.can_fiscalize(invoice.store):
#             return Response({
#                 'success': False,
#                 'error': 'Permission denied'
#             }, status=status.HTTP_403_FORBIDDEN)
#
#         audits = FiscalizationAudit.objects.filter(
#             invoice=invoice
#         ).order_by('-created_at')
#
#         audit_data = []
#         for audit in audits:
#             audit_data.append({
#                 'id': audit.id,
#                 'action': audit.action,
#                 'status': audit.status,
#                 'user': audit.user.get_full_name() if audit.user else None,
#                 'fiscal_document_number': audit.fiscal_document_number,
#                 'verification_code': audit.verification_code,
#                 'error_message': audit.error_message,
#                 'duration_seconds': audit.duration_seconds,
#                 'created_at': audit.created_at,
#                 'completed_at': audit.completed_at,
#                 'retry_count': audit.retry_count
#             })
#
#         return Response({
#             'success': True,
#             'audits': audit_data,
#             'invoice': {
#                 'id': invoice.id,
#                 'invoice_number': invoice.invoice_number,
#                 'is_fiscalized': invoice.is_fiscalized,
#                 'fiscalization_status': invoice.fiscalization_status
#             }
#         })
#
#     except Exception as e:
#         logger.error(f"Failed to get audit trail: {e}")
#         return Response({
#             'success': False,
#             'error': str(e)
#         }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
#
#
# class DigitalKeyView(APIView):
#     permission_classes = [IsAuthenticated]
#
#     def get(self, request):
#         """List digital keys"""
#         company = request.user.company
#         keys = EFRISDigitalKey.objects.filter(company=company).order_by('-uploaded_at')
#         data = []
#         for key in keys:
#             data.append({
#                 'id': key.id,
#                 'key_type': key.key_type,
#                 'status': key.status,
#                 'valid_from': key.valid_from,
#                 'valid_until': key.valid_until,
#                 'uploaded_to_ura': key.uploaded_to_ura,
#                 'ura_upload_date': key.ura_upload_date,
#                 'fingerprint': key.fingerprint,
#                 'subject_name': key.subject_name,
#                 'uploaded_at': key.uploaded_at
#             })
#         return Response({
#             'success': True,
#             'keys': data
#         })
#
#     def post(self, request):
#         """Generate or upload digital key"""
#         try:
#             company = request.user.company
#             action = request.data.get('action', 'generate')  # 'generate' or 'upload'
#
#             if action == 'generate':
#                 # Generate self-signed certificate
#                 security = SecurityManager()
#                 private_key, public_key = security.generate_rsa_keypair()
#
#                 # Create self-signed certificate
#                 subject_name = request.data.get('subject_name', company.efris_business_name or 'EFRIS Test')
#
#                 builder = x509.CertificateBuilder()
#                 builder = builder.subject_name(x509.Name([
#                     x509.NameAttribute(NameOID.COMMON_NAME, subject_name),
#                 ]))
#                 builder = builder.issuer_name(x509.Name([
#                     x509.NameAttribute(NameOID.COMMON_NAME, subject_name),
#                 ]))
#                 builder = builder.public_key(public_key)
#                 builder = builder.serial_number(x509.random_serial_number())
#                 builder = builder.not_valid_before(timezone.now() - timedelta(days=1))
#                 builder = builder.not_valid_after(timezone.now() + timedelta(days=365 * int(request.data.get('valid_years', 1))))
#                 certificate = builder.sign(private_key, hashes.SHA256())
#
#                 # Export certificate (X.509 DER for public)
#                 cert_der = certificate.public_bytes(serialization.Encoding.DER)
#                 public_cert_b64 = base64.b64encode(cert_der).decode('utf-8')
#
#                 # Export private key as PKCS12
#                 p12 = serialization.pkcs12.serialize_key_and_certificates(
#                     name=subject_name.encode('utf-8'),
#                     private_key=private_key,
#                     certificate=certificate,
#                     cas=None,
#                     encryption_algorithm=serialization.NoEncryption()
#                 )
#                 private_p12_b64 = base64.b64encode(p12).decode('utf-8')
#
#                 # Thumbprint (SHA256 of DER cert)
#                 thumbprint = hashlib.sha256(cert_der).hexdigest()
#
#                 # Create digital key model
#                 digital_key = EFRISDigitalKey.objects.create(
#                     company=company,
#                     key_type='self_signed',
#                     status='active',
#                     private_key=private_p12_b64,
#                     public_certificate=public_cert_b64,
#                     key_password='',  # No password
#                     valid_from=certificate.not_valid_before,
#                     valid_until=certificate.not_valid_after,
#                     fingerprint=thumbprint,
#                     subject_name=subject_name,
#                     issuer_name=subject_name,
#                     serial_number=str(certificate.serial_number),
#                     uploaded_by=request.user
#                 )
#
#                 # Update company fields
#                 company.public_key = public_cert_b64
#                 company.private_key = private_p12_b64
#                 company.thumbprint = thumbprint
#                 company.save()
#
#                 return Response({
#                     'success': True,
#                     'message': 'Digital key generated successfully',
#                     'key_id': digital_key.id,
#                     'thumbprint': thumbprint
#                 })
#
#             elif action == 'upload':
#                 # Handle uploaded files
#                 private_file = request.FILES.get('private_key')
#                 public_file = request.FILES.get('public_certificate')
#                 password = request.data.get('password', '')
#
#                 if not private_file or not public_file:
#                     return Response({
#                         'success': False,
#                         'error': 'Private key and public certificate files are required'
#                     }, status=status.HTTP_400_BAD_REQUEST)
#
#                 private_data = private_file.read()
#                 public_data = public_file.read()
#
#                 # Validate
#                 try:
#                     private_key = serialization.load_pem_private_key(
#                         private_data,
#                         password=password.encode() if password else None
#                     )
#                     certificate = x509.load_pem_x509_certificate(public_data)
#                 except Exception as e:
#                     return Response({
#                         'success': False,
#                         'error': f'Invalid key files: {str(e)}'
#                     }, status=status.HTTP_400_BAD_REQUEST)
#
#                 # Base64 encode
#                 private_b64 = base64.b64encode(private_data).decode('utf-8')
#                 public_b64 = base64.b64encode(public_data).decode('utf-8')
#
#                 # Thumbprint
#                 thumbprint = hashlib.sha256(public_data).hexdigest()
#
#                 digital_key = EFRISDigitalKey.objects.create(
#                     company=company,
#                     key_type='ca_issued',
#                     status='active',
#                     private_key=private_b64,
#                     public_certificate=public_b64,
#                     key_password=password,
#                     valid_from=certificate.not_valid_before,
#                     valid_until=certificate.not_valid_after,
#                     fingerprint=thumbprint,
#                     subject_name=certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value,
#                     issuer_name=certificate.issuer.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value,
#                     serial_number=str(certificate.serial_number),
#                     uploaded_by=request.user
#                 )
#
#                 # Update company
#                 company.public_key = public_b64
#                 company.private_key = private_b64
#                 company.thumbprint = thumbprint
#                 company.save()
#
#                 return Response({
#                     'success': True,
#                     'message': 'Digital key uploaded successfully',
#                     'key_id': digital_key.id,
#                     'thumbprint': thumbprint
#                 })
#
#             else:
#                 return Response({
#                     'success': False,
#                     'error': 'Invalid action. Use "generate" or "upload"'
#                 }, status=status.HTTP_400_BAD_REQUEST)
#
#         except Exception as e:
#             logger.error(f"Digital key operation failed: {e}")
#             return Response({
#                 'success': False,
#                 'error': str(e)
#             }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
#
#
# class CertificateUploadView(APIView):
#     """Upload certificate to URA"""
#     permission_classes = [IsAuthenticated]
#
#     def post(self, request):
#         try:
#             company = request.user.company
#             key_id = request.data.get('key_id')
#             verify_string = request.data.get('verify_string')
#
#             if not verify_string:
#                 return Response({
#                     'success': False,
#                     'error': 'Verification string is required'
#                 }, status=status.HTTP_400_BAD_REQUEST)
#
#             digital_key = get_object_or_404(EFRISDigitalKey, id=key_id, company=company)
#
#             # Get public certificate bytes
#             cert_b64 = digital_key.public_certificate
#             certificate_file = base64.b64decode(cert_b64)
#
#             with EnhancedEFRISAPIClient(company) as client:
#                 response = client.upload_certificate(certificate_file, verify_string)
#
#             if response.success:
#                 digital_key.uploaded_to_ura = True
#                 digital_key.ura_upload_date = timezone.now()
#                 digital_key.ura_response = response.data or {}
#                 digital_key.save()
#
#                 return Response({
#                     'success': True,
#                     'message': 'Certificate uploaded successfully',
#                     'ura_response': response.data
#                 })
#             else:
#                 return Response({
#                     'success': False,
#                     'error': response.error_message,
#                     'error_code': response.error_code
#                 })
#
#         except Exception as e:
#             logger.error(f"Certificate upload failed: {e}")
#             return Response({
#                 'success': False,
#                 'error': str(e)
#             }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
#
#
# class FiscalizationAuditListView(APIView):
#     """List fiscalization audits"""
#     permission_classes = [IsAuthenticated]
#
#     def get(self, request):
#         try:
#             company = request.user.company
#
#             # Pagination
#             page = int(request.GET.get('page', 1))
#             per_page = min(int(request.GET.get('per_page', 20)), 100)
#
#             # Filters
#             action = request.GET.get('action')
#             status = request.GET.get('status')
#             start_date = request.GET.get('start_date')
#             end_date = request.GET.get('end_date')
#
#             audits = FiscalizationAudit.objects.filter(company=company).order_by('-created_at')
#
#             if action:
#                 audits = audits.filter(action=action)
#             if status:
#                 audits = audits.filter(status=status)
#             if start_date:
#                 audits = audits.filter(created_at__date__gte=start_date)
#             if end_date:
#                 audits = audits.filter(created_at__date__lte=end_date)
#
#             paginator = Paginator(audits, per_page)
#             page_obj = paginator.get_page(page)
#
#             data = []
#             for audit in page_obj:
#                 data.append({
#                     'id': audit.id,
#                     'action': audit.action,
#                     'status': audit.status,
#                     'invoice_number': audit.invoice_number,
#                     'fiscal_document_number': audit.fiscal_document_number,
#                     'error_message': audit.error_message,
#                     'duration_seconds': audit.duration_seconds,
#                     'created_at': audit.created_at,
#                     'retry_count': audit.retry_count,
#                     'severity': audit.severity
#                 })
#
#             return Response({
#                 'success': True,
#                 'audits': data,
#                 'pagination': {
#                     'current_page': page_obj.number,
#                     'total_pages': paginator.num_pages,
#                     'total_count': paginator.count,
#                     'per_page': per_page
#                 }
#             })
#
#         except Exception as e:
#             logger.error(f"Failed to list audits: {e}")
#             return Response({
#                 'success': False,
#                 'error': str(e)
#             }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
#
#
# class EFRISNotificationView(APIView):
#     """EFRIS Notifications"""
#     permission_classes = [IsAuthenticated]
#
#     def get(self, request):
#         """Get notifications"""
#         try:
#             company = request.user.company
#             status_filter = request.GET.get('status', 'unread')
#
#             notifications = EFRISNotification.objects.filter(company=company)
#             if status_filter:
#                 notifications = notifications.filter(status=status_filter)
#
#             notifications = notifications.order_by('-created_at')[:50]
#
#             data = []
#             for n in notifications:
#                 data.append({
#                     'id': n.id,
#                     'type': n.notification_type,
#                     'priority': n.priority,
#                     'title': n.title,
#                     'message': n.message,
#                     'status': n.status,
#                     'created_at': n.created_at,
#                     'action_url': n.action_url,
#                     'action_label': n.action_label
#                 })
#
#             return Response({
#                 'success': True,
#                 'notifications': data
#             })
#
#         except Exception as e:
#             logger.error(f"Failed to get notifications: {e}")
#             return Response({
#                 'success': False,
#                 'error': str(e)
#             }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
#
#     def post(self, request, notification_id):
#         """Mark notification as read"""
#         try:
#             notification = get_object_or_404(EFRISNotification, id=notification_id, company=request.user.company)
#             notification.mark_as_read(request.user)
#             return Response({
#                 'success': True,
#                 'message': 'Notification marked as read'
#             })
#
#         except Exception as e:
#             logger.error(f"Failed to mark notification: {e}")
#             return Response({
#                 'success': False,
#                 'error': str(e)
#             }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
#
#
# class ErrorPatternView(APIView):
#     """EFRIS Error Patterns"""
#     permission_classes = [IsAuthenticated]
#
#     def get(self, request):
#         """Get error patterns"""
#         try:
#             company = request.user.company
#             patterns = EFRISErrorPattern.objects.filter(company=company).order_by('-last_occurred')
#
#             data = []
#             for p in patterns:
#                 data.append({
#                     'id': p.id,
#                     'error_code': p.error_code,
#                     'error_message': p.error_message,
#                     'interface_code': p.interface_code,
#                     'occurrence_count': p.occurrence_count,
#                     'first_occurred': p.first_occurred,
#                     'last_occurred': p.last_occurred,
#                     'is_resolved': p.is_resolved,
#                     'suggested_solution': p.suggested_solution
#                 })
#
#             return Response({
#                 'success': True,
#                 'patterns': data
#             })
#
#         except Exception as e:
#             logger.error(f"Failed to get error patterns: {e}")
#             return Response({
#                 'success': False,
#                 'error': str(e)
#             }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
#
#
# @login_required
# def efris_dashboard(request):
#     """EFRIS Dashboard view"""
#     try:
#         company = request.user.company
#
#         # Get recent logs
#         recent_logs = EFRISAPILog.objects.filter(
#             company=company
#         ).order_by('-request_time')[:10]
#
#         # Get configuration
#         try:
#             config = EFRISConfiguration.objects.get(company=company)
#         except EFRISConfiguration.DoesNotExist:
#             config = None
#
#         # Get health status
#         try:
#             health_checker = EFRISHealthChecker(company)
#             health_status = health_checker.check_system_health()
#         except Exception as e:
#             health_status = {
#                 'overall_status': 'error',
#                 'error': str(e)
#             }
#
#         context = {
#             'company': company,
#             'config': config,
#             'recent_logs': recent_logs,
#             'health_status': health_status,
#             'efris_enabled': company.efris_enabled
#         }
#
#         return render(request, 'efris/dashboard.html', context)
#
#     except Exception as e:
#         logger.error(f"Dashboard view failed: {e}")
#         return render(request, 'efris/error.html', {'error': str(e)})
#
#
# @login_required
# @require_http_methods(["GET"])
# def efris_metrics_api(request):
#     """API endpoint for EFRIS metrics"""
#     try:
#         from .services import EFRISMetricsCollector
#
#         company = request.user.company
#         time_range = int(request.GET.get('hours', 24))
#
#         metrics = EFRISMetricsCollector.get_system_metrics(company, time_range)
#
#         return JsonResponse({
#             'success': True,
#             'metrics': metrics
#         })
#
#     except Exception as e:
#         logger.error(f"Metrics API failed: {e}")
#         return JsonResponse({
#             'success': False,
#             'error': str(e)
#         }, status=500)