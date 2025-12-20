import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.http import JsonResponse, HttpResponse, Http404
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.views.generic import TemplateView
from django.urls import reverse

from .models import (
    EFRISConfiguration, EFRISAPILog, FiscalizationAudit,
    EFRISSystemDictionary
)
from .services import (
    EnhancedEFRISAPIClient, EFRISProductService, EFRISCustomerService,
    EFRISInvoiceService, EFRISHealthChecker, EFRISMetricsCollector,
    EFRISConfigurationWizard, create_efris_service, validate_efris_configuration,
    setup_efris_for_company, EFRISError, EFRISConstants, OperationStatus
)

logger = logging.getLogger(__name__)


class EFRISDashboardView(TemplateView):
    """Main EFRIS dashboard view"""
    template_name = 'efris/dashboards.html'

    @method_decorator(login_required)
    @method_decorator(staff_member_required)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = self.request.user.company

        try:
            # Get configuration status
            config = EFRISConfiguration.objects.filter(company=company).first()
            context['has_config'] = bool(config)
            context['config'] = config

            if config:
                # Get system health
                health_checker = EFRISHealthChecker(company)
                context['health_status'] = health_checker.check_system_health()

                # Get recent metrics
                metrics_collector = EFRISMetricsCollector()
                context['metrics'] = metrics_collector.get_system_metrics(company, 24)
                context['invoice_metrics'] = metrics_collector.get_invoice_fiscalization_metrics(company, 7)

                # Get recent API logs
                context['recent_logs'] = EFRISAPILog.objects.filter(
                    company=company
                ).order_by('-created_at')[:10]

                # Get recent fiscalization audits
                context['recent_audits'] = FiscalizationAudit.objects.filter(
                    invoice__sale__store__company=company  # Updated path through Sale
                ).order_by('-created_at')[:10]

            else:
                # Setup wizard for new configurations
                wizard = EFRISConfigurationWizard(company)
                context['setup_checklist'] = wizard.generate_setup_checklist()

        except Exception as e:
            logger.error(f"Dashboard error: {e}")
            messages.error(self.request, f"Dashboard error: {e}")
            context['error'] = str(e)

        return context

class EFRISConfigurationView(TemplateView):
    """EFRIS configuration management view"""
    template_name = 'efris/configuration.html'

    @method_decorator(login_required)
    @method_decorator(staff_member_required)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = self.request.user.company

        try:
            config = EFRISConfiguration.objects.filter(company=company).first()
            context['config'] = config

            # Validation results
            is_valid, errors = validate_efris_configuration(company)
            context['is_valid'] = is_valid
            context['validation_errors'] = errors

            # Setup wizard
            wizard = EFRISConfigurationWizard(company)
            context['setup_status'] = wizard.validate_setup_requirements()

        except Exception as e:
            logger.error(f"Configuration view error: {e}")
            context['error'] = str(e)

        return context


class EFRISTestConnectionView(View):
    """Test EFRIS API connection"""

    @method_decorator(login_required)
    @method_decorator(staff_member_required)
    def post(self, request, *args, **kwargs):
        company = request.user.company

        try:
            with EnhancedEFRISAPIClient(company) as client:
                # Test basic connectivity
                response = client.get_server_time()

                if response.success:
                    server_time = response.data.get('serverTime', 'Unknown') if response.data else 'Unknown'
                    return JsonResponse({
                        'success': True,
                        'message': f'Connection successful. Server time: {server_time}',
                        'duration_ms': response.duration_ms,
                        'data': response.data
                    })
                else:
                    return JsonResponse({
                        'success': False,
                        'message': response.error_message or 'Connection failed',
                        'error_code': response.error_code
                    })

        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return JsonResponse({
                'success': False,
                'message': f'Connection test failed: {e}',
                'error_code': type(e).__name__
            })


class EFRISAuthenticationView(View):
    """Handle EFRIS authentication flow"""

    @method_decorator(login_required)
    @method_decorator(staff_member_required)
    def post(self, request, *args, **kwargs):
        company = request.user.company
        action = request.POST.get('action', 'authenticate')

        try:
            with EnhancedEFRISAPIClient(company) as client:
                if action == 'authenticate':
                    response = client.authenticate()
                elif action == 'get_server_time':
                    response = client.get_server_time()
                elif action == 'client_init':
                    otp = request.POST.get('otp')
                    response = client.client_initialization(otp)
                elif action == 'login':
                    response = client.login()
                elif action == 'get_symmetric_key':
                    response = client.get_symmetric_key()
                else:
                    return JsonResponse({
                        'success': False,
                        'message': f'Unknown action: {action}'
                    })

                if response.success:
                    messages.success(request, f'{action.title()} completed successfully')
                    return JsonResponse({
                        'success': True,
                        'message': f'{action.title()} successful',
                        'data': response.data,
                        'duration_ms': response.duration_ms
                    })
                else:
                    messages.error(request, f'{action.title()} failed: {response.error_message}')
                    return JsonResponse({
                        'success': False,
                        'message': response.error_message or f'{action.title()} failed',
                        'error_code': response.error_code
                    })

        except Exception as e:
            logger.error(f"Authentication {action} failed: {e}")
            messages.error(request, f'{action.title()} error: {e}')
            return JsonResponse({
                'success': False,
                'message': str(e),
                'error_code': type(e).__name__
            })


