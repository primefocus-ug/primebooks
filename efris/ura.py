import base64
from django.core.exceptions import ValidationError
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator
from django.db.models import Q, Count, Sum
from django.utils import timezone
import json
from django.views.decorators.csrf import csrf_exempt
from datetime import datetime, date, timedelta
from django.views.decorators.http import require_http_methods
from django_tenants.utils import schema_context
from company.models import Company, EFRISCommodityCategory
from inventory.models import Product, Stock, StockMovement
from invoices.models import Invoice

from django.template.loader import render_to_string
from django.http import JsonResponse
from .models import (
    EFRISConfiguration, EFRISAPILog, FiscalizationAudit,
)
from .services import (
    EnhancedEFRISAPIClient,
    EFRISProductService,
    EFRISInvoiceService,
    EFRISHealthChecker,
    EFRISMetricsCollector,
    EFRISConfigurationWizard,
    SystemDictionaryManager,
    TaxpayerQueryService,
    GoodsInquiryService,
    bulk_register_products_with_efris,
    sync_commodity_categories,
    test_efris_connection,
    diagnose_efris_issue
)



@login_required
def system_dictionary(request):
    """View and manage EFRIS system dictionary"""
    company = request.tenant

    manager = SystemDictionaryManager(company)

    # Get current dictionary statistics
    stats = manager.get_dictionary_statistics()

    # Handle actions
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'update':
            force_update = request.POST.get('force_update') == 'on'
            result = manager.update_system_dictionary(force_update=force_update)

            if result.get('success'):
                messages.success(
                    request,
                    f"System dictionary updated successfully (Version: {result.get('version', 'unknown')})"
                )
            else:
                messages.error(
                    request,
                    f"Failed to update dictionary: {result.get('error')}"
                )

            return redirect('efris:system_dictionary')

    # Handle search
    search_term = request.GET.get('search', '')
    search_results = None

    if search_term:
        search_results = manager.search_dictionary(search_term)

    # Get dictionary categories
    payment_methods = manager.get_payment_methods()
    currencies = manager.get_currencies()
    rate_units = manager.get_rate_units()
    sectors = manager.get_sectors()
    country_codes = manager.get_country_codes()
    delivery_terms = manager.get_delivery_terms()
    export_rate_units = manager.get_export_rate_units()
    credit_note_limits = manager.get_credit_note_limits()

    # Get formats
    date_format = manager.get_date_format()
    time_format = manager.get_time_format()

    context = {
        'stats': stats,
        'search_term': search_term,
        'search_results': search_results,
        'payment_methods': payment_methods,
        'currencies': currencies,
        'rate_units': rate_units,
        'sectors': sectors,
        'country_codes': country_codes,
        'delivery_terms': delivery_terms,
        'export_rate_units': export_rate_units,
        'credit_note_limits': credit_note_limits,
        'date_format': date_format,
        'time_format': time_format,
    }

    return render(request, 'efris/system_dictionary.html', context)


@login_required
def system_dictionary_category(request, category):
    """View specific dictionary category details"""
    company = request.tenant

    manager = SystemDictionaryManager(company)
    category_data = manager.get_dictionary_value(category)

    if not category_data:
        messages.warning(request, f'Category "{category}" not found in dictionary')
        return redirect('efris:system_dictionary')

    context = {
        'category': category,
        'category_data': category_data,
        'is_list': isinstance(category_data, list),
        'is_dict': isinstance(category_data, dict),
    }

    return render(request, 'efris/system_dictionary_category.html', context)


