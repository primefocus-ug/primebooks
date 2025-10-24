from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator
from django.utils import timezone
from datetime import datetime, date, timedelta

from invoices.models import Invoice
from sales.models import Sale
from inventory.models import Product,Category
from .services import EnhancedEFRISAPIClient


@login_required
def invoice_detail_query(request):
    company = request.tenant
    invoice_data = None

    if request.method == 'POST':
        invoice_no = request.POST.get('invoice_no', '').strip()

        if invoice_no:
            try:
                client = EnhancedEFRISAPIClient(company)
                result = client.t108_query_invoice_detail(invoice_no)

                if result.get('success'):
                    invoice_data = result.get('invoice_data')
                    messages.success(
                        request,
                        f"Invoice {invoice_no} retrieved successfully"
                    )
                else:
                    messages.error(
                        request,
                        f"Query failed: {result.get('error')}"
                    )
            except Exception as e:
                messages.error(request, f"Query error: {str(e)}")
        else:
            messages.warning(request, 'Please provide an invoice number')

    context = {
        'invoice_data': invoice_data,
    }

    return render(request, 'efris/invoice_detail_query.html', context)


@login_required
def zreport_list(request):
    company = request.tenant

    # Get date range
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    today = date.today()
    date_range = []

    for i in range(30):  # Last 30 days
        report_date = today - timedelta(days=i + 1)

        # Check if report exists for this date
        # (You might want to store Z-report submissions in a model)
        date_range.append({
            'date': report_date,
            'uploaded': False,  # Check against your records
        })

    context = {
        'date_range': date_range,
        'date_from': date_from,
        'date_to': date_to,
    }

    return render(request, 'efris/zreport_list.html', context)


@login_required
def zreport_generate(request, report_date_str):
    company = request.tenant

    try:
        report_date = datetime.strptime(report_date_str, '%Y-%m-%d').date()
    except ValueError:
        messages.error(request, 'Invalid date format')
        return redirect('efris:zreport_list')

    try:
        client = EnhancedEFRISAPIClient(company)
        result = client.generate_daily_zreport(report_date)

        if result.get('success'):
            zreport_data = result.get('zreport_data')

            context = {
                'report_date': report_date,
                'zreport_data': zreport_data,
            }

            return render(request, 'efris/zreport_preview.html', context)
        else:
            messages.error(
                request,
                f"Failed to generate Z-report: {result.get('error')}"
            )
            return redirect('efris:zreport_list')

    except Exception as e:
        messages.error(request, f"Error: {str(e)}")
        return redirect('efris:zreport_list')


@login_required
@require_http_methods(["POST"])
def zreport_upload(request):
    company = request.tenant

    report_date_str = request.POST.get('report_date')

    try:
        report_date = datetime.strptime(report_date_str, '%Y-%m-%d').date()
    except ValueError:
        messages.error(request, 'Invalid date format')
        return redirect('efris:zreport_list')

    try:
        client = EnhancedEFRISAPIClient(company)

        # Generate report
        gen_result = client.generate_daily_zreport(report_date)

        if not gen_result.get('success'):
            messages.error(
                request,
                f"Failed to generate Z-report: {gen_result.get('error')}"
            )
            return redirect('efris:zreport_list')

        # Upload to EFRIS
        upload_result = client.t116_upload_zreport(
            gen_result.get('zreport_data')
        )

        if upload_result.get('success'):
            messages.success(
                request,
                f"Z-report for {report_date} uploaded successfully"
            )
        else:
            messages.error(
                request,
                f"Upload failed: {upload_result.get('error')}"
            )

    except Exception as e:
        messages.error(request, f"Error: {str(e)}")

    return redirect('efris:zreport_list')