class EFRISInvoiceOperationsView(TemplateView):
    """Manual invoice operations"""
    template_name = 'efris/invoice_operations.html'

    @method_decorator(login_required)
    @method_decorator(staff_member_required)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = self.request.user.company

        try:
            # Get pending invoices from your actual invoice model
            from invoices.models import Invoice

            pending_invoices = Invoice.objects.filter(
                sale__store__company=company,  # Navigate through Sale to Store to Company
                fiscalization_status='pending'  # Use your actual field name
            ).select_related(
                'sale', 'sale__store', 'sale__customer'
            ).order_by('-created_at')[:20]

            context['pending_invoices'] = pending_invoices

            # Get recent fiscalization audits
            context['recent_audits'] = FiscalizationAudit.objects.filter(
                invoice__sale__store__company=company
            ).select_related('invoice', 'user').order_by('-created_at')[:20]

        except Exception as e:
            logger.error(f"Invoice operations view error: {e}")
            context['error'] = str(e)

        return context


class EFRISFiscalizeInvoiceView(View):
    """Fiscalize individual invoice"""

    @method_decorator(login_required)
    @method_decorator(staff_member_required)
    def post(self, request, *args, **kwargs):
        company = request.user.company
        invoice_id = request.POST.get('invoice_id')

        if not invoice_id:
            return JsonResponse({
                'success': False,
                'message': 'Invoice ID is required'
            })

        try:
            from invoices.models import Invoice

            # Get invoice with proper company filtering
            invoice = get_object_or_404(
                Invoice.objects.select_related('sale', 'sale__store'),
                pk=invoice_id,
                sale__store__company=company
            )

            # Fiscalize invoice
            invoice_service = EFRISInvoiceService(company)
            success, message = invoice_service.fiscalize_invoice(invoice, request.user)

            if success:
                messages.success(request, f'Invoice fiscalized: {message}')
                return JsonResponse({
                    'success': True,
                    'message': message,
                    'fiscal_number': invoice.fiscal_document_number or '',
                    'verification_code': invoice.verification_code or ''
                })
            else:
                messages.error(request, f'Fiscalization failed: {message}')
                return JsonResponse({
                    'success': False,
                    'message': message
                })

        except Exception as e:
            logger.error(f"Invoice fiscalization failed: {e}")
            messages.error(request, f'Fiscalization error: {e}')
            return JsonResponse({
                'success': False,
                'message': str(e),
                'error_code': type(e).__name__
            })


class EFRISBulkFiscalizeView(View):
    """Bulk fiscalize invoices"""

    @method_decorator(login_required)
    @method_decorator(staff_member_required)
    def post(self, request, *args, **kwargs):
        company = request.user.company
        invoice_ids = request.POST.getlist('invoice_ids[]')

        if not invoice_ids:
            return JsonResponse({
                'success': False,
                'message': 'No invoices selected'
            })

        try:
            from invoices.models import Invoice

            # Get invoices with proper company filtering
            invoices = Invoice.objects.filter(
                pk__in=invoice_ids,
                sale__store__company=company
            ).select_related('sale', 'sale__store')

            if not invoices:
                return JsonResponse({
                    'success': False,
                    'message': 'No valid invoices found'
                })

            # Bulk fiscalize
            invoice_service = EFRISInvoiceService(company)
            results = invoice_service.bulk_fiscalize_invoices(list(invoices), request.user)

            if results['success']:
                messages.success(request, results['message'])
            else:
                messages.warning(request, results['message'])

            return JsonResponse(results)

        except Exception as e:
            logger.error(f"Bulk fiscalization failed: {e}")
            messages.error(request, f'Bulk fiscalization error: {e}')
            return JsonResponse({
                'success': False,
                'message': str(e),
                'error_code': type(e).__name__
            })