@login_required
@require_http_methods(["POST"])
def system_dictionary_update(request):
    """AJAX endpoint to update system dictionary"""
    company = request.tenant

    try:
        force_update = request.POST.get('force_update') == 'true'

        manager = SystemDictionaryManager(company)
        result = manager.update_system_dictionary(force_update=force_update)

        return JsonResponse(result)

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
def system_dictionary_export(request):
    """Export system dictionary as JSON"""
    company = request.tenant

    manager = SystemDictionaryManager(company)
    dictionary = manager._get_cached_dictionary()

    if not dictionary:
        messages.error(request, 'No dictionary data to export')
        return redirect('efris:system_dictionary')

    # Create JSON response
    response = HttpResponse(
        json.dumps(dictionary, indent=2),
        content_type='application/json'
    )
    response[
        'Content-Disposition'] = f'attachment; filename="efris_dictionary_{company.tin}_{timezone.now().strftime("%Y%m%d")}.json"'

    return response

@login_required
def efris_dashboard(request):
    """EFRIS main dashboard"""
    company = request.tenant

    # Get health status
    health_checker = EFRISHealthChecker(company)
    health_status = health_checker.check_system_health()

    # Get recent metrics
    metrics = EFRISMetricsCollector.get_system_metrics(company, time_range_hours=24)
    invoice_metrics = EFRISMetricsCollector.get_invoice_fiscalization_metrics(company, days=7)

    # Get recent API logs
    recent_logs = EFRISAPILog.objects.filter(
        company=company
    ).order_by('-request_time')[:10]

    # Get configuration status
    try:
        config = company.efris_config
        config_exists = True
    except:
        config_exists = False
        config = None

    # Product statistics
    total_products = Product.objects.count()
    uploaded_products = Product.objects.filter(
        efris_is_uploaded=True
    ).count()

    # Invoice statistics
    total_invoices = Invoice.objects.count()
    fiscalized_invoices = Invoice.objects.filter(
        is_fiscalized=True
    ).count()

    context = {
        'health_status': health_status,
        'metrics': metrics,
        'invoice_metrics': invoice_metrics,
        'recent_logs': recent_logs,
        'config_exists': config_exists,
        'config': config,
        'total_products': total_products,
        'uploaded_products': uploaded_products,
        'total_invoices': total_invoices,
        'fiscalized_invoices': fiscalized_invoices,
    }

    return render(request, 'efris/dashboard.html', context)