@login_required
def invoice_consistency_check(request):
    """Check invoice consistency with EFRIS"""
    company = request.tenant
    results = None

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'check_single':
            invoice_no = request.POST.get('invoice_no', '').strip()
            invoice_type = request.POST.get('invoice_type', '1')

            if invoice_no:
                try:
                    client = EnhancedEFRISAPIClient(company)
                    result = client.t117_check_invoices([{
                        'invoiceNo': invoice_no,
                        'invoiceType': invoice_type
                    }])

                    results = {
                        'checked': [invoice_no],
                        'result': result
                    }

                    if result.get('success'):
                        inconsistent = result.get('inconsistent_invoices', [])
                        if inconsistent:
                            messages.warning(
                                request,
                                f"Invoice {invoice_no} is inconsistent with EFRIS"
                            )
                        else:
                            messages.success(
                                request,
                                f"Invoice {invoice_no} is consistent"
                            )
                    else:
                        messages.error(
                            request,
                            f"Check failed: {result.get('error')}"
                        )

                except Exception as e:
                    messages.error(request, f"Error: {str(e)}")
            else:
                messages.warning(request, 'Please provide an invoice number')

        elif action == 'check_recent':
            # Check recent fiscalized invoices
            try:
                recent_invoices = Invoice.objects.filter(
                    company=company,
                    is_fiscalized=True
                ).order_by('-created_at')[:20]

                invoice_list = []
                for inv in recent_invoices:
                    invoice_no = getattr(inv, 'invoice_number', None) or inv.number
                    invoice_list.append({
                        'invoiceNo': invoice_no,
                        'invoiceType': '1'
                    })

                if invoice_list:
                    client = EnhancedEFRISAPIClient(company)
                    result = client.t117_check_invoices(invoice_list)

                    results = {
                        'checked': [inv['invoiceNo'] for inv in invoice_list],
                        'result': result
                    }

                    if result.get('success'):
                        inconsistent_count = len(
                            result.get('inconsistent_invoices', [])
                        )
                        if inconsistent_count > 0:
                            messages.warning(
                                request,
                                f"Found {inconsistent_count} inconsistent invoice(s)"
                            )
                        else:
                            messages.success(
                                request,
                                f"All {len(invoice_list)} invoices are consistent"
                            )
                    else:
                        messages.error(
                            request,
                            f"Check failed: {result.get('error')}"
                        )
                else:
                    messages.warning(request, 'No fiscalized invoices found')

            except Exception as e:
                messages.error(request, f"Error: {str(e)}")

    context = {
        'results': results,
    }

    return render(request, 'efris/invoice_consistency.html', context)


from django.template.loader import render_to_string
from django.http import JsonResponse

@login_required
def goods_inquiry(request):
    """Search and browse goods from EFRIS"""
    company = request.tenant
    goods_list = []
    pagination_info = None

    # Get search parameters
    search_term = request.GET.get('search', '').strip()
    goods_code = request.GET.get('goods_code', '').strip()
    goods_name = request.GET.get('goods_name', '').strip()
    category = request.GET.get('category', '').strip()
    page_size = int(request.GET.get('page_size', 10))
    page = int(request.GET.get('page', 1))

    if search_term or goods_code or goods_name or category:
        try:
            client = EnhancedEFRISAPIClient(company)

            query_params = {
                'page_no': page,
                'page_size': min(page_size, 100),  # EFRIS limit
            }

            if search_term:
                query_params['combine_keywords'] = search_term
            if goods_code:
                query_params['goods_code'] = goods_code
            if goods_name:
                query_params['goods_name'] = goods_name
            if category:
                query_params['commodity_category_name'] = category

            result = client.t127_query_goods(**query_params)

            if result.get('success'):
                goods_list = result.get('goods', [])
                pagination_info = result.get('pagination', {})
            else:
                messages.error(request, f"Search failed: {result.get('error')}")

        except Exception as e:
            messages.error(request, f"Search error: {str(e)}")

    context = {
        'goods_list': goods_list,
        'pagination': pagination_info,
        'search_term': search_term,
        'goods_code': goods_code,
        'goods_name': goods_name,
        'category': category,
    }

    # ✅ If AJAX request, return only results section
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        html = render_to_string('efris/goods_inquiry.html', context, request=request)
        # Extract only the results portion
        start = html.find('<!-- Results Section -->')
        end = html.find('<!-- Pagination -->', start)
        return JsonResponse({'html': html[start:end]})

    return render(request, 'efris/goods_inquiry.html', context)




@login_required
def goods_detail(request, goods_id):
    """View detailed goods information"""
    company = request.tenant

    # In a real implementation, you'd query T127 with specific filters
    # or use T144 to get the goods by code

    context = {
        'goods_id': goods_id,
    }

    return render(request, 'efris/goods_detail.html', context)