class EFRISProductOperationsView(TemplateView):
    """Manual product operations"""
    template_name = 'efris/product_operations.html'

    @method_decorator(login_required)
    @method_decorator(staff_member_required)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = self.request.user.company

        try:
            from inventory.models import Product

            # Get products not uploaded to EFRIS for this company's stores
            pending_products = Product.objects.filter(
                store_inventory__store__company=company,  # Through Stock model to Store to Company
                efris_is_uploaded=False,
                is_active=True
            ).distinct().order_by('-created_at')[:50]

            context['pending_products'] = pending_products

        except Exception as e:
            logger.error(f"Product operations view error: {e}")
            context['error'] = str(e)

        return context


class EFRISUploadProductsView(View):
    """Upload products to EFRIS"""

    @method_decorator(login_required)
    @method_decorator(staff_member_required)
    def post(self, request, *args, **kwargs):
        company = request.user.company
        product_ids = request.POST.getlist('product_ids[]')

        if not product_ids:
            return JsonResponse({
                'success': False,
                'message': 'No products selected'
            })

        try:
            from inventory.models import Product

            # Get products with company validation through stores
            products = Product.objects.filter(
                pk__in=product_ids,
                store_inventory__store__company=company
            ).distinct()

            if not products:
                return JsonResponse({
                    'success': False,
                    'message': 'No valid products found'
                })

            # Upload products
            product_service = EFRISProductService(company)
            success, message = product_service.upload_products(list(products), request.user)

            if success:
                messages.success(request, message)
                return JsonResponse({
                    'success': True,
                    'message': message
                })
            else:
                messages.error(request, f'Product upload failed: {message}')
                return JsonResponse({
                    'success': False,
                    'message': message
                })

        except Exception as e:
            logger.error(f"Product upload failed: {e}")
            messages.error(request, f'Product upload error: {e}')
            return JsonResponse({
                'success': False,
                'message': str(e),
                'error_code': type(e).__name__
            })


class EFRISGoodsInquiryView(View):
    """Query EFRIS goods/services"""

    @method_decorator(login_required)
    @method_decorator(staff_member_required)
    def get(self, request, *args, **kwargs):
        company = request.user.company

        # Get query parameters
        goods_name = request.GET.get('goods_name', '')
        goods_code = request.GET.get('goods_code', '')
        category_id = request.GET.get('category_id', '')
        page = int(request.GET.get('page', 1))
        page_size = int(request.GET.get('page_size', 20))

        try:
            with EnhancedEFRISAPIClient(company) as client:
                filters = {}
                if goods_name:
                    filters['goodsName'] = goods_name
                if goods_code:
                    filters['goodsCode'] = goods_code
                if category_id:
                    filters['categoryId'] = category_id

                response = client.goods_inquiry(filters, page, page_size)

                if response.success:
                    return JsonResponse({
                        'success': True,
                        'data': response.data,
                        'page': page,
                        'page_size': page_size
                    })
                else:
                    return JsonResponse({
                        'success': False,
                        'message': response.error_message or 'Goods inquiry failed'
                    })

        except Exception as e:
            logger.error(f"Goods inquiry failed: {e}")
            return JsonResponse({
                'success': False,
                'message': str(e),
                'error_code': type(e).__name__
            })

class EFRISCustomerOperationsView(TemplateView):
    """Customer operations"""
    template_name = 'efris/customer_operations.html'

    @method_decorator(login_required)
    @method_decorator(staff_member_required)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = self.request.user.company

        try:
            from customers.models import Customer

            # Get customers for this company's stores
            customers = Customer.objects.filter(
                store__company=company
            ).distinct().order_by('-created_at')[:50]

            context['customers'] = customers

        except Exception as e:
            logger.error(f"Customer operations view error: {e}")
            context['error'] = str(e)

        return context


class EFRISQueryTaxpayerView(View):
    """Query taxpayer by TIN"""

    @method_decorator(login_required)
    @method_decorator(staff_member_required)
    def post(self, request, *args, **kwargs):
        company = request.user.company
        tin = request.POST.get('tin', '').strip()
        nin_brn = request.POST.get('nin_brn', '').strip()

        if not tin:
            return JsonResponse({
                'success': False,
                'message': 'TIN is required'
            })

        try:
            customer_service = EFRISCustomerService(company)
            success, result = customer_service.query_taxpayer(tin, nin_brn or None)

            if success:
                return JsonResponse({
                    'success': True,
                    'data': result,
                    'message': 'Taxpayer found'
                })
            else:
                return JsonResponse({
                    'success': False,
                    'message': result  # Error message
                })

        except Exception as e:
            logger.error(f"Taxpayer query failed: {e}")
            return JsonResponse({
                'success': False,
                'message': str(e),
                'error_code': type(e).__name__
            })