@login_required
def efris_configuration(request):
    """EFRIS configuration management"""
    company = request.tenant

    try:
        config = company.efris_config
    except Exception:
        config = None

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'save_config':
            # Create config if it doesn't exist
            if not config:
                config = EFRISConfiguration.objects.create(company=company)

            # Save basic configuration
            config.device_number = request.POST.get('device_number')
            config.api_base_url = request.POST.get('api_base_url', '').strip()
            config.is_active = request.POST.get('is_active') == 'on'

            # Environment and mode
            config.environment = request.POST.get('environment', 'sandbox')
            config.mode = request.POST.get('mode', 'online')

            # Device information
            config.device_mac = request.POST.get('device_mac', 'FFFFFFFFFFFF')
            config.app_id = request.POST.get('app_id', 'AP04')
            config.version = request.POST.get('version', '1.1.20191201')

            # Connection settings
            try:
                config.timeout_seconds = int(request.POST.get('timeout_seconds', 30))
                config.max_retry_attempts = int(request.POST.get('max_retry_attempts', 3))
            except ValueError:
                pass

            # Sync settings
            config.auto_sync_enabled = request.POST.get('auto_sync_enabled') == 'on'
            config.auto_fiscalize = request.POST.get('auto_fiscalize') == 'on'
            try:
                config.sync_interval_minutes = int(request.POST.get('sync_interval_minutes', 60))
            except ValueError:
                pass

            # Digital keys and certificates - only update if provided
            if request.POST.get('private_key'):
                config.private_key = request.POST.get('private_key')
            if request.POST.get('public_certificate'):
                config.public_certificate = request.POST.get('public_certificate')
            if request.POST.get('key_password'):
                config.key_password = request.POST.get('key_password')

            # Validate and save
            try:
                config.clean()  # This will run the validation methods
                config.save()
                messages.success(request, 'Configuration saved successfully')
            except ValidationError as e:
                for field, error in e.message_dict.items():
                    if field == '__all__':
                        messages.error(request, f'Validation error: {error[0]}')
                    else:
                        messages.error(request, f'{field}: {error[0]}')
            except Exception as e:
                messages.error(request, f'Error saving configuration: {str(e)}')

            return redirect('efris:configuration')

        elif action == 'test_connection':
            result = test_efris_connection(company)
            if result['success']:
                messages.success(request, 'Connection test successful!')
                if config:
                    config.last_test_connection = timezone.now()
                    config.test_connection_success = True
                    config.save(update_fields=['last_test_connection', 'test_connection_success'])
            else:
                messages.error(request, f"Connection test failed: {result.get('error')}")
                if config:
                    config.last_test_connection = timezone.now()
                    config.test_connection_success = False
                    config.save(update_fields=['last_test_connection', 'test_connection_success'])
            return redirect('efris:configuration')

        elif action == 'validate_keys':
            # Validate keys and certificates
            if not config:
                messages.error(request, 'No configuration found. Please save configuration first.')
            else:
                try:
                    config.inspect_all_keys()  # This will print debug info
                    messages.success(request, 'Keys validated successfully. Check console for details.')
                except ValidationError as e:
                    messages.error(request, f'Key validation failed: {str(e)}')
                except Exception as e:
                    messages.error(request, f'Error validating keys: {str(e)}')
            return redirect('efris:configuration')

        elif action == 'upload_certificate':
            # Handle certificate upload via file
            if request.FILES.get('certificate_file'):
                certificate_file = request.FILES['certificate_file']
                try:
                    certificate_data = certificate_file.read().decode('utf-8')

                    if not config:
                        config = EFRISConfiguration.objects.create(company=company)

                    # Determine if it's a certificate or key based on content
                    content = certificate_data.strip()
                    if '-----BEGIN CERTIFICATE-----' in content:
                        config.public_certificate = content
                    elif '-----BEGIN PRIVATE KEY-----' in content or '-----BEGIN RSA PRIVATE KEY-----' in content:
                        config.private_key = content
                    elif '-----BEGIN PUBLIC KEY-----' in content or '-----BEGIN RSA PUBLIC KEY-----' in content:
                        config.public_certificate = content
                    else:
                        # Try to decode as base64
                        try:
                            # Clean and validate
                            clean_data = ''.join(content.split())
                            missing_padding = len(clean_data) % 4
                            if missing_padding:
                                clean_data += '=' * (4 - missing_padding)

                            decoded = base64.b64decode(clean_data)
                            # If we can decode it, store as-is
                            config.public_certificate = content
                        except:
                            messages.error(request, 'Could not identify the certificate/key format.')
                            return redirect('efris:configuration')

                    config.save()
                    messages.success(request, 'Certificate uploaded successfully')
                except Exception as e:
                    messages.error(request, f'Error uploading certificate: {str(e)}')
            else:
                messages.error(request, 'No certificate file provided')
            return redirect('efris:configuration')

        elif action == 'reset_config':
            # Reset configuration to defaults
            if config:
                config.environment = 'sandbox'
                config.mode = 'online'
                config.is_active = False
                config.is_initialized = False
                config.save()
                messages.success(request, 'Configuration reset to defaults')
            return redirect('efris:configuration')

    # Setup wizard
    wizard = EFRISConfigurationWizard(company)
    checklist = wizard.generate_setup_checklist()

    # Get current configuration status
    config_status = {
        'is_configured': config.is_configured if config else False,
        'is_certificate_valid': config.is_certificate_valid if config else False,
        'certificate_type': config.certificate_type if config else 'none',
        'private_key_type': config.private_key_type if config else 'none',
        'days_until_expiry': config.days_until_certificate_expires if config else None,
    }

    context = {
        'config': config,
        'checklist': checklist,
        'config_status': config_status,
        'ENVIRONMENT_CHOICES': EFRISConfiguration.ENVIRONMENT_CHOICES,
        'MODE_CHOICES': EFRISConfiguration.MODE_CHOICES,
    }

    return render(request, 'efris/configuration.html', context)


