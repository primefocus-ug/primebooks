"""
EFRIS Export Invoice Views
Handles export invoice creation, customs SAD submission, and status tracking
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator
from django.utils import timezone
from django.db import transaction
from datetime import datetime, timedelta
import json
import structlog

from company.models import Company
from .services import (
    EnhancedEFRISAPIClient,
    EFRISError,
    create_efris_service
)
from .models import (
    EFRISConfiguration,
    EFRISAPILog,
    FiscalizationAudit
)

logger = structlog.get_logger(__name__)


# ============================================================================
# EXPORT INVOICE VIEWS
# ============================================================================

@login_required
def export_invoices_list_view(request):
    """
    Display all export invoices with their customs clearance status
    """
    company = request.tenant

    if not company.efris_enabled:
        messages.error(request, "EFRIS is not enabled for your company")
        return redirect('dashboard')

    context = {
        'page_title': 'Export Invoices',
        'company': company
    }

    try:
        # Get filter parameters
        status = request.GET.get('status')  # cleared, pending, failed
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        buyer_country = request.GET.get('buyer_country')

        # Query local export invoices — scoped to tenant via sale__store__company
        from invoices.models import Invoice

        invoices = Invoice.objects.filter(
            sale__store__company=company,
            is_fiscalized=True,
            fiscal_document_number__isnull=False
        ).exclude(
            fiscal_document_number=''
        ).select_related(
            'sale', 'sale__customer', 'sale__store'
        ).order_by('-created_at')

        # Apply filters
        if status == 'cleared':
            invoices = invoices.filter(export_status='102')  # Exited/Cleared
        elif status == 'pending':
            invoices = invoices.filter(export_status='101')  # Under processing
        elif status == 'failed':
            invoices = invoices.filter(export_status__isnull=True)

        if start_date:
            invoices = invoices.filter(created_at__date__gte=start_date)

        if end_date:
            invoices = invoices.filter(created_at__date__lte=end_date)

        # Paginate
        paginator = Paginator(invoices, 20)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)

        context['invoices'] = page_obj
        context['filters'] = {
            'status': status,
            'start_date': start_date,
            'end_date': end_date,
            'buyer_country': buyer_country
        }

        # Statistics — scoped to this tenant
        all_export_invoices = Invoice.objects.filter(
            sale__store__company=company,
            is_fiscalized=True,
        ).exclude(fiscal_document_number='')

        context['stats'] = {
            'total': all_export_invoices.count(),
            'cleared': all_export_invoices.filter(export_status='102').count(),
            'pending': all_export_invoices.filter(export_status='101').count(),
        }

    except Exception as e:
        logger.error(f"Export invoices list failed: {e}", exc_info=True)
        messages.error(request, f"Error loading export invoices: {str(e)}")

    return render(request, 'efris/export_invoices_list.html', context)

#
# @login_required
# def create_export_invoice_view(request):
#     """
#     Create a new export invoice with T109
#     """
#     company = request.tenant
#
#     if not company.efris_enabled:
#         messages.error(request, "EFRIS is not enabled for your company")
#         return redirect('dashboard')
#
#     context = {
#         'page_title': 'Create Export Invoice',
#         'company': company,
#         'delivery_terms': [
#             ('FOB', 'FOB - Free On Board'),
#             ('CIF', 'CIF - Cost, Insurance and Freight'),
#             ('CFR', 'CFR - Cost and Freight'),
#             ('EXW', 'EXW - Ex Works'),
#             ('DDP', 'DDP - Delivered Duty Paid'),
#             ('DAP', 'DAP - Delivered At Place'),
#             ('CPT', 'CPT - Carriage Paid To'),
#             ('CIP', 'CIP - Carriage and Insurance Paid To'),
#             ('FAS', 'FAS - Free Alongside Ship'),
#             ('FCA', 'FCA - Free Carrier'),
#             ('DPU', 'DPU - Delivered at Place Unloaded'),
#         ],
#         'currencies': [
#             ('USD', 'US Dollar'),
#             ('EUR', 'Euro'),
#             ('GBP', 'British Pound'),
#             ('KES', 'Kenyan Shilling'),
#             ('TZS', 'Tanzanian Shilling'),
#             ('RWF', 'Rwandan Franc'),
#         ]
#     }
#
#     if request.method == 'POST':
#         try:
#             # Get sale/invoice to export
#             sale_id = request.POST.get('sale_id')
#             invoice_id = request.POST.get('invoice_id')
#
#             # Get export-specific data
#             delivery_terms = request.POST.get('delivery_terms')
#             total_weight = float(request.POST.get('total_weight'))
#             buyer_country = request.POST.get('buyer_country')
#             buyer_passport = request.POST.get('buyer_passport', '')
#             foreign_currency = request.POST.get('foreign_currency')
#             exchange_rate = float(
#                 request.POST.get('exchange_rate')) if foreign_currency and foreign_currency != 'UGX' else None
#
#             # Get HS codes (from form or existing data)
#             hs_codes_json = request.POST.get('hs_codes')
#             hs_codes = json.loads(hs_codes_json) if hs_codes_json else []
#
#             # Validate required fields
#             if not all([delivery_terms, total_weight, buyer_country]):
#                 messages.error(request,
#                                "Delivery terms, total weight, and buyer country are mandatory for export invoices")
#                 return redirect('efris:create_export_invoice')
#
#             if not hs_codes:
#                 messages.error(request, "HS codes are mandatory for all export items")
#                 return redirect('efris:create_export_invoice')
#
#             # Get the sale or invoice — tenant-scoped via sale__store__company
#             sale_or_invoice = None
#             if sale_id:
#                 from sales.models import Sale
#                 sale_or_invoice = get_object_or_404(Sale, id=sale_id, store__company=company)
#             elif invoice_id:
#                 from invoices.models import Invoice
#                 invoice_obj = get_object_or_404(Invoice, id=invoice_id, sale__store__company=company)
#                 sale_or_invoice = invoice_obj.sale
#
#             if not sale_or_invoice:
#                 messages.error(request, "Sale or invoice not found")
#                 return redirect('efris:create_export_invoice')
#
#             # Create export service
#             export_service = create_efris_service(company, 'export', sale_or_invoice.store)
#
#             # Fiscalize export invoice
#             result = export_service.fiscalize_export_sale(
#                 sale_or_invoice=sale_or_invoice,
#                 delivery_terms=delivery_terms,
#                 hs_codes=hs_codes,
#                 total_weight=total_weight,
#                 buyer_country=buyer_country,
#                 buyer_passport=buyer_passport,
#                 foreign_currency=foreign_currency,
#                 exchange_rate=exchange_rate,
#                 user=request.user
#             )
#
#             if result.get('success'):
#                 invoice_no = result['data']['invoice_no']
#                 fiscal_code = result['data'].get('fiscal_code', '')
#
#                 # Update invoice/sale with export data
#                 from invoices.models import Invoice
#                 if hasattr(sale_or_invoice, 'invoice_detail'):
#                     invoice = sale_or_invoice.invoice_detail
#                 else:
#                     invoice = Invoice.objects.filter(sale=sale_or_invoice).first()
#
#                 if invoice:
#                     invoice.fiscal_document_number = invoice_no
#                     invoice.fiscal_number = invoice_no
#                     invoice.verification_code = fiscal_code
#                     invoice.is_fiscalized = True
#                     invoice.fiscalization_status = 'fiscalized'
#                     invoice.fiscalization_time = timezone.now()
#                     invoice.export_status = '101'  # Pending customs clearance
#                     invoice.export_delivery_terms = delivery_terms
#                     invoice.export_total_weight = total_weight
#                     invoice.save(update_fields=[
#                         'fiscal_document_number', 'fiscal_number', 'verification_code',
#                         'is_fiscalized', 'fiscalization_status', 'fiscalization_time',
#                         'export_status', 'export_delivery_terms', 'export_total_weight',
#                     ])
#
#                 messages.success(
#                     request,
#                     f"✓ Export invoice created successfully! Invoice No: {invoice_no}"
#                 )
#
#                 # Redirect to SAD submission
#                 return redirect('efris:submit_export_sad', invoice_no=invoice_no)
#             else:
#                 messages.error(request, f"Export invoice creation failed: {result.get('error')}")
#
#         except Exception as e:
#             logger.error(f"Export invoice creation failed: {e}", exc_info=True)
#             messages.error(request, f"Error: {str(e)}")
#
#     # Load pending sales/invoices for export
#     try:
#         from sales.models import Sale
#         pending_sales = Sale.objects.filter(
#             store__company=company,
#             status__in=['COMPLETED', 'PAID'],
#             is_fiscalized=False
#         ).select_related('customer', 'store').order_by('-created_at')[:50]
#
#         context['pending_sales'] = pending_sales
#     except Exception as e:
#         logger.error(f"Failed to load pending sales: {e}")
#         context['pending_sales'] = []
#
#     return render(request, 'efris/create_export_invoice.html', context)