class EFRISSystemDictionaryView(View):
    """Get system dictionary from EFRIS"""

    @method_decorator(login_required)
    @method_decorator(staff_member_required)
    def post(self, request, *args, **kwargs):
        company = request.user.company

        try:
            with EnhancedEFRISAPIClient(company) as client:
                response = client.get_system_dictionary()

                if response.success:
                    messages.success(request, 'System dictionary updated successfully')
                    return JsonResponse({
                        'success': True,
                        'message': 'System dictionary updated',
                        'data': response.data
                    })
                else:
                    messages.error(request, f'Dictionary update failed: {response.error_message}')
                    return JsonResponse({
                        'success': False,
                        'message': response.error_message or 'Dictionary update failed'
                    })

        except Exception as e:
            logger.error(f"System dictionary update failed: {e}")
            messages.error(request, f'Dictionary update error: {e}')
            return JsonResponse({
                'success': False,
                'message': str(e),
                'error_code': type(e).__name__
            })


class EFRISLogsView(TemplateView):
    """View EFRIS API logs"""
    template_name = 'efris/logs.html'

    @method_decorator(login_required)
    @method_decorator(staff_member_required)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = self.request.user.company

        # Get query parameters
        interface_code = self.request.GET.get('interface_code', '')
        status = self.request.GET.get('status', '')
        date_from = self.request.GET.get('date_from', '')
        date_to = self.request.GET.get('date_to', '')
        page = int(self.request.GET.get('page', 1))

        # Build query - updated field name
        logs = EFRISAPILog.objects.filter(company=company).order_by('-request_time')

        if interface_code:
            logs = logs.filter(interface_code=interface_code)
        if status:
            logs = logs.filter(status=status)
        if date_from:
            try:
                from_date = datetime.strptime(date_from, '%Y-%m-%d').date()
                logs = logs.filter(request_time__date__gte=from_date)
            except ValueError:
                pass
        if date_to:
            try:
                to_date = datetime.strptime(date_to, '%Y-%m-%d').date()
                logs = logs.filter(request_time__date__lte=to_date)
            except ValueError:
                pass

        # Pagination
        paginator = Paginator(logs, 50)
        page_obj = paginator.get_page(page)

        context.update({
            'logs': page_obj,
            'interface_codes': EFRISAPILog.objects.filter(
                company=company
            ).values_list('interface_code', flat=True).distinct(),
            'statuses': [choice[0] for choice in EFRISAPILog.STATUS_CHOICES],
            'current_filters': {
                'interface_code': interface_code,
                'status': status,
                'date_from': date_from,
                'date_to': date_to
            }
        })

        return context


class EFRISAuditTrailView(TemplateView):
    """View fiscalization audit trail"""
    template_name = 'efris/audit_trail.html'

    @method_decorator(login_required)
    @method_decorator(staff_member_required)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = self.request.user.company

        # Get query parameters
        action = self.request.GET.get('action', '')
        success = self.request.GET.get('success', '')
        date_from = self.request.GET.get('date_from', '')
        date_to = self.request.GET.get('date_to', '')
        page = int(self.request.GET.get('page', 1))

        # Build query - use the correct field path
        audits = FiscalizationAudit.objects.filter(
            company=company  # Direct company field
        ).select_related('invoice', 'user').order_by('-created_at')

        if action:
            audits = audits.filter(action=action)
        if success:
            audits = audits.filter(status='success' if success.lower() == 'true' else 'failed')
        if date_from:
            try:
                from_date = datetime.strptime(date_from, '%Y-%m-%d').date()
                audits = audits.filter(created_at__date__gte=from_date)
            except ValueError:
                pass
        if date_to:
            try:
                to_date = datetime.strptime(date_to, '%Y-%m-%d').date()
                audits = audits.filter(created_at__date__lte=to_date)
            except ValueError:
                pass

        # Pagination
        paginator = Paginator(audits, 50)
        page_obj = paginator.get_page(page)

        context.update({
            'audits': page_obj,
            'actions': FiscalizationAudit.objects.filter(
                company=company
            ).values_list('action', flat=True).distinct(),
            'current_filters': {
                'action': action,
                'success': success,
                'date_from': date_from,
                'date_to': date_to
            }
        })

        return context