# ============================================================================
# PRODUCT MANAGEMENT
# ============================================================================

@login_required
def product_list(request):
    """List products with EFRIS upload status"""
    company = request.tenant

    # Filters
    search = request.GET.get('search', '')
    status = request.GET.get('status', 'all')

    products = Product.objects.all()

    if search:
        products = products.filter(
            Q(name__icontains=search) |
            Q(sku__icontains=search)
        )

    if status == 'uploaded':
        products = products.filter(efris_is_uploaded=True)
    elif status == 'pending':
        products = products.filter(efris_is_uploaded=False)

    # Pagination
    paginator = Paginator(products.order_by('-created_at'), 25)
    page = request.GET.get('page')
    products_page = paginator.get_page(page)

    context = {
        'products': products_page,
        'search': search,
        'status': status,
    }

    return render(request, 'efris/product_list.html', context)


@login_required
@require_http_methods(["POST"])
def product_upload(request, product_id):
    """Upload single product to EFRIS"""
    company = request.tenant
    product = get_object_or_404(Product, id=product_id)

    try:
        client = EnhancedEFRISAPIClient(company)
        result = client.register_product_with_efris(product)

        if result.get('success'):
            messages.success(
                request,
                f"Product '{product.name}' uploaded successfully to EFRIS"
            )
        else:
            messages.error(
                request,
                f"Failed to upload product: {result.get('error')}"
            )
    except Exception as e:
        messages.error(request, f"Upload error: {str(e)}")

    return redirect('efris:product_list')


@login_required
@require_http_methods(["POST"])
def product_bulk_upload(request):
    """Bulk upload products to EFRIS"""
    company = request.tenant

    # Get selected product IDs
    product_ids = request.POST.getlist('product_ids')

    if not product_ids:
        messages.warning(request, 'No products selected')
        return redirect('efris:product_list')

    try:
        results = bulk_register_products_with_efris(company)

        messages.success(
            request,
            f"Bulk upload completed: {results['successful']}/{results['total']} successful"
        )

        if results['errors']:
            for error in results['errors'][:5]:  # Show first 5 errors
                messages.warning(
                    request,
                    f"Product {error['name']}: {error['error']}"
                )

    except Exception as e:
        messages.error(request, f"Bulk upload failed: {str(e)}")

    return redirect('efris:product_list')


# ============================================================================
# INVOICE FISCALIZATION
# ============================================================================

@login_required
def invoice_list(request):
    """List invoices with fiscalization status"""
    company = request.tenant

    # Filters
    search = request.GET.get('search', '')
    status = request.GET.get('status', 'all')

    invoices = Invoice.objects.all()

    if search:
        invoices = invoices.filter(
            Q(number__icontains=search) |
            Q(customer__name__icontains=search)
        )

    if status == 'fiscalized':
        invoices = invoices.filter(is_fiscalized=True)
    elif status == 'pending':
        invoices = invoices.filter(is_fiscalized=False)

    # Pagination
    paginator = Paginator(invoices.order_by('-created_at'), 25)
    page = request.GET.get('page')
    invoices_page = paginator.get_page(page)

    context = {
        'invoices': invoices_page,
        'search': search,
        'status': status,
    }

    return render(request, 'efris/invoice_list.html', context)