@login_required
def submit_export_sad_view(request, invoice_no):
    """
    C105 - Submit Customs SAD Declaration for Export
    """
    company = request.tenant

    if not company.efris_enabled:
        messages.error(request, "EFRIS is not enabled for your company")
        return redirect('dashboard')

    # Get the invoice — tenant-scoped via sale__store__company
    from invoices.models import Invoice
    try:
        invoice = Invoice.objects.get(
            fiscal_document_number=invoice_no,
            sale__store__company=company
        )
    except Invoice.DoesNotExist:
        messages.error(request, f"Invoice {invoice_no} not found")
        return redirect('efris:export_invoices_list')

    context = {
        'page_title': f'Submit Customs SAD - {invoice_no}',
        'company': company,
        'invoice': invoice,
        'invoice_no': invoice_no
    }

    if request.method == 'POST':
        try:
            # Get SAD submission data
            sad_number = request.POST.get('sad_number')
            exit_office = request.POST.get('exit_office')
            exit_officer = request.POST.get('exit_officer')
            exit_date = request.POST.get('exit_date')
            exit_time = request.POST.get('exit_time', '00:00:00')

            # Get exported items data
            exported_items = []
            item_count = int(request.POST.get('item_count', 0))

            for i in range(item_count):
                hs_code = request.POST.get(f'hs_code_{i}')
                item_id = request.POST.get(f'item_id_{i}')
                quantity = request.POST.get(f'quantity_{i}')

                if hs_code and item_id and quantity:
                    exported_items.append({
                        'hsCode': hs_code,
                        'invoiceItemId': item_id,
                        'exportedQuantity': quantity
                    })

            # Validate
            if not sad_number or len(sad_number) != 20:
                messages.error(request, "SAD number must be exactly 20 digits")
                return redirect('efris:submit_export_sad', invoice_no=invoice_no)

            if not all([exit_office, exit_officer, exit_date]):
                messages.error(request, "All exit information fields are required")
                return redirect('efris:submit_export_sad', invoice_no=invoice_no)

            if not exported_items:
                messages.error(request, "At least one exported item is required")
                return redirect('efris:submit_export_sad', invoice_no=invoice_no)

            # Combine date and time
            exit_datetime_str = f"{exit_date} {exit_time}"
            exit_datetime = datetime.strptime(exit_datetime_str, '%Y-%m-%d %H:%M:%S')

            # Submit SAD
            export_service = create_efris_service(company, 'export', invoice.sale.store if invoice.sale else None)

            result = export_service.submit_customs_declaration(
                invoice_no=invoice_no,
                sad_number=sad_number,
                exit_office=exit_office,
                exit_officer=exit_officer,
                exit_datetime=exit_datetime,
                exported_items=exported_items
            )

            if result.get('success'):
                # Update invoice
                invoice.export_sad_number = sad_number
                invoice.export_sad_submitted_at = timezone.now()
                invoice.export_status = '101'  # Under processing
                invoice.save(update_fields=[
                    'export_sad_number', 'export_sad_submitted_at', 'export_status'
                ])

                messages.success(
                    request,
                    f"✓ Customs SAD declaration submitted successfully! SAD No: {sad_number}"
                )
                return redirect('efris:export_invoice_detail', invoice_no=invoice_no)
            else:
                messages.error(request, f"SAD submission failed: {result.get('error')}")

        except Exception as e:
            logger.error(f"SAD submission failed: {e}", exc_info=True)
            messages.error(request, f"Error: {str(e)}")

    # Load invoice items for the form
    if invoice.sale:
        context['sale_items'] = invoice.sale.items.all()

    return render(request, 'efris/submit_export_sad.html', context)