class EFRISMetricsView(TemplateView):
    """View EFRIS metrics and analytics"""
    template_name = 'efris/metrics.html'

    @method_decorator(login_required)
    @method_decorator(staff_member_required)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = self.request.user.company

        try:
            metrics_collector = EFRISMetricsCollector()

            # Get time range from query params
            hours = int(self.request.GET.get('hours', 24))
            days = int(self.request.GET.get('days', 7))

            # System metrics
            context['system_metrics'] = metrics_collector.get_system_metrics(company, hours)

            # Invoice fiscalization metrics
            context['invoice_metrics'] = metrics_collector.get_invoice_fiscalization_metrics(company, days)

            # Health status
            health_checker = EFRISHealthChecker(company)
            context['health_status'] = health_checker.check_system_health()

            # Summary statistics
            context['summary_stats'] = self._get_summary_statistics(company)

        except Exception as e:
            logger.error(f"Metrics view error: {e}")
            context['error'] = str(e)

        return context

    def _get_summary_statistics(self, company) -> Dict[str, Any]:
        """Get summary statistics"""
        try:
            total_logs = EFRISAPILog.objects.filter(company=company).count()
            successful_logs = EFRISAPILog.objects.filter(
                company=company,
                status='success'
            ).count()

            total_audits = FiscalizationAudit.objects.filter(
                company=company
            ).count()
            successful_audits = FiscalizationAudit.objects.filter(
                company=company,
                status='success'
            ).count()

            return {
                'total_api_calls': total_logs,
                'successful_api_calls': successful_logs,
                'api_success_rate': (successful_logs / total_logs * 100) if total_logs > 0 else 0,
                'total_fiscalizations': total_audits,
                'successful_fiscalizations': successful_audits,
                'fiscalization_success_rate': (successful_audits / total_audits * 100) if total_audits > 0 else 0
            }
        except Exception as e:
            logger.error(f"Summary statistics error: {e}")
            return {}


class EFRISHealthCheckView(View):
    """Health check endpoint"""

    @method_decorator(login_required)
    @method_decorator(staff_member_required)
    def get(self, request, *args, **kwargs):
        company = request.user.company

        try:
            health_checker = EFRISHealthChecker(company)
            health_status = health_checker.check_system_health()

            return JsonResponse({
                'success': True,
                'health_status': health_status
            })

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return JsonResponse({
                'success': False,
                'message': str(e),
                'error_code': type(e).__name__
            })


class EFRISSetupWizardView(TemplateView):
    """EFRIS setup wizard"""
    template_name = 'efris/setup_wizard.html'

    @method_decorator(login_required)
    @method_decorator(staff_member_required)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Check if user has a company
        if not hasattr(self.request.user, 'company') or not self.request.user.company:
            context['needs_company_setup'] = True
            context['checklist'] = {}
            context['requirements'] = {}  # Empty dict for template
            return context

        company = self.request.user.company

        try:
            wizard = EFRISConfigurationWizard(company)

            # Get the setup data
            setup_data = wizard.generate_setup_checklist()
            validation_result = wizard.validate_setup_requirements()

            # Format requirements for the template
            context['requirements'] = self._format_requirements(validation_result)
            context['checklist'] = setup_data
            context['setup_status'] = validation_result['ready_for_setup']
            context['next_steps'] = validation_result['next_steps']

        except Exception as e:
            logger.error(f"Setup wizard error: {e}")
            context['error'] = str(e)
            context['checklist'] = {}
            context['requirements'] = {}

        return context

    def _format_requirements(self, validation_result):
        """Format requirements data for template consumption"""
        requirements = {}

        for category, data in validation_result['requirements'].items():
            requirements[category] = []

            if category == 'company_info':
                requirements[category].append({
                    'name': 'Company Information',
                    'status': data['valid'],
                    'message': f"Missing: {len(data.get('missing_fields', []))}, Invalid: {len(data.get('invalid_fields', []))}"
                })
            elif category == 'certificates':
                requirements[category].append({
                    'name': 'Digital Certificates',
                    'status': data['valid'],
                    'message': f"Has Certificate: {data.get('has_certificate', False)}"
                })
            elif category == 'network':
                requirements[category].append({
                    'name': 'Network Access',
                    'status': data['valid'],
                    'message': f"Status: {data.get('status_code', 'N/A')}"
                })
            elif category == 'permissions':
                requirements[category].append({
                    'name': 'System Permissions',
                    'status': data['valid'],
                    'message': "All permissions verified"
                })

        return requirements


class EFRISCompleteSetupView(View):
    """Complete EFRIS setup"""

    @method_decorator(login_required)
    @method_decorator(staff_member_required)
    def post(self, request, *args, **kwargs):
        company = request.user.company

        try:
            setup_result = setup_efris_for_company(company)

            if setup_result['success']:
                messages.success(request, setup_result['message'])
                return JsonResponse({
                    'success': True,
                    'message': setup_result['message'],
                    'steps_completed': setup_result['steps_completed'],
                    'health_status': setup_result.get('health_status')
                })
            else:
                error_msg = '; '.join(setup_result['errors'])
                messages.error(request, f'Setup failed: {error_msg}')
                return JsonResponse({
                    'success': False,
                    'message': error_msg,
                    'errors': setup_result['errors'],
                    'warnings': setup_result['warnings']
                })

        except Exception as e:
            logger.error(f"Complete setup failed: {e}")
            messages.error(request, f'Setup error: {e}')
            return JsonResponse({
                'success': False,
                'message': str(e),
                'error_code': type(e).__name__
            })