@login_required
@require_http_methods(["POST"])
def invoice_fiscalize(request, invoice_id):
    """Fiscalize single invoice"""
    company = request.tenant
    invoice = get_object_or_404(Invoice, id=invoice_id)

    if invoice.is_fiscalized:
        messages.warning(request, 'Invoice is already fiscalized')
        return redirect('efris:invoice_list')

    try:
        service = EFRISInvoiceService(company)
        result = service.fiscalize_invoice(invoice, request.user)

        if result.get('success'):
            messages.success(
                request,
                f"Invoice {invoice.number} fiscalized successfully"
            )
        else:
            messages.error(
                request,
                f"Fiscalization failed: {result.get('message')}"
            )
    except Exception as e:
        messages.error(request, f"Fiscalization error: {str(e)}")

    return redirect('efris:invoice_list')




# ============================================================================
# STOCK MANAGEMENT
# ============================================================================

@login_required
def stock_management(request):
    """Stock management and EFRIS sync"""
    company = request.tenant

    # Get products with stock info
    products = Product.objects.filter(
        efris_is_uploaded=True
    )

    context = {
        'products': products,
    }

    return render(request, 'efris/stock_management.html', context)


@login_required
@require_http_methods(["POST"])
def stock_sync(request, product_id):
    """Sync product stock to EFRIS"""
    company = request.tenant
    product = get_object_or_404(
        Product,
        id=product_id,
        efris_is_uploaded=True
    )

    try:
        client = EnhancedEFRISAPIClient(company)
        results = client.sync_product_to_efris_stock(product)

        if results:
            messages.success(
                request,
                f"Stock synced for {product.name}"
            )
        else:
            messages.warning(request, 'No stock records to sync')

    except Exception as e:
        messages.error(request, f"Stock sync failed: {str(e)}")

    return redirect('efris:stock_management')


# ============================================================================
# COMMODITY CATEGORIES
# ============================================================================

from django.contrib import messages
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from .tasks import sync_categories_async



@login_required
def commodity_categories(request):
    """View and manage commodity categories"""
    company = request.tenant

    search = request.GET.get('search', '')

    categories = EFRISCommodityCategory.objects.all()

    if search:
        categories = categories.filter(
            Q(commodity_category_code__icontains=search) |
            Q(commodity_category_name__icontains=search)
        )

    # Pagination
    paginator = Paginator(categories.order_by('commodity_category_code'), 50)
    page = request.GET.get('page')
    categories_page = paginator.get_page(page)

    context = {
        'categories': categories_page,
        'search': search,
    }

    return render(request, 'efris/commodity_categories.html', context)

@login_required
@require_http_methods(["POST"])
def sync_categories(request):
    """Trigger async category sync"""
    company = request.tenant

    try:
        # Launch async task
        task = sync_categories_async.delay(
            company_id=company.company_id,
            schema_name=company.schema_name
        )

        messages.info(
            request,
            f"Category sync started (Task ID: {task.id}). "
            "This may take several minutes. Check back shortly."
        )

        # Store task ID in session to check status later
        request.session['sync_task_id'] = str(task.id)

    except Exception as e:
        messages.error(request, f"Failed to start sync: {str(e)}")

    return redirect('efris:commodity_categories')


# Add status check endpoint
@login_required
def check_sync_status(request):
    """Check status of category sync task"""
    from celery.result import AsyncResult
    import json
    from django.http import JsonResponse

    task_id = request.GET.get('task_id') or request.session.get('sync_task_id')

    if not task_id:
        return JsonResponse({'status': 'no_task'})

    task = AsyncResult(task_id)

    response = {
        'status': task.state,
        'ready': task.ready(),
    }

    if task.successful():
        result = task.result
        response.update({
            'success': result.get('success'),
            'total_fetched': result.get('total_fetched', 0),
            'error': result.get('error')
        })
    elif task.failed():
        response['error'] = str(task.info)

    return JsonResponse(response)


# ============================================================================
# TAXPAYER QUERY
# ============================================================================