@login_required
def export_invoice_detail_view(request, invoice_no):
    """
    Display detailed export invoice information and clearance status
    """
    company = request.tenant

    if not company.efris_enabled:
        messages.error(request, "EFRIS is not enabled for your company")
        return redirect('dashboard')

    try:
        # Get local invoice — tenant-scoped via sale__store__company
        from invoices.models import Invoice
        invoice = get_object_or_404(
            Invoice,
            fiscal_document_number=invoice_no,
            sale__store__company=company
        )

        # Query EFRIS for latest invoice details
        client = EnhancedEFRISAPIClient(company)
        invoice_result = client.t108_query_invoice_detail(invoice_no)

        # Query export FDN status
        export_service = create_efris_service(company, 'export', invoice.sale.store if invoice.sale else None)
        status_result = export_service.check_export_clearance_status(invoice_no)

        context = {
            'page_title': f'Export Invoice - {invoice_no}',
            'company': company,
            'invoice': invoice,
            'invoice_no': invoice_no,
            'efris_data': invoice_result.get('invoice') if invoice_result.get('success') else None,
            'clearance_status': status_result.get('documentStatusCode') if status_result.get('success') else None,
            'is_cleared': status_result.get('is_cleared', False) if status_result.get('success') else False,
            'status_codes': {
                '101': 'Under Processing',
                '102': 'Exited/Cleared'
            }
        }

        # Update local status if changed
        if status_result.get('success'):
            new_status = status_result.get('documentStatusCode')
            if invoice.export_status != new_status:
                invoice.export_status = new_status
                update_fields = ['export_status']
                if new_status == '102':
                    invoice.export_cleared_at = timezone.now()
                    update_fields.append('export_cleared_at')
                invoice.save(update_fields=update_fields)

        return render(request, 'efris/export_invoice_detail.html', context)

    except Invoice.DoesNotExist:
        messages.error(request, f"Invoice {invoice_no} not found")
        return redirect('efris:export_invoices_list')
    except Exception as e:
        logger.error(f"Export invoice detail failed: {e}", exc_info=True)
        messages.error(request, f"Error: {str(e)}")
        return redirect('efris:export_invoices_list')