class EFRISCreditNoteView(View):
    """Apply credit note"""

    @method_decorator(login_required)
    @method_decorator(staff_member_required)
    def post(self, request, *args, **kwargs):
        company = request.user.company

        # Get form data
        original_invoice_id = request.POST.get('original_invoice_id')
        original_invoice_no = request.POST.get('original_invoice_no')
        reason = request.POST.get('reason')
        credit_amount = request.POST.get('credit_amount')
        tax_amount = request.POST.get('tax_amount', '0')

        if not all([original_invoice_id, original_invoice_no, reason, credit_amount]):
            return JsonResponse({
                'success': False,
                'message': 'All fields are required'
            })

        try:
            credit_note_data = {
                'oriInvoiceId': original_invoice_id,
                'oriInvoiceNo': original_invoice_no,
                'reason': reason,
                'creditAmount': credit_amount,
                'taxAmount': tax_amount
            }

            invoice_service = EFRISInvoiceService(company)
            success, message = invoice_service.apply_credit_note(credit_note_data, request.user)

            if success:
                messages.success(request, f'Credit note applied: {message}')
                return JsonResponse({
                    'success': True,
                    'message': message
                })
            else:
                messages.error(request, f'Credit note failed: {message}')
                return JsonResponse({
                    'success': False,
                    'message': message
                })

        except Exception as e:
            logger.error(f"Credit note application failed: {e}")
            messages.error(request, f'Credit note error: {e}')
            return JsonResponse({
                'success': False,
                'message': str(e),
                'error_code': type(e).__name__
            })


class EFRISInvoiceQueryView(View):
    """Query invoices from EFRIS"""

    @method_decorator(login_required)
    @method_decorator(staff_member_required)
    def get(self, request, *args, **kwargs):
        company = request.user.company

        # Get query parameters
        filters = {}
        for param in ['invoiceNo', 'startDate', 'endDate', 'buyerTin', 'invoiceType', 'status']:
            value = request.GET.get(param, '').strip()
            if value:
                filters[param] = value

        page = int(request.GET.get('page', 1))
        page_size = min(int(request.GET.get('page_size', 10)), 100)

        try:
            invoice_service = EFRISInvoiceService(company)
            success, result = invoice_service.query_invoices(filters, page, page_size)

            if success:
                return JsonResponse({
                    'success': True,
                    'data': result,
                    'page': page,
                    'page_size': page_size
                })
            else:
                return JsonResponse({
                    'success': False,
                    'message': result
                })

        except Exception as e:
            logger.error(f"Invoice query failed: {e}")
            return JsonResponse({
                'success': False,
                'message': str(e),
                'error_code': type(e).__name__
            })


class EFRISExportLogsView(View):
    """Export EFRIS logs to CSV"""

    @method_decorator(login_required)
    @method_decorator(staff_member_required)
    def get(self, request, *args, **kwargs):
        company = request.user.company

        try:
            import csv
            from django.http import HttpResponse

            # Create response
            response = HttpResponse(content_type='text/csv')
            response[
                'Content-Disposition'] = f'attachment; filename="efris_logs_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'

            # Get logs
            logs = EFRISAPILog.objects.filter(company=company).order_by('-request_time')[:1000]

            # Write CSV
            writer = csv.writer(response)
            writer.writerow([
                'Timestamp', 'Interface Code', 'Status', 'Duration (ms)',
                'Error Message', 'Request Size', 'Response Size'
            ])

            for log in logs:
                writer.writerow([
                    log.request_time.strftime('%Y-%m-%d %H:%M:%S'),
                    log.interface_code,
                    log.status,
                    log.duration_ms or 0,
                    log.return_message or '',  # Updated field name
                    len(str(log.request_data)) if log.request_data else 0,
                    len(str(log.response_data)) if log.response_data else 0
                ])

            return response

        except Exception as e:
            logger.error(f"Export logs failed: {e}")
            messages.error(request, f'Export failed: {e}')
            return redirect('efris:logs')