@login_required
def taxpayer_query(request):
    """Query taxpayer information from EFRIS via AJAX"""
    company = request.tenant
    taxpayer_data = None
    error_msg = None

    if request.method == 'POST':
        tin = request.POST.get('tin', '').strip()
        nin_brn = request.POST.get('nin_brn', '').strip()

        if tin:
            try:
                from django_tenants.utils import schema_context

                with schema_context(company.schema_name):
                    service = TaxpayerQueryService(company)
                    result = service.query_taxpayer_by_tin(tin, nin_brn)

                    if result.get('success'):
                        taxpayer_data = result.get('taxpayer')
                    else:
                        error_msg = result.get('message', 'Taxpayer not found')

            except Exception as e:
                logger.error(f"EFRIS query error: {e}")
                error_msg = str(e)
        else:
            error_msg = "Please provide a TIN"

    # For AJAX requests
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({
            'success': bool(taxpayer_data),
            'taxpayer': taxpayer_data,
            'error': error_msg
        })

    # For regular requests
    context = {'taxpayer_data': taxpayer_data, 'error': error_msg}
    return render(request, 'efris/taxpayer_query.html', context)

# ============================================================================
# GOODS INQUIRY
# ============================================================================

@login_required
def goods_inquiry(request):
    """Search and query goods from EFRIS"""
    company = request.tenant
    goods_list = []
    pagination_info = None

    if request.method == 'GET' and request.GET.get('search'):
        keywords = request.GET.get('search', '').strip()
        page_no = int(request.GET.get('page', 1))

        if keywords:
            try:
                service = GoodsInquiryService(company)
                result = service.search_goods_by_keywords(
                    keywords=keywords,
                    page_no=page_no,
                    page_size=20
                )

                if result.get('success'):
                    goods_list = result.get('goods', [])
                    pagination_info = result.get('pagination', {})
                else:
                    messages.error(
                        request,
                        f"Search failed: {result.get('error')}"
                    )
            except Exception as e:
                messages.error(request, f"Search error: {str(e)}")

    context = {
        'goods_list': goods_list,
        'pagination': pagination_info,
        'search': request.GET.get('search', ''),
    }

    return render(request, 'efris/goods_inquiry.html', context)


# ============================================================================
# API LOGS & MONITORING
# ============================================================================

@login_required
def api_logs(request):
    """View EFRIS API logs"""
    company = request.tenant

    # Filters
    interface_code = request.GET.get('interface', '')
    status = request.GET.get('status', '')
    date_from = request.GET.get('date_from', '')

    logs = EFRISAPILog.objects.filter(company=company)

    if interface_code:
        logs = logs.filter(interface_code=interface_code)

    if status:
        logs = logs.filter(status=status)

    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            logs = logs.filter(created_at__date__gte=date_from_obj)
        except ValueError:
            pass

    # Pagination
    paginator = Paginator(logs.order_by('-request_time'), 50)
    page = request.GET.get('page')
    logs_page = paginator.get_page(page)

    # Get unique interface codes for filter
    interface_codes = EFRISAPILog.objects.filter(
        company=company
    ).values_list('interface_code', flat=True).distinct()

    context = {
        'logs': logs_page,
        'interface_codes': interface_codes,
        'selected_interface': interface_code,
        'selected_status': status,
        'date_from': date_from,
    }

    return render(request, 'efris/api_logs.html', context)


@login_required
def system_health(request):
    """System health check dashboard"""
    company = request.tenant

    health_checker = EFRISHealthChecker(company)
    health_status = health_checker.check_system_health()

    # Get metrics for different time ranges
    metrics_24h = EFRISMetricsCollector.get_system_metrics(company, 24)
    metrics_7d = EFRISMetricsCollector.get_system_metrics(company, 168)

    context = {
        'health_status': health_status,
        'metrics_24h': metrics_24h,
        'metrics_7d': metrics_7d,
    }

    return render(request, 'efris/system_health.html', context)


# ============================================================================
# AJAX/API ENDPOINTS
# ============================================================================