# ============================================================================
# API ENDPOINTS
# ============================================================================

@login_required
@require_http_methods(["POST"])
def check_export_clearance_api(request):
    """
    API endpoint to check export clearance status (T187)
    """
    company = request.tenant

    if not company.efris_enabled:
        return JsonResponse({
            'success': False,
            'error': 'EFRIS is not enabled for your company'
        })

    try:
        invoice_no = request.POST.get('invoice_no')

        if not invoice_no:
            return JsonResponse({
                'success': False,
                'error': 'Invoice number is required'
            })

        export_service = create_efris_service(company, 'export')
        result = export_service.check_export_clearance_status(invoice_no)

        if result.get('success'):
            # Update local invoice status — tenant-scoped
            from invoices.models import Invoice
            try:
                invoice = Invoice.objects.get(
                    fiscal_document_number=invoice_no,
                    sale__store__company=company
                )
                new_status = result.get('documentStatusCode')
                if invoice.export_status != new_status:
                    invoice.export_status = new_status
                    update_fields = ['export_status']
                    if new_status == '102':
                        invoice.export_cleared_at = timezone.now()
                        update_fields.append('export_cleared_at')
                    invoice.save(update_fields=update_fields)
            except Invoice.DoesNotExist:
                pass

        return JsonResponse(result)

    except Exception as e:
        logger.error(f"Export clearance check failed: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
def get_exchange_rate_for_export_api(request):
    """
    Get current exchange rate for export invoice
    """
    company = request.tenant

    if not company.efris_enabled:
        return JsonResponse({
            'success': False,
            'error': 'EFRIS is not enabled for your company'
        })

    try:
        currency = request.GET.get('currency')

        if not currency or currency == 'UGX':
            return JsonResponse({
                'success': True,
                'rate': 1.0,
                'currency': 'UGX'
            })

        client = EnhancedEFRISAPIClient(company)
        result = client.t121_get_exchange_rate(currency=currency)

        return JsonResponse(result)

    except Exception as e:
        logger.error(f"Exchange rate fetch failed: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
@require_http_methods(["POST"])
def bulk_check_export_status(request):
    """
    Bulk check export clearance status for multiple invoices
    """
    company = request.tenant

    if not company.efris_enabled:
        return JsonResponse({
            'success': False,
            'error': 'EFRIS is not enabled for your company'
        })

    try:
        invoice_nos = request.POST.getlist('invoice_nos')

        if not invoice_nos:
            return JsonResponse({
                'success': False,
                'error': 'No invoice numbers provided'
            })

        export_service = create_efris_service(company, 'export')
        results = []

        for invoice_no in invoice_nos:
            try:
                result = export_service.check_export_clearance_status(invoice_no)
                results.append({
                    'invoice_no': invoice_no,
                    'success': result.get('success'),
                    'status': result.get('documentStatusCode'),
                    'is_cleared': result.get('is_cleared', False)
                })

                # Update local status — tenant-scoped
                if result.get('success'):
                    from invoices.models import Invoice
                    try:
                        invoice = Invoice.objects.get(
                            fiscal_document_number=invoice_no,
                            sale__store__company=company
                        )
                        new_status = result.get('documentStatusCode')
                        if invoice.export_status != new_status:
                            invoice.export_status = new_status
                            update_fields = ['export_status']
                            if new_status == '102':
                                invoice.export_cleared_at = timezone.now()
                                update_fields.append('export_cleared_at')
                            invoice.save(update_fields=update_fields)
                    except Invoice.DoesNotExist:
                        pass

            except Exception as e:
                logger.error(f"Status check failed for {invoice_no}: {e}")
                results.append({
                    'invoice_no': invoice_no,
                    'success': False,
                    'error': str(e)
                })

        return JsonResponse({
            'success': True,
            'results': results,
            'total': len(invoice_nos),
            'checked': len(results)
        })

    except Exception as e:
        logger.error(f"Bulk status check failed: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


# ============================================================================
# NEW: PRODUCT EXPORT CONFIGURATION
# ============================================================================

@login_required
def configure_product_for_export_view(request, product_id):
    """
    Configure product with customs UoM for export capability
    """
    company = request.tenant

    if not company.efris_enabled:
        messages.error(request, "EFRIS is not enabled for your company")
        return redirect('dashboard')

    # Get product
    from inventory.models import Product
    from decimal import Decimal
    product = get_object_or_404(Product, id=product_id)

    context = {
        'page_title': f'Configure Export Settings - {product.name}',
        'company': company,
        'product': product,
        # Customs measure units (from T115 exportRateUnit)
        'customs_units': [
            ('NTT', 'NTT - Net Metric Tons'),
            ('KGM', 'KGM - Kilograms'),
            ('LTR', 'LTR - Litres'),
            ('MTR', 'MTR - Meters'),
            ('MTK', 'MTK - Square Meters'),
            ('MTQ', 'MTQ - Cubic Meters'),
            ('PCE', 'PCE - Pieces'),
        ],
        # Piece measure units
        'piece_units': [
            ('101', 'Per Stick'),
            ('102', 'Per Litre'),
            ('103', 'Per Kg'),
            ('106', 'Per 1,000 sticks'),
        ]
    }

    if request.method == 'POST':
        try:
            # ✅ CRITICAL FIX: Update ALL export-related fields

            # Get form data
            hs_code = request.POST.get('hs_code', '').strip()
            customs_measure_unit = request.POST.get('customs_measure_unit', '').strip()
            item_weight = request.POST.get('item_weight', '').strip()
            piece_qty = request.POST.get('piece_qty', '1').strip()
            customs_unit_price = request.POST.get('customs_unit_price', '').strip()
            package_scaled_value = request.POST.get('package_scaled_value_customs', '1').strip()
            customs_scaled_value = request.POST.get('customs_scaled_value', '1').strip()

            # Validate required fields
            if not all([hs_code, customs_measure_unit, item_weight]):
                messages.error(request, 'HS Code, Customs Measure Unit, and Item Weight are required')
                return render(request, 'efris/configure_product_export.html', context)

            # Validate weight
            try:
                weight_value = float(item_weight)
                if weight_value <= 0:
                    messages.error(request, 'Item weight must be greater than 0')
                    return render(request, 'efris/configure_product_export.html', context)
            except (ValueError, TypeError):
                messages.error(request, 'Invalid weight value')
                return render(request, 'efris/configure_product_export.html', context)

            # ✅ UPDATE PRODUCT MODEL - CORE FIELDS (no efris_ prefix)
            product.hs_code = hs_code
            product.hs_name = request.POST.get('hs_name', '')
            product.customs_measure_unit = customs_measure_unit  # ← NO efris_ prefix
            product.item_weight = Decimal(str(weight_value))  # ← CRITICAL: Must save weight!
            product.piece_qty = int(piece_qty) if piece_qty else 1
            product.customs_unit_price = Decimal(
                str(customs_unit_price)) if customs_unit_price else product.selling_price
            product.package_scaled_value_customs = Decimal(
                str(package_scaled_value)) if package_scaled_value else Decimal('1')
            product.customs_scaled_value = Decimal(str(customs_scaled_value)) if customs_scaled_value else Decimal('1')

            # ✅ UPDATE EFRIS-SPECIFIC FIELDS (with efris_ prefix for EFRIS API)
            product.efris_customs_measure_unit = customs_measure_unit
            product.efris_customs_unit_price = Decimal(
                str(customs_unit_price)) if customs_unit_price else product.selling_price
            product.efris_package_scaled_value_customs = Decimal(
                str(package_scaled_value)) if package_scaled_value else Decimal('1')
            product.efris_customs_scaled_value = Decimal(
                str(customs_scaled_value)) if customs_scaled_value else Decimal('1')
            product.is_export_product = True

            # Optional: piece measure unit
            piece_unit = request.POST.get('piece_measure_unit', '').strip()
            if piece_unit:
                product.piece_measure_unit = piece_unit  # Core field
                product.efris_piece_measure_unit = piece_unit  # EFRIS field
                product.efris_has_piece_unit = True

            # ✅ SAVE TO DATABASE FIRST (before EFRIS)
            product.save()

            logger.info(
                f"✅ Product {product.id} saved locally: "
                f"weight={product.item_weight}kg, HS={product.hs_code}, "
                f"customs_unit={product.customs_measure_unit}"
            )

            # ✅ THEN sync to EFRIS (T130)
            try:
                from efris.services import EnhancedEFRISAPIClient

                with EnhancedEFRISAPIClient(company) as client:
                    result = client.register_product_with_efris(product)

                if result.get('success'):
                    messages.success(
                        request,
                        f"✅ Product '{product.name}' configured for export and synced to EFRIS!"
                    )
                else:
                    # Product is saved locally even if EFRIS fails
                    messages.warning(
                        request,
                        f"⚠️ Product saved locally but EFRIS sync failed: {result.get('error')}\n"
                        f"You can retry EFRIS sync later from product management."
                    )
            except Exception as efris_error:
                logger.error(f"EFRIS sync error: {efris_error}", exc_info=True)
                messages.warning(
                    request,
                    f"⚠️ Product saved locally but EFRIS sync failed: {str(efris_error)}\n"
                    f"You can retry EFRIS sync later."
                )

            # Redirect to product detail or back to sales page
            next_url = request.GET.get('next')
            if next_url:
                return redirect(next_url)
            return redirect('inventory:product_detail', pk=product.id)

        except Exception as e:
            logger.error(f"Export configuration failed: {e}", exc_info=True)
            messages.error(request, f"Error: {str(e)}")

    return render(request, 'efris/configure_product_export.html', context)

# ============================================================================
# UPDATED: CREATE EXPORT INVOICE (WITH VALIDATION)
# ============================================================================

@login_required
def create_export_invoice_view(request):
    """
    CORRECTED: Create export invoice with product validation
    """
    company = request.tenant

    if not company.efris_enabled:
        messages.error(request, "EFRIS is not enabled for your company")
        return redirect('dashboard')

    context = {
        'page_title': 'Create Export Invoice',
        'company': company,
        'delivery_terms': [
            ('FOB', 'FOB - Free On Board'),
            ('CIF', 'CIF - Cost, Insurance and Freight'),
            ('CFR', 'CFR - Cost and Freight'),
            ('EXW', 'EXW - Ex Works'),
            ('DDP', 'DDP - Delivered Duty Paid'),
            ('DAP', 'DAP - Delivered At Place'),
            ('CPT', 'CPT - Carriage Paid To'),
            ('CIP', 'CIP - Carriage and Insurance Paid To'),
            ('FAS', 'FAS - Free Alongside Ship'),
            ('FCA', 'FCA - Free Carrier'),
            ('DPU', 'DPU - Delivered at Place Unloaded'),
        ],
        'currencies': [
            ('USD', 'US Dollar'),
            ('EUR', 'Euro'),
            ('GBP', 'British Pound'),
            ('KES', 'Kenyan Shilling'),
            ('TZS', 'Tanzanian Shilling'),
            ('RWF', 'Rwandan Franc'),
        ],
        'piece_units': [
            ('101', 'Per Stick'),
            ('102', 'Per Litre'),
            ('103', 'Per Kg'),
        ]
    }

    if request.method == 'POST':
        try:
            # Get sale/invoice to export
            sale_id = request.POST.get('sale_id')

            # Get export-specific data
            delivery_terms = request.POST.get('delivery_terms')
            total_weight = float(request.POST.get('total_weight'))
            buyer_country = request.POST.get('buyer_country')
            buyer_passport = request.POST.get('buyer_passport', '')
            foreign_currency = request.POST.get('foreign_currency')
            exchange_rate = float(
                request.POST.get('exchange_rate')) if foreign_currency and foreign_currency != 'UGX' else None

            # Get HS codes
            hs_codes_json = request.POST.get('hs_codes')
            hs_codes = json.loads(hs_codes_json) if hs_codes_json else []

            # NEW: Get piece quantities and measure units
            piece_quantities_json = request.POST.get('piece_quantities')
            piece_quantities = json.loads(piece_quantities_json) if piece_quantities_json else []

            piece_units_json = request.POST.get('piece_measure_units')
            piece_units = json.loads(piece_units_json) if piece_units_json else []

            # Validate required fields
            if not all([delivery_terms, total_weight, buyer_country]):
                messages.error(request, "Delivery terms, total weight, and buyer country are mandatory")
                return redirect('efris:create_export_invoice')

            if not hs_codes:
                messages.error(request, "HS codes are mandatory for all export items")
                return redirect('efris:create_export_invoice')

            # Get the sale
            from sales.models import Sale
            sale = get_object_or_404(Sale, id=sale_id, sale__store__company=company)

            # NEW: Validate products are export-ready
            non_export_products = []
            for item in sale.items.all():
                if not hasattr(item.product, 'is_export_ready') or not item.product.is_export_ready:
                    non_export_products.append(item.product.name)

            if non_export_products:
                messages.error(
                    request,
                    f"The following products are not configured for export: {', '.join(non_export_products)}. "
                    f"Please configure them first."
                )
                return redirect('efris:create_export_invoice')

            # Create export service
            export_service = create_efris_service(company, 'export', sale.store)

            # Fiscalize export invoice (CORRECTED version with piece data)
            result = export_service.fiscalize_export_sale(
                sale_or_invoice=sale,
                delivery_terms=delivery_terms,
                hs_codes=hs_codes,
                total_weight=total_weight,
                buyer_country=buyer_country,
                buyer_passport=buyer_passport,
                foreign_currency=foreign_currency,
                exchange_rate=exchange_rate,
                piece_quantities=piece_quantities,  # NEW
                piece_measure_units=piece_units,  # NEW
                user=request.user
            )

            if result.get('success'):
                invoice_no = result['data']['invoice_no']
                fiscal_code = result['data'].get('fiscal_code', '')

                # Update invoice with export data
                from invoices.models import Invoice
                invoice = Invoice.objects.filter(sale=sale).first()

                if invoice:
                    invoice.fiscal_document_number = invoice_no
                    invoice.fiscal_number = invoice_no
                    invoice.verification_code = fiscal_code
                    invoice.is_fiscalized = True
                    invoice.fiscalization_time = timezone.now()
                    invoice.export_status = '101'  # Pending customs clearance
                    invoice.export_delivery_terms = delivery_terms
                    invoice.export_total_weight = total_weight
                    invoice.save()

                messages.success(
                    request,
                    f"✓ Export invoice created successfully! Invoice No: {invoice_no}"
                )

                # Redirect to SAD submission
                return redirect('efris:submit_export_sad', invoice_no=invoice_no)
            else:
                messages.error(request, f"Export invoice creation failed: {result.get('error')}")

        except Exception as e:
            logger.error(f"Export invoice creation failed: {e}", exc_info=True)
            messages.error(request, f"Error: {str(e)}")

    # Load pending sales for export (ONLY export-ready sales)
    try:
        from sales.models import Sale

        # Get sales with all items export-ready
        all_sales = Sale.objects.filter(
            sale__store__company=company,
            status__in=['COMPLETED', 'PAID'],
            is_fiscalized=False
        ).select_related('customer', 'store').prefetch_related('items__product')

        # Filter for export-ready sales
        pending_sales = []
        for sale in all_sales[:100]:  # Limit to 100 for performance
            all_items_ready = all(
                hasattr(item.product, 'is_export_ready') and item.product.is_export_ready
                for item in sale.items.all()
            )
            if all_items_ready:
                pending_sales.append(sale)

        context['pending_sales'] = pending_sales
        context['non_export_count'] = all_sales.count() - len(pending_sales)
    except Exception as e:
        logger.error(f"Failed to load pending sales: {e}")
        context['pending_sales'] = []
        context['non_export_count'] = 0

    return render(request, 'efris/create_export_invoice.html', context)


# ============================================================================
# UPDATED: SUBMIT SAD (WITH PIECE DATA)
# ============================================================================

@login_required
def submit_export_sad_view(request, invoice_no):
    """
    CORRECTED: Submit customs SAD declaration with all mandatory fields
    """
    company = request.tenant

    if not company.efris_enabled:
        messages.error(request, "EFRIS is not enabled for your company")
        return redirect('dashboard')

    # Get the invoice
    from invoices.models import Invoice
    try:
        invoice = Invoice.objects.get(
            fiscal_document_number=invoice_no,
        )
    except Invoice.DoesNotExist:
        messages.error(request, f"Invoice {invoice_no} not found")
        return redirect('efris:export_invoices_list')

    context = {
        'page_title': f'Submit Customs SAD - {invoice_no}',
        'company': company,
        'invoice': invoice,
        'invoice_no': invoice_no
    }

    if request.method == 'POST':
        try:
            # Get SAD submission data
            sad_number = request.POST.get('sad_number')
            exit_office = request.POST.get('exit_office')
            exit_officer = request.POST.get('exit_officer')
            exit_date = request.POST.get('exit_date')
            exit_time = request.POST.get('exit_time', '00:00:00')

            # Get exported items data
            exported_items = []
            item_count = int(request.POST.get('item_count', 0))

            for i in range(item_count):
                hs_code = request.POST.get(f'hs_code_{i}')
                item_id = request.POST.get(f'item_id_{i}')
                quantity = request.POST.get(f'quantity_{i}')

                if hs_code and item_id and quantity:
                    exported_items.append({
                        'hsCode': hs_code,
                        'invoiceItemId': item_id,
                        'exportedQuantity': quantity
                    })

            # Validate
            if not sad_number or len(sad_number) != 20:
                messages.error(request, "SAD number must be exactly 20 digits")
                return redirect('efris:submit_export_sad', invoice_no=invoice_no)

            if not all([exit_office, exit_officer, exit_date]):
                messages.error(request, "All exit information fields are required")
                return redirect('efris:submit_export_sad', invoice_no=invoice_no)

            if not exported_items:
                messages.error(request, "At least one exported item is required")
                return redirect('efris:submit_export_sad', invoice_no=invoice_no)

            # Combine date and time
            exit_datetime_str = f"{exit_date} {exit_time}"
            exit_datetime = datetime.strptime(exit_datetime_str, '%Y-%m-%d %H:%M:%S')

            # Submit SAD
            export_service = create_efris_service(company, 'export', invoice.sale.store if invoice.sale else None)

            result = export_service.submit_customs_declaration(
                invoice_no=invoice_no,
                sad_number=sad_number,
                exit_office=exit_office,
                exit_officer=exit_officer,
                exit_datetime=exit_datetime,
                exported_items=exported_items
            )

            if result.get('success'):
                # Update invoice
                invoice.export_sad_number = sad_number
                invoice.export_sad_submitted_at = timezone.now()
                invoice.export_status = '101'  # Under processing
                invoice.save()

                messages.success(
                    request,
                    f"✓ Customs SAD declaration submitted successfully! SAD No: {sad_number}"
                )
                return redirect('efris:export_invoice_detail', invoice_no=invoice_no)
            else:
                messages.error(request, f"SAD submission failed: {result.get('error')}")

        except Exception as e:
            logger.error(f"SAD submission failed: {e}", exc_info=True)
            messages.error(request, f"Error: {str(e)}")

    # Load invoice items for the form
    if invoice.sale:
        context['sale_items'] = invoice.sale.items.all()

    return render(request, 'efris/submit_export_sad.html', context)


# ============================================================================
# API: Get Sale Items for Export Validation
# ============================================================================

@login_required
def get_sale_items_export_api(request):
    """
    NEW: API to get sale items with export readiness status
    """
    company = request.tenant

    if not company.efris_enabled:
        return JsonResponse({
            'success': False,
            'error': 'EFRIS is not enabled for your company'
        })

    try:
        sale_id = request.GET.get('sale_id')

        if not sale_id:
            return JsonResponse({
                'success': False,
                'error': 'Sale ID is required'
            })

        from sales.models import Sale
        sale = get_object_or_404(Sale, id=sale_id, sale__store__company=company)

        # Get items with export readiness
        items = []
        all_ready = True

        for item in sale.items.all():
            is_ready = hasattr(item.product, 'is_export_ready') and item.product.is_export_ready
            all_ready = all_ready and is_ready

            items.append({
                'id': item.id,
                'product_name': item.product.name,
                'quantity': float(item.quantity),
                'is_export_ready': is_ready,
                'customs_unit': item.product.customs_measure_unit if hasattr(item.product,
                                                                             'customs_measure_unit') else None,
                'piece_unit': item.product.piece_measure_unit if hasattr(item.product, 'piece_measure_unit') else '101'
            })

        return JsonResponse({
            'success': True,
            'items': items,
            'all_ready': all_ready,
            'total_items': len(items)
        })

    except Exception as e:
        logger.error(f"Get sale items failed: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        })