class EFRISSystemDictionariesView(TemplateView):
    """View system dictionaries"""
    template_name = 'efris/system_dictionaries.html'

    @method_decorator(login_required)
    @method_decorator(staff_member_required)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = self.request.user.company

        try:
            # Get all dictionaries for this company
            dictionaries = EFRISSystemDictionary.objects.filter(
                company=company
            ).order_by('dictionary_type')

            # Group by type
            dictionary_groups = {}
            for dictionary in dictionaries:
                dict_type = dictionary.dictionary_type
                if dict_type not in dictionary_groups:
                    dictionary_groups[dict_type] = {
                        'type': dict_type,
                        'last_updated': dictionary.updated_at,  # Updated field name
                        'data': dictionary.data,
                        'count': len(dictionary.data) if isinstance(dictionary.data, list) else 1
                    }

            context['dictionaries'] = dictionary_groups

        except Exception as e:
            logger.error(f"System dictionaries view error: {e}")
            context['error'] = str(e)

        return context


# API Views for AJAX calls
@csrf_exempt
@require_http_methods(["POST"])
@login_required
@staff_member_required
def efris_api_test(request):
    """Generic API test endpoint"""
    company = request.user.company

    try:
        data = json.loads(request.body)
        interface_code = data.get('interface_code')
        test_data = data.get('test_data', {})

        if not interface_code:
            return JsonResponse({
                'success': False,
                'message': 'Interface code is required'
            })

        with EnhancedEFRISAPIClient(company) as client:
            response = client._make_request(interface_code, test_data, user=request.user)

            return JsonResponse({
                'success': response.success,
                'message': response.error_message or 'Request completed',
                'data': response.data,
                'duration_ms': response.duration_ms,
                'error_code': response.error_code
            })

    except Exception as e:
        logger.error(f"API test failed: {e}")
        return JsonResponse({
            'success': False,
            'message': str(e),
            'error_code': type(e).__name__
        })


@csrf_exempt
@require_http_methods(["POST"])
@login_required
@staff_member_required
def efris_clear_cache(request):
    """Clear EFRIS cache"""
    try:
        from django.core.cache import cache
        company = request.user.company

        # Clear company-specific cache keys
        cache_patterns = [
            f'efris_config_{company.pk}',
            f'efris_http_metrics_{getattr(company, "efris_device_mac", "unknown")}',
            f'efris_health_{company.pk}',
        ]

        cleared_count = 0
        for pattern in cache_patterns:
            if cache.get(pattern):
                cache.delete(pattern)
                cleared_count += 1

        messages.success(request, f'Cleared {cleared_count} cache entries')
        return JsonResponse({
            'success': True,
            'message': f'Cleared {cleared_count} cache entries'
        })

    except Exception as e:
        logger.error(f"Clear cache failed: {e}")
        return JsonResponse({
            'success': False,
            'message': str(e)
        })

@csrf_exempt
@require_http_methods(["POST"])
@login_required
@staff_member_required
def efris_api_test(request):
    """Generic API test endpoint"""
    company = request.user.company

    try:
        data = json.loads(request.body)
        interface_code = data.get('interface_code')
        test_data = data.get('test_data', {})

        if not interface_code:
            return JsonResponse({
                'success': False,
                'message': 'Interface code is required'
            })

        with EnhancedEFRISAPIClient(company) as client:
            response = client._make_request(interface_code, test_data, user=request.user)

            return JsonResponse({
                'success': response.success,
                'message': response.error_message or 'Request completed',
                'data': response.data,
                'duration_ms': response.duration_ms,
                'error_code': response.error_code
            })

    except Exception as e:
        logger.error(f"API test failed: {e}")
        return JsonResponse({
            'success': False,
            'message': str(e),
            'error_code': type(e).__name__
        })


@csrf_exempt
@require_http_methods(["POST"])
@login_required
@staff_member_required
def efris_clear_cache(request):
    """Clear EFRIS cache"""
    try:
        from django.core.cache import cache
        company = request.user.company

        # Clear company-specific cache keys
        cache_patterns = [
            f'efris_config_{company.pk}',
            f'efris_http_metrics_{getattr(company, "efris_device_number", "unknown")}',
            f'efris_health_{company.pk}',
        ]

        cleared_count = 0
        for pattern in cache_patterns:
            if cache.get(pattern):
                cache.delete(pattern)
                cleared_count += 1

        messages.success(request, f'Cleared {cleared_count} cache entries')
        return JsonResponse({
            'success': True,
            'message': f'Cleared {cleared_count} cache entries'
        })

    except Exception as e:
        logger.error(f"Clear cache failed: {e}")
        return JsonResponse({
            'success': False,
            'message': str(e)
        })