@login_required
@require_http_methods(["POST"])
def ajax_test_connection(request):
    """AJAX endpoint to test EFRIS connection"""
    company = request.tenant

    try:
        result = test_efris_connection(company)
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
def ajax_product_status(request, product_id):
    """Get product EFRIS status"""
    company = request.tenant
    product = get_object_or_404(Product, id=product_id)

    return JsonResponse({
        'success': True,
        'product': {
            'id': product.id,
            'name': product.name,
            'sku': product.sku,
            'efris_is_uploaded': product.efris_is_uploaded,
            'efris_upload_date': product.efris_upload_date.isoformat() if product.efris_upload_date else None,
            'efris_goods_id': getattr(product, 'efris_goods_id', None),
        }
    })


@login_required
def ajax_invoice_status(request, invoice_id):
    """Get invoice fiscalization status"""
    company = request.tenant
    invoice = get_object_or_404(Invoice, id=invoice_id)

    # Get latest audit
    latest_audit = FiscalizationAudit.objects.filter(
        invoice=invoice
    ).order_by('-created_at').first()

    return JsonResponse({
        'success': True,
        'invoice': {
            'id': invoice.id,
            'number': invoice.invoice_number,
            'is_fiscalized': invoice.is_fiscalized,
            'fiscal_code': getattr(invoice, 'fiscal_document_number', None),
            'fiscalization_date': invoice.fiscalization_date.isoformat() if getattr(invoice, 'fiscalization_date',
                                                                                    None) else None,
        },
        'latest_audit': {
            'action': latest_audit.action,
            'success': latest_audit.success,
            'created_at': latest_audit.created_at.isoformat(),
        } if latest_audit else None
    })


@login_required
def ajax_dashboard_stats(request):
    """Get dashboard statistics (for auto-refresh)"""
    company = request.tenant

    health_checker = EFRISHealthChecker(company)
    health_status = health_checker.check_system_health()

    metrics = EFRISMetricsCollector.get_system_metrics(company, 1)

    return JsonResponse({
        'success': True,
        'health_status': health_status['overall_status'],
        'metrics': {
            'total_requests': metrics['total_requests'],
            'success_rate': metrics['overall']['success_rate'],
            'average_duration': metrics['overall']['average_duration_ms'],
        },
        'timestamp': timezone.now().isoformat()
    })


# ============================================================================
# DIAGNOSTIC TOOLS
# ============================================================================

@login_required
def diagnostic_tool(request):
    """EFRIS diagnostic tool"""
    company = request.tenant
    diagnostic_result = None

    if request.method == 'POST':
        invoice_id = request.POST.get('invoice_id')

        if invoice_id:
            try:
                invoice = Invoice.objects.get(id=invoice_id)
                # Capture diagnostic output
                import io
                import sys

                old_stdout = sys.stdout
                sys.stdout = buffer = io.StringIO()

                diagnose_efris_issue(company, invoice)

                diagnostic_result = buffer.getvalue()
                sys.stdout = old_stdout

            except Invoice.DoesNotExist:
                messages.error(request, 'Invoice not found')
        else:
            # General diagnostic
            import io
            import sys

            old_stdout = sys.stdout
            sys.stdout = buffer = io.StringIO()

            diagnose_efris_issue(company)

            diagnostic_result = buffer.getvalue()
            sys.stdout = old_stdout

    context = {
        'diagnostic_result': diagnostic_result,
    }

    return render(request, 'efris/diagnostic_tool.html', context)


from .models import ProductUploadTask  # New model to track upload jobs
from .tasks import bulk_upload_products_task  # Celery task
import uuid
from django.urls import reverse