@login_required
@require_http_methods(["POST"])
def goods_import_to_product(request):
    """Import goods from EFRIS and only update SKU if necessary"""
    company = request.tenant
    goods_code = request.POST.get('goods_code')

    if not goods_code:
        messages.error(request, 'Goods code is required')
        return redirect('efris:goods_inquiry')

    try:
        client = EnhancedEFRISAPIClient(company)
        result = client.t144_query_goods_by_code(goods_code)

        if not result.get('success'):
            messages.error(request, f"Failed to get goods details: {result.get('error')}")
            return redirect('efris:goods_inquiry')

        goods_list = result.get('goods', [])
        if not goods_list:
            messages.error(request, f"Goods {goods_code} not found")
            return redirect('efris:goods_inquiry')

        goods = goods_list[0]
        new_sku = goods.get('goodsCode')
        product_name = goods.get('goodsName') or 'Imported from EFRIS'

        # Search for existing product by name OR SKU starting with EFRIS code
        from django.db.models import Q
        product = Product.objects.filter(
            Q(name=product_name) | Q(sku__startswith=new_sku)
        ).first()

        if product:
            # Only update SKU if it’s different
            if product.sku != new_sku:
                # Ensure no other product already has this SKU
                if Product.objects.exclude(pk=product.pk).filter(sku=new_sku).exists():
                    messages.warning(
                        request,
                        f"Cannot update SKU to '{new_sku}' because it already exists on another product."
                    )
                else:
                    product.sku = new_sku
                    product.efris_goods_id = goods.get('id')
                    product.save(update_fields=['sku', 'efris_goods_id'])
                    messages.success(request, f"SKU for product '{product.name}' updated successfully")
            else:
                messages.info(request, f"No changes needed for product '{product.name}'")
        else:
            # Create new product (minimal required fields)
            from decimal import Decimal

            if Product.objects.filter(sku=new_sku).exists():
                messages.error(request, f"Cannot create product because SKU '{new_sku}' already exists")
                return redirect('efris:goods_inquiry')

            product = Product.objects.create(
                name=product_name,
                sku=new_sku,
                cost_price=Decimal('0.00'),  # required field
                selling_price=Decimal(goods.get('unitPrice') or 0),
                unit_of_measure=goods.get('measureUnit') or 'each',
                efris_is_uploaded=True,
                efris_goods_id=goods.get('id')
            )
            messages.success(request, f"Product '{product.name}' created successfully")

        return redirect('inventory:product_detail', pk=product.id)

    except Exception as e:
        messages.error(request, f"Import error: {str(e)}")
        return redirect('efris:goods_inquiry')



@login_required
def goods_batch_query(request):
    """Query multiple goods by codes"""
    company = request.tenant
    goods_results = []

    if request.method == 'POST':
        goods_codes_text = request.POST.get('goods_codes', '').strip()

        if goods_codes_text:
            # Parse codes (comma or newline separated)
            goods_codes = [
                code.strip()
                for code in goods_codes_text.replace('\n', ',').split(',')
                if code.strip()
            ]

            if goods_codes:
                try:
                    client = EnhancedEFRISAPIClient(company)
                    result = client.t144_query_goods_by_code(goods_codes)

                    if result.get('success'):
                        goods_results = result.get('goods', [])
                        messages.success(
                            request,
                            f"Found {len(goods_results)} goods"
                        )
                    else:
                        messages.error(
                            request,
                            f"Query failed: {result.get('error')}"
                        )

                except Exception as e:
                    messages.error(request, f"Error: {str(e)}")
            else:
                messages.warning(request, 'Please provide goods codes')
        else:
            messages.warning(request, 'Please provide goods codes')

    context = {
        'goods_results': goods_results,
    }

    return render(request, 'efris/goods_batch_query.html', context)


@login_required
@require_http_methods(["POST"])
def goods_sync_from_efris(request):
    """Sync all goods from EFRIS to local products"""
    company = request.tenant

    try:
        client = EnhancedEFRISAPIClient(company)
        result = client.sync_goods_from_efris_to_products()

        if result['total'] > 0:
            messages.success(
                request,
                f"Sync completed: {result['created']} created, "
                f"{result['updated']} updated, {result['failed']} failed"
            )

            if result['errors']:
                for error in result['errors'][:5]:  # Show first 5 errors
                    messages.warning(
                        request,
                        f"Error: {error.get('error')}"
                    )
        else:
            messages.info(request, 'No goods found to sync')

    except Exception as e:
        messages.error(request, f"Sync error: {str(e)}")

    return redirect('efris:goods_inquiry')