@require_http_methods(["GET"])
@login_required
@staff_member_required
def efris_download_qr_code(request, invoice_id):
    """Download QR code for invoice"""
    try:
        company = request.user.company

        # Get invoice using your actual Invoice model
        from invoices.models import Invoice

        invoice = get_object_or_404(
            Invoice.objects.select_related('sale', 'sale__store'),
            pk=invoice_id,
            sale__store__company=company
        )

        qr_code = invoice.qr_code or ''
        if not qr_code:
            messages.error(request, 'QR code not available for this invoice')
            return redirect('efris:invoice_operations')

        # Generate QR code image
        import qrcode
        from io import BytesIO

        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(qr_code)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")

        # Return as response
        response = HttpResponse(content_type="image/png")
        response['Content-Disposition'] = f'attachment; filename="invoice_{invoice_id}_qr.png"'

        buffer = BytesIO()
        img.save(buffer, format='PNG')
        response.write(buffer.getvalue())
        buffer.close()

        return response

    except Exception as e:
        logger.error(f"QR code download failed: {e}")
        messages.error(request, f'QR code download failed: {e}')
        return redirect('efris:invoice_operations')



class EFRISDebugView(TemplateView):
    """Debug information view - only for development"""
    template_name = 'efris/debug.html'

    @method_decorator(login_required)
    @method_decorator(staff_member_required)
    def dispatch(self, *args, **kwargs):
        # Only allow in debug mode
        from django.conf import settings
        if not settings.DEBUG:
            raise Http404("Debug view not available in production")
        return super().dispatch(*args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = self.request.user.company

        try:
            # Configuration details
            config = EFRISConfiguration.objects.filter(company=company).first()
            context['config'] = config

            # Company EFRIS fields using your actual field names
            efris_fields = {}
            efris_field_names = [
                'tin', 'brn', 'nin', 'name', 'trading_name',
                'email', 'phone', 'physical_address',
                'efris_enabled', 'efris_is_production', 'efris_integration_mode',
                 'efris_device_number'
            ]

            for field in efris_field_names:
                efris_fields[field] = getattr(company, field, None)
            context['company_efris_fields'] = efris_fields

            # Recent API logs with full data
            context['debug_logs'] = EFRISAPILog.objects.filter(
                company=company
            ).order_by('-request_time')[:5]

            # Environment info
            from django.conf import settings
            import sys
            context['debug_info'] = {
                'debug_mode': settings.DEBUG,
                'efris_api_url': getattr(settings, 'EFRIS_API_URL', 'Not configured'),
                'python_version': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
                'django_version': getattr(settings, 'DJANGO_VERSION', 'Unknown')
            }

        except Exception as e:
            context['error'] = str(e)

        return context


class EFRISSalesReportView(TemplateView):
    """View sales report with EFRIS fiscalization status"""
    template_name = 'efris/sales_report.html'

    @method_decorator(login_required)
    @method_decorator(staff_member_required)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = self.request.user.company

        try:
            from sales.models import Sale
            from django.db.models import Sum, Count, Q

            # Get query parameters
            date_from = self.request.GET.get('date_from', '')
            date_to = self.request.GET.get('date_to', '')
            store_id = self.request.GET.get('store_id', '')

            # Base queryset
            sales = Sale.objects.filter(
                store__company=company,
                status__in=['COMPLETED', 'PAID']
            ).select_related('store', 'customer', 'created_by')

            # Apply filters
            if date_from:
                try:
                    from_date = datetime.strptime(date_from, '%Y-%m-%d').date()
                    sales = sales.filter(created_at__date__gte=from_date)
                except ValueError:
                    pass

            if date_to:
                try:
                    to_date = datetime.strptime(date_to, '%Y-%m-%d').date()
                    sales = sales.filter(created_at__date__lte=to_date)
                except ValueError:
                    pass

            if store_id:
                sales = sales.filter(store_id=store_id)

            # Pagination
            paginator = Paginator(sales.order_by('-created_at'), 50)
            page = int(self.request.GET.get('page', 1))
            page_obj = paginator.get_page(page)

            # Summary statistics
            summary = sales.aggregate(
                total_sales=Count('id'),
                total_amount=Sum('total_amount'),
                fiscalized_count=Count('id', filter=Q(is_fiscalized=True)),
                non_fiscalized_count=Count('id', filter=Q(is_fiscalized=False))
            )

            # Get stores for filter dropdown
            from stores.models import Store
            stores = Store.objects.filter(company=company, is_active=True)

            context.update({
                'sales': page_obj,
                'summary': summary,
                'stores': stores,
                'current_filters': {
                    'date_from': date_from,
                    'date_to': date_to,
                    'store_id': store_id
                }
            })

        except Exception as e:
            logger.error(f"Sales report view error: {e}")
            context['error'] = str(e)

        return context