@require_http_methods(["GET", "POST"])
def upload_products_to_efris(request):
    """
    FIXED: Handle bulk uploads via background task to prevent timeout
    """
    company = request.tenant

    if request.method == "POST":
        selected_product_ids = request.POST.getlist('products')

        if not selected_product_ids:
            messages.warning(request, "No products selected for upload.")
            return redirect('efris:upload_products')

        # Validate products exist and aren't uploaded
        with schema_context(company.schema_name):
            products_to_upload = Product.objects.filter(
                id__in=selected_product_ids,
                efris_is_uploaded=False
            )

            count = products_to_upload.count()

            if count == 0:
                messages.info(request, "Selected products are already uploaded.")
                return redirect('efris:upload_products')

        # Decision: Sync vs Async based on count
        if count <= 5:
            # Small batch - process synchronously (immediate feedback)
            return _process_sync_upload(request, company, list(selected_product_ids))
        else:
            # Large batch - process asynchronously (background task)
            return _process_async_upload(request, company, list(selected_product_ids), count)

    # GET request - show product list
    with schema_context(company.schema_name):
        products = Product.objects.all().order_by('name')

    return render(request, 'efris/upload_products.html', {
        'products': products
    })


def _process_sync_upload(request, company, product_ids):
    """Process small batches synchronously (≤5 products)"""
    results = {'successful': [], 'failed': []}

    with schema_context(company.schema_name):
        products = Product.objects.filter(id__in=product_ids)

        with EnhancedEFRISAPIClient(company) as client:
            for product in products:
                result = client.register_product_with_efris(product)

                if result.get('success'):
                    results['successful'].append(product.name)
                else:
                    results['failed'].append({
                        'name': product.name,
                        'error': result.get('error', 'Unknown error')
                    })

    # Show results
    if results['successful']:
        messages.success(
            request,
            f"✅ {len(results['successful'])} products uploaded successfully."
        )

    if results['failed']:
        error_details = "; ".join([
            f"{f['name']}: {f['error']}"
            for f in results['failed'][:3]
        ])
        messages.error(
            request,
            f"❌ {len(results['failed'])} products failed. {error_details}"
        )

    return redirect('efris:upload_products')


def _process_async_upload(request, company, product_ids, count):
    """Process large batches asynchronously (>5 products)"""

    # Create tracking record
    task_id = str(uuid.uuid4())

    with schema_context(company.schema_name):
        upload_task = ProductUploadTask.objects.create(
            task_id=task_id,
            company=company,
            total_products=count,
            status='pending',
            created_by=request.user
        )

    # Queue background task
    bulk_upload_products_task.delay(
        company_id=company.id,
        schema_name=company.schema_name,
        product_ids=product_ids,
        task_id=task_id
    )

    messages.info(
        request,
        f"⏳ Upload started for {count} products. "
        f"<a href='{reverse('efris:upload_status', args=[task_id])}'>Track progress here</a>",
        extra_tags='safe'  # Allow HTML in message
    )

    return redirect('efris:upload_status', task_id=task_id)


@require_http_methods(["GET"])
def upload_status(request, task_id):
    """Show progress page for async uploads"""
    company = request.tenant

    with schema_context(company.schema_name):
        try:
            task = ProductUploadTask.objects.get(task_id=task_id)
        except ProductUploadTask.DoesNotExist:
            messages.error(request, "Upload task not found.")
            return redirect('efris:upload_products')

    return render(request, 'efris/upload_status.html', {
        'task': task
    })


@require_http_methods(["GET"])
def upload_status_api(request, task_id):
    """API endpoint for progress polling (AJAX)"""
    company = request.tenant

    with schema_context(company.schema_name):
        try:
            task = ProductUploadTask.objects.get(task_id=task_id)

            return JsonResponse({
                'status': task.status,
                'progress': task.progress_percentage,
                'processed': task.processed_count,
                'total': task.total_products,
                'successful': task.successful_count,
                'failed': task.failed_count,
                'errors': task.error_details or [],
                'completed_at': task.completed_at.isoformat() if task.completed_at else None
            })
        except ProductUploadTask.DoesNotExist:
            return JsonResponse({'error': 'Task not found'}, status=404)