@login_required
def ajax_goods_search(request):
    """AJAX endpoint for goods search"""
    company = request.tenant

    search_term = request.GET.get('q', '').strip()

    if not search_term or len(search_term) < 2:
        return JsonResponse({'results': []})

    try:
        client = EnhancedEFRISAPIClient(company)
        goods_list = client.search_goods_in_efris(search_term, limit=10)

        results = [
            {
                'id': goods.get('id'),
                'code': goods.get('goodsCode'),
                'name': goods.get('goodsName'),
                'price': goods.get('unitPrice'),
                'unit': goods.get('measureUnit'),
            }
            for goods in goods_list
        ]

        return JsonResponse({'results': results})

    except Exception as e:
        return JsonResponse({
            'error': str(e)
        }, status=500)


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
    """Get product EFRIS upload status"""
    company = request.tenant

    try:
        product = get_object_or_404(Product, id=product_id, company=company)

        return JsonResponse({
            'success': True,
            'product': {
                'id': product.id,
                'name': product.name,
                'sku': product.sku,
                'efris_is_uploaded': getattr(product, 'efris_is_uploaded', False),
                'efris_upload_date': (
                    product.efris_upload_date.isoformat()
                    if getattr(product, 'efris_upload_date', None)
                    else None
                ),
                'efris_goods_id': getattr(product, 'efris_goods_id', None),
                'efris_item_code': getattr(product, 'efris_item_code', None),
            }
        })
    except Product.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Product not found'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
def ajax_invoice_status(request, invoice_id):
    """Get invoice fiscalization status"""
    company = request.tenant

    try:
        invoice = get_object_or_404(Invoice, id=invoice_id, company=company)

        # Get latest audit
        latest_audit = FiscalizationAudit.objects.filter(
            invoice=invoice
        ).order_by('-created_at').first()

        response_data = {
            'success': True,
            'invoice': {
                'id': invoice.id,
                'number': getattr(invoice, 'number', None) or getattr(invoice, 'invoice_number', None),
                'is_fiscalized': getattr(invoice, 'is_fiscalized', False),
                'fiscal_code': getattr(invoice, 'fiscal_code', None),
                'fiscalization_date': (
                    invoice.fiscalization_date.isoformat()
                    if getattr(invoice, 'fiscalization_date', None)
                    else None
                ),
                'total_amount': float(invoice.total_amount) if hasattr(invoice, 'total_amount') else 0,
            }
        }

        if latest_audit:
            response_data['latest_audit'] = {
                'action': latest_audit.action,
                'success': latest_audit.success,
                'created_at': latest_audit.created_at.isoformat(),
                'error_message': latest_audit.error_message,
                'fiscal_document_number': latest_audit.fiscal_document_number,
                'verification_code': latest_audit.verification_code,
            }
        else:
            response_data['latest_audit'] = None

        return JsonResponse(response_data)

    except Invoice.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Invoice not found'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
def ajax_dashboard_stats(request):
    """Get dashboard statistics (for auto-refresh)"""
    company = request.tenant

    try:
        # Health check
        health_checker = EFRISHealthChecker(company)
        health_status = health_checker.check_system_health()

        # Metrics
        metrics = EFRISMetricsCollector.get_system_metrics(company, 1)  # Last hour

        # Recent operations count
        recent_logs = EFRISAPILog.objects.filter(
            company=company,
            created_at__gte=timezone.now() - timezone.timedelta(hours=1)
        ).count()

        return JsonResponse({
            'success': True,
            'health_status': health_status['overall_status'],
            'metrics': {
                'total_requests': metrics.get('total_requests', 0),
                'success_rate': metrics['overall'].get('success_rate', 0),
                'average_duration': metrics['overall'].get('average_duration_ms', 0),
                'recent_operations': recent_logs,
            },
            'timestamp': timezone.now().isoformat()
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


# ============================================================================
# BULK OPERATIONS STATUS
# ============================================================================

@login_required
def ajax_bulk_operation_status(request, operation_id):
    """Check status of bulk operation (upload, sync, etc)"""
    company = request.tenant

    try:
        # This would check a task queue or cache for operation status
        # For now, return a simple response
        return JsonResponse({
            'success': True,
            'operation_id': operation_id,
            'status': 'completed',  # or 'processing', 'failed'
            'progress': 100,
            'total': 10,
            'completed': 10,
            'failed': 0,
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


# ============================================================================
# CONFIGURATION VALIDATION
# ============================================================================

@login_required
def ajax_validate_config(request):
    """Validate EFRIS configuration"""
    company = request.tenant

    try:
        errors = []
        warnings = []

        # Check if config exists
        try:
            config = company.efris_config
        except:
            return JsonResponse({
                'success': False,
                'valid': False,
                'errors': ['EFRIS configuration not found']
            })

        # Validate device number
        if not config.device_number:
            errors.append('Device number is missing')

        # Validate keys
        if not config.private_key:
            errors.append('Private key is missing')

        if not config.public_certificate:
            warnings.append('Public certificate is missing')

        # Validate TIN
        if not company.tin:
            errors.append('Company TIN is not set')

        # Check if active
        if not config.is_active:
            warnings.append('Configuration is inactive')

        return JsonResponse({
            'success': True,
            'valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings,
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


# ============================================================================
# LIVE SEARCH
# ============================================================================

@login_required
def ajax_product_search(request):
    """AJAX product search for autocomplete"""
    company = request.tenant
    query = request.GET.get('q', '').strip()

    if not query or len(query) < 2:
        return JsonResponse({'results': []})

    try:
        products = Product.objects.filter(
            company=company,
            name__icontains=query
        )[:10]

        results = [
            {
                'id': p.id,
                'name': p.name,
                'sku': p.sku,
                'efris_uploaded': getattr(p, 'efris_is_uploaded', False),
            }
            for p in products
        ]

        return JsonResponse({'results': results})

    except Exception as e:
        return JsonResponse({
            'error': str(e)
        }, status=500)


@login_required
def ajax_invoice_search(request):
    """AJAX invoice search for autocomplete"""
    company = request.tenant
    query = request.GET.get('q', '').strip()

    if not query or len(query) < 2:
        return JsonResponse({'results': []})

    try:
        invoices = Invoice.objects.filter(
            company=company,
            number__icontains=query
        )[:10]

        results = [
            {
                'id': inv.id,
                'number': getattr(inv, 'number', None) or getattr(inv, 'invoice_number', None),
                'is_fiscalized': getattr(inv, 'is_fiscalized', False),
                'total': float(inv.total_amount) if hasattr(inv, 'total_amount') else 0,
            }
            for inv in invoices
        ]

        return JsonResponse({'results': results})

    except Exception as e:
        return JsonResponse({
            'error': str(e)
        }, status=500)


# ============================================================================
# REAL-TIME NOTIFICATIONS
# ============================================================================

@login_required
def ajax_get_notifications(request):
    """Get recent EFRIS notifications"""
    company = request.tenant

    try:
        from .models import EFRISNotification

        notifications = EFRISNotification.objects.filter(
            company=company,
            status='unread'
        ).order_by('-created_at')[:5]

        results = [
            {
                'id': notif.id,
                'type': notif.notification_type,
                'priority': notif.priority,
                'title': notif.title,
                'message': notif.message,
                'created_at': notif.created_at.isoformat(),
            }
            for notif in notifications
        ]

        return JsonResponse({
            'success': True,
            'notifications': results,
            'unread_count': notifications.count()
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_http_methods(["POST"])
def ajax_mark_notification_read(request, notification_id):
    """Mark notification as read"""
    company = request.tenant

    try:
        from .models import EFRISNotification

        notification = get_object_or_404(
            EFRISNotification,
            id=notification_id,
            company=company
        )

        notification.mark_as_read(request.user)

        return JsonResponse({
            'success': True,
            'message': 'Notification marked as read'
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
def ajax_invoice_verify(request, invoice_id):
    """AJAX endpoint to verify invoice consistency"""
    company = request.tenant

    try:
        invoice = Invoice.objects.get(id=invoice_id, company=company)

        client = EnhancedEFRISAPIClient(company)
        result = client.verify_invoice_consistency(invoice)

        return JsonResponse(result)

    except Invoice.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Invoice not found'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)