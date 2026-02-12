from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator
from django.utils import timezone
from django.db import transaction
from datetime import datetime, timedelta
import json
import structlog
from django.conf import settings
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



@login_required
def exception_logs_view(request):
    """
    T132 - Exception Logs Management
    Display and upload exception logs
    """
    company = request.tenant

    if not company.efris_enabled:
        messages.error(request, "EFRIS is not enabled for your company")
        return redirect('dashboard')

    context = {
        'page_title': 'EFRIS Exception Logs',
        'company': company
    }

    try:
        from efris.models import EFRISExceptionLog

        # Get filter parameters
        uploaded = request.GET.get('uploaded')
        interruption_type = request.GET.get('type')
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')

        # Build queryset
        logs = EFRISExceptionLog.objects.filter(company=company)

        if uploaded is not None:
            logs = logs.filter(uploaded=(uploaded == '1'))

        if interruption_type:
            logs = logs.filter(interruption_type_code=interruption_type)

        if start_date:
            logs = logs.filter(interruption_time__date__gte=start_date)

        if end_date:
            logs = logs.filter(interruption_time__date__lte=end_date)

        logs = logs.order_by('-interruption_time')

        # Paginate
        paginator = Paginator(logs, 50)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)

        context['logs'] = page_obj
        context['pending_count'] = EFRISExceptionLog.objects.filter(
            company=company,
            uploaded=False
        ).count()

    except Exception as e:
        logger.error(f"Failed to load exception logs: {e}", exc_info=True)
        messages.error(request, f"Error: {str(e)}")

    return render(request, 'efris/exception_logs.html', context)

@login_required
@require_http_methods(["POST"])
def upload_exception_logs(request):
    """Upload pending exception logs to EFRIS"""
    company = request.tenant

    if not company.efris_enabled:
        return JsonResponse({
            'success': False,
            'error': 'EFRIS is not enabled for your company'
        })

    try:
        client = EnhancedEFRISAPIClient(company)
        result = client.upload_pending_exception_logs_on_login()

        if result.get('success'):
            messages.success(
                request,
                f"Successfully uploaded {result.get('logs_count', 0)} exception logs"
            )
        else:
            messages.error(request, f"Upload failed: {result.get('error')}")

        return JsonResponse(result)

    except Exception as e:
        logger.error(f"Exception log upload failed: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
def system_upgrade_view(request):
    """
    T133 & T135 - System Upgrade Management
    Check for updates and download upgrade files
    """
    company = request.tenant

    if not company.efris_enabled:
        messages.error(request, "EFRIS is not enabled for your company")
        return redirect('dashboard')

    context = {
        'page_title': 'EFRIS System Upgrade',
        'company': company
    }

    try:
        client = EnhancedEFRISAPIClient(company)

        # Get current TCS version (from settings or config)
        current_version = getattr(settings, 'EFRIS_TCS_VERSION', '1')

        # Check for latest version
        version_result = client.t135_get_latest_tcs_version()

        if version_result.get('success'):
            latest_version = version_result.get('latest_version', current_version)
            context['current_version'] = current_version
            context['latest_version'] = latest_version
            context['update_available'] = int(latest_version) > int(current_version)
        else:
            messages.warning(request, f"Could not check for updates: {version_result.get('error')}")

    except Exception as e:
        logger.error(f"System upgrade check failed: {e}", exc_info=True)
        messages.error(request, f"Error: {str(e)}")

    return render(request, 'efris/system_upgrade.html', context)


@login_required
@require_http_methods(["POST"])
def download_upgrade_files(request):
    """Download TCS upgrade files"""
    company = request.tenant

    if not company.efris_enabled:
        return JsonResponse({
            'success': False,
            'error': 'EFRIS is not enabled for your company'
        })

    try:
        tcs_version = request.POST.get('tcs_version')
        os_type = request.POST.get('os_type', '1')

        if not tcs_version:
            return JsonResponse({
                'success': False,
                'error': 'TCS version is required'
            })

        client = EnhancedEFRISAPIClient(company)
        result = client.t133_download_tcs_upgrade_files(tcs_version, os_type)

        return JsonResponse(result)

    except Exception as e:
        logger.error(f"Upgrade file download failed: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
def commodity_category_updates_view(request):
    """
    T134 - Commodity Category Incremental Updates
    Check and apply category updates
    """
    company = request.tenant

    if not company.efris_enabled:
        messages.error(request, "EFRIS is not enabled for your company")
        return redirect('dashboard')

    context = {
        'page_title': 'Commodity Category Updates',
        'company': company
    }

    # Handle update request
    if request.method == 'POST':
        try:
            current_version = request.POST.get('current_version', '1.0')

            client = EnhancedEFRISAPIClient(company)
            result = client.t134_get_commodity_category_incremental_update(current_version)

            if result.get('success'):
                categories = result.get('categories', [])

                if categories:
                    # Process updates
                    updated_count = 0

                    for category in categories:
                        try:
                            # Update or create category
                            from company.models import EFRISCommodityCategory

                            EFRISCommodityCategory.objects.update_or_create(
                                commodity_category_code=category.get('commodityCategoryCode'),
                                defaults={
                                    'commodity_category_name': category.get('commodityCategoryName', ''),
                                    'parent_code': category.get('parentCode', ''),
                                    'commodity_category_level': category.get('commodityCategoryLevel', '1'),
                                    'rate': category.get('rate', '0'),
                                    'is_leaf_node': category.get('isLeafNode', '102'),
                                    'service_mark': category.get('serviceMark', '102'),
                                    'is_zero_rate': category.get('isZeroRate', '102'),
                                    'is_exempt': category.get('isExempt', '102'),
                                    'enable_status_code': category.get('enableStatusCode', '1'),
                                    'exclusion': category.get('exclusion', '2'),
                                    'excisable': category.get('excisable', '102'),
                                    'vat_out_scope_code': category.get('vatOutScopeCode', '102'),
                                    'last_synced': timezone.now()
                                }
                            )
                            updated_count += 1
                        except Exception as cat_error:
                            logger.error(f"Failed to update category: {cat_error}")

                    messages.success(
                        request,
                        f"Successfully updated {updated_count} commodity categories"
                    )
                else:
                    messages.info(request, "No updates available. Your categories are up to date.")
            else:
                messages.error(request, f"Update failed: {result.get('error')}")

        except Exception as e:
            logger.error(f"Category update failed: {e}", exc_info=True)
            messages.error(request, f"Error: {str(e)}")

    # Get current category stats
    try:
        from company.models import EFRISCommodityCategory

        total_categories = EFRISCommodityCategory.objects.count()
        context['total_categories'] = total_categories
        context['last_sync'] = EFRISCommodityCategory.objects.order_by('-last_synced').first()
    except Exception:
        context['total_categories'] = 0

    return render(request, 'efris/commodity_category_updates.html', context)


@login_required
def certificate_upload_view(request):
    """
    T136 - Certificate Public Key Upload
    Upload certificate files
    """
    company = request.tenant

    if not company.efris_enabled:
        messages.error(request, "EFRIS is not enabled for your company")
        return redirect('dashboard')

    context = {
        'page_title': 'Certificate Upload',
        'company': company
    }

    if request.method == 'POST':
        try:
            certificate_file = request.FILES.get('certificate_file')
            manual_verify_string = request.POST.get('verify_string', '')

            if not certificate_file:
                messages.error(request, "Please select a certificate file")
                return redirect('efris:certificate_upload')

            # Validate file extension
            if not (certificate_file.name.endswith('.crt') or certificate_file.name.endswith('.cer')):
                messages.error(request, "File must be .crt or .cer format")
                return redirect('efris:certificate_upload')

            # Check file size (max 10MB)
            if certificate_file.size > 10 * 1024 * 1024:
                messages.error(request, "File size must be less than 10MB")
                return redirect('efris:certificate_upload')

            # Read and encode file
            import base64
            file_content = base64.b64encode(certificate_file.read()).decode('utf-8')

            # Upload to EFRIS
            client = EnhancedEFRISAPIClient(company)

            result = client.t136_upload_certificate_public_key(
                file_name=certificate_file.name,
                file_content=file_content
            )

            if result.get('success'):
                messages.success(request, f"Certificate {certificate_file.name} uploaded successfully")
                # Log the success
                logger.info(f"Certificate uploaded: {certificate_file.name}, size: {certificate_file.size} bytes")
            else:
                error_msg = result.get('error', 'Unknown error')
                error_code = result.get('error_code')

                if error_code == '2096':
                    messages.error(request, f"Upload failed: VerifyString error. Please check TIN configuration.")
                else:
                    messages.error(request, f"Upload failed: {error_msg}")

                # Add debug info for troubleshooting
                logger.error(f"Certificate upload failed: {error_msg} (code: {error_code})")

        except Exception as e:
            logger.error(f"Certificate upload failed: {e}", exc_info=True)
            messages.error(request, f"Error: {str(e)}")

    return render(request, 'efris/certificate_upload.html', context)

@login_required
def taxpayer_exemption_check_view(request):
    """
    T137 - Check Exempt/Deemed Taxpayer Status
    Check if a taxpayer is tax exempt or deemed
    """
    company = request.tenant

    if not company.efris_enabled:
        messages.error(request, "EFRIS is not enabled for your company")
        return redirect('dashboard')

    context = {
        'page_title': 'Taxpayer Exemption Check',
        'company': company
    }

    if request.method == 'POST':
        try:
            tin = request.POST.get('tin')
            commodity_codes = request.POST.get('commodity_codes', '')

            if not tin:
                messages.error(request, "TIN is required")
                return redirect('efris:taxpayer_exemption_check')

            client = EnhancedEFRISAPIClient(company)
            result = client.t137_check_exempt_deemed_taxpayer(
                tin=tin,
                commodity_category_codes=commodity_codes if commodity_codes else None
            )

            if result.get('success'):
                context['check_result'] = result
                context['searched_tin'] = tin
            else:
                messages.error(request, f"Check failed: {result.get('error')}")

        except Exception as e:
            logger.error(f"Exemption check failed: {e}", exc_info=True)
            messages.error(request, f"Error: {str(e)}")

    return render(request, 'efris/taxpayer_exemption_check.html', context)


@login_required
def branches_list_view(request):
    """
    T138 - All Branches List
    Display all branches for the company
    """
    company = request.tenant

    if not company.efris_enabled:
        messages.error(request, "EFRIS is not enabled for your company")
        return redirect('dashboard')

    context = {
        'page_title': 'EFRIS Branches',
        'company': company
    }

    try:
        client = EnhancedEFRISAPIClient(company)
        result = client.t138_get_all_branches()

        if result.get('success'):
            branches = result.get('branches', [])
            context['branches'] = branches
            context['total_branches'] = len(branches)
        else:
            messages.error(request, f"Failed to load branches: {result.get('error')}")

    except Exception as e:
        logger.error(f"Branches query failed: {e}", exc_info=True)
        messages.error(request, f"Error: {str(e)}")

    return render(request, 'efris/branches_list.html', context)


# ============================================================================
# API ENDPOINTS
# ============================================================================

@login_required
def check_taxpayer_status_api(request):
    """API endpoint for checking taxpayer status"""
    company = request.tenant

    if not company.efris_enabled:
        return JsonResponse({
            'success': False,
            'error': 'EFRIS is not enabled for your company'
        })

    try:
        tin = request.GET.get('tin')

        if not tin:
            return JsonResponse({
                'success': False,
                'error': 'TIN is required'
            })

        client = EnhancedEFRISAPIClient(company)
        result = client.t137_check_exempt_deemed_taxpayer(tin)

        return JsonResponse(result)

    except Exception as e:
        logger.error(f"API check failed: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
def get_branches_api(request):
    """API endpoint for getting branches"""
    company = request.tenant

    if not company.efris_enabled:
        return JsonResponse({
            'success': False,
            'error': 'EFRIS is not enabled for your company'
        })

    try:
        client = EnhancedEFRISAPIClient(company)
        result = client.t138_get_all_branches()

        return JsonResponse(result)

    except Exception as e:
        logger.error(f"API query failed: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@login_required
def invoice_search_view(request):
    company = request.tenant

    if not company.efris_enabled:
        messages.error(request, "EFRIS is not enabled for your company")
        return redirect('dashboard')

    context = {
        'page_title': 'EFRIS Invoice Search',
        'company': company
    }

    # Handle search request
    if request.method == 'POST' or request.GET.get('search'):
        try:
            # Get search parameters
            search_params = {
                'invoice_no': request.POST.get('invoice_number') or request.GET.get('invoice_number'),
                'buyer_tin': request.POST.get('buyer_tin') or request.GET.get('buyer_tin'),
                'buyer_legal_name': request.POST.get('buyer_legal_name') or request.GET.get('buyer_legal_name'),
                'invoice_type': request.POST.get('invoice_type') or request.GET.get('invoice_type'),
                'invoice_kind': request.POST.get('invoice_kind') or request.GET.get('invoice_kind'),
                'start_date': request.POST.get('start_date') or request.GET.get('start_date'),
                'end_date': request.POST.get('end_date') or request.GET.get('end_date'),
                'is_invalid': request.POST.get('is_invalid') or request.GET.get('is_invalid'),
                'is_refund': request.POST.get('is_refund') or request.GET.get('is_refund'),
                'reference_no': request.POST.get('reference_no') or request.GET.get('reference_no'),
                'page_no': int(request.GET.get('page', 1))
            }

            # Remove None values
            search_params = {k: v for k, v in search_params.items() if v}

            client = EnhancedEFRISAPIClient(company)
            result = client.t106_query_invoices(**search_params)

            if result.get('success'):
                context['invoices'] = result.get('invoices', [])
                context['pagination'] = result.get('pagination', {})
                context['search_performed'] = True
                context['search_params'] = search_params
            else:
                messages.error(request, f"Search failed: {result.get('error')}")

        except Exception as e:
            logger.error(f"Invoice search failed: {e}", exc_info=True)
            messages.error(request, f"Search error: {str(e)}")

    return render(request, 'efris/invoice_search.html', context)


@login_required
def invoice_detail_view(request, invoice_no):
    """
    Display detailed invoice information from EFRIS via T108
    """
    company = request.tenant

    if not company.efris_enabled:
        messages.error(request, "EFRIS is not enabled for your company")
        return redirect('dashboard')

    try:
        with EnhancedEFRISAPIClient(company) as client:
            # Query invoice details from EFRIS
            result = client.t108_query_invoice_detail(invoice_no)

            if result.get('success'):
                invoice_data = result.get('invoice')

                if not invoice_data:
                    messages.error(request, f"Invoice {invoice_no} not found in EFRIS")
                    return redirect('efris:normal_invoices')

                context = {
                    'page_title': f'Invoice Details - {invoice_no}',
                    'invoice': invoice_data,
                    'invoice_no': invoice_no,
                    'company': company
                }
                return render(request, 'efris/invoice_detail.html', context)
            else:
                error_msg = result.get('error', 'Unknown error')
                messages.error(request, f"Failed to load invoice: {error_msg}")
                return redirect('efris:normal_invoices')

    except Exception as e:
        logger.error(f"Invoice detail view failed for {invoice_no}: {e}", exc_info=True)
        messages.error(request, f"Error loading invoice: {str(e)}")
        return redirect('efris:normal_invoices')

@login_required
def normal_invoices_view(request):
    """
    T107 - Normal Invoices View
    Display invoices eligible for credit/debit notes
    Also handles direct credit note creation from this page
    """
    company = request.tenant

    if not company.efris_enabled:
        messages.error(request, "EFRIS is not enabled for your company")
        return redirect('dashboard')

    # Handle POST - Quick credit note creation
    if request.method == 'POST':
        invoice_no = request.POST.get('invoice_no')
        invoice_id = request.POST.get('invoice_id')
        reason_code = request.POST.get('reason_code', '102')  # Default: Cancellation
        reason = request.POST.get('reason', '')

        try:
            with EnhancedEFRISAPIClient(company) as client:
                # Build full credit note from invoice
                build_result = client.build_credit_note_from_invoice(
                    original_invoice_no=invoice_no,
                    reason_code=reason_code,
                    reason=reason if reason_code == '105' else None,
                    contact_name=request.user.get_full_name() or request.user.username,
                    contact_email=request.user.email,
                    remarks=f"Credit note for invoice {invoice_no}"
                )

                if not build_result.get('success'):
                    messages.error(request, f"Failed to build credit note: {build_result.get('error')}")
                    return redirect('efris:normal_invoices')

                # Apply credit note
                credit_note_data = build_result['credit_note_data']
                result = client.t110_apply_credit_note(credit_note_data)

                if result.get('success'):
                    # Save credit note application record
                    try:
                        from efris.models import CreditNoteApplication
                        CreditNoteApplication.objects.create(
                            company=company,
                            original_invoice_no=invoice_no,
                            original_invoice_id=invoice_id,
                            reason_code=reason_code,
                            reason=reason,
                            reference_no=result.get('reference_no'),
                            status='PENDING',
                            application_data=credit_note_data,
                            response_data=result.get('data', {})
                        )
                    except Exception as db_error:
                        logger.warning(f"Failed to save credit note record: {db_error}")

                    messages.success(
                        request,
                        f"✓ Credit note application submitted successfully! "
                        f"Reference No: {result.get('reference_no')}"
                    )
                    return redirect('efris:normal_invoices')
                else:
                    messages.error(request, f"Application failed: {result.get('error')}")

        except Exception as e:
            logger.error(f"Credit note application error: {e}", exc_info=True)
            messages.error(request, f"Error: {str(e)}")

        return redirect('efris:normal_invoices')

    # GET request - Display invoices
    context = {
        'page_title': 'Normal Invoices (Eligible for Credit/Debit Notes)',
        'company': company,
        'reason_codes': [
            ('101', 'Return of products due to expiry or damage'),
            ('102', 'Cancellation of the purchase'),
            ('103', 'Invoice amount wrongly stated'),
            ('104', 'Partial or complete waive off'),
            ('105', 'Others (specify reason)')
        ]
    }

    try:
        # Get filter parameters
        page_no = int(request.GET.get('page', 1))
        buyer_tin = request.GET.get('buyer_tin')
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')

        client = EnhancedEFRISAPIClient(company)
        result = client.t107_query_normal_invoices(
            buyer_tin=buyer_tin,
            start_date=start_date,
            end_date=end_date,
            page_no=page_no,
            page_size=20
        )

        if result.get('success'):
            context['invoices'] = result.get('invoices', [])
            context['pagination'] = result.get('pagination', {})
        else:
            messages.error(request, f"Failed to load invoices: {result.get('error')}")

    except Exception as e:
        logger.error(f"Normal invoices query failed: {e}", exc_info=True)
        messages.error(request, f"Error: {str(e)}")

    return render(request, 'efris/normal_invoices.html', context)


# ============================================================================
# CREDIT/DEBIT NOTE APPLICATION VIEWS
# ============================================================================


class CreditNoteStatus:
    """Status codes used in T111/T112 Query APIs"""
    PENDING = '101'
    APPROVED = '102'
    REJECTED = '103'
    CANCELLED = '104'
    PROCESSED = '105'

    STATUS_DISPLAY = {
        '101': 'Pending/Submitted',
        '102': 'Approved',
        '103': 'Rejected',
        '104': 'Voided/Cancelled',
        '105': 'Processed',
    }

    @classmethod
    def get_display(cls, status_code):
        return cls.STATUS_DISPLAY.get(status_code, f'Unknown ({status_code})')

    @classmethod
    def can_approve(cls, status_code):
        """Check if application can be approved/rejected"""
        return status_code == cls.PENDING


class ApprovalAction:
    """Action codes used in T113 Approval API"""
    APPROVE = '101'  # This means "APPROVE" in T113
    REJECT = '103'  # This means "REJECT" in T113

    ACTION_DISPLAY = {
        '101': 'Approved',
        '103': 'Rejected',
    }


@login_required
def credit_note_applications_view(request):
    """
    T111 - Credit/Debit Note Applications List
    Display all credit and debit note applications
    """
    company = request.tenant

    if not company.efris_enabled:
        messages.error(request, "EFRIS is not enabled for your company")
        return redirect('dashboard')

    context = {
        'page_title': 'Credit/Debit Note Applications',
        'company': company,
        'status_class': CreditNoteStatus,  # Pass the class to template
    }

    try:
        # Get filter parameters
        page_no = int(request.GET.get('page', 1))
        approve_status = request.GET.get('approve_status')
        category_code = request.GET.get('category_code')
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        query_type = request.GET.get('query_type', '1')

        # Validate query_type
        if query_type not in ['1', '2', '3']:
            query_type = '1'

        client = EnhancedEFRISAPIClient(company)
        result = client.t111_query_credit_note_applications(
            approve_status=approve_status,
            invoice_apply_category_code=category_code,
            start_date=start_date,
            end_date=end_date,
            query_type=query_type,
            page_no=page_no,
            page_size=20
        )

        if result.get('success'):
            applications = result.get('applications', [])

            # Map reason codes to descriptions
            reason_codes = {
                '101': 'Return of products due to expiry or damage',
                '102': 'Cancellation of the purchase',
                '103': 'Invoice amount wrongly stated',
                '104': 'Partial or complete waive off',
                '105': 'Others',
            }

            for app in applications:
                # Handle both camelCase and snake_case field names
                app_status = app.get('approveStatus') or app.get('approve_status')
                app['approve_status'] = app_status

                # FIX: Correct status display mapping per EFRIS docs
                status_map = {
                    '101': 'Approved',  # Changed from Pending
                    '102': 'Submitted',  # Changed from Approved (this is actually Pending)
                    '103': 'Rejected',
                    '104': 'Voided',
                    # Add if they exist in responses
                    '105': 'Processed',
                }
                app['status_display'] = status_map.get(app_status, f'Unknown ({app_status})')
                app['can_approve'] = (app_status == '102')

                # Map reason code
                reason_code = app.get('invoiceApplyCategoryCode') or app.get('invoice_apply_category_code')
                if reason_code in reason_codes:
                    app['reason_description'] = reason_codes[reason_code]
                else:
                    app['reason_description'] = f"Code: {reason_code}"

            context['applications'] = applications
            context['pagination'] = result.get('pagination', {})
            context['filters'] = {
                'approve_status': approve_status,
                'category_code': category_code,
                'start_date': start_date,
                'end_date': end_date,
                'query_type': query_type
            }

            # Status options for filter
            context['status_options'] = [
                ('', 'All Status'),
                (CreditNoteStatus.PENDING, CreditNoteStatus.STATUS_DISPLAY[CreditNoteStatus.PENDING]),
                (CreditNoteStatus.APPROVED, CreditNoteStatus.STATUS_DISPLAY[CreditNoteStatus.APPROVED]),
                (CreditNoteStatus.REJECTED, CreditNoteStatus.STATUS_DISPLAY[CreditNoteStatus.REJECTED]),
                (CreditNoteStatus.CANCELLED, CreditNoteStatus.STATUS_DISPLAY[CreditNoteStatus.CANCELLED]),
                (CreditNoteStatus.PROCESSED, CreditNoteStatus.STATUS_DISPLAY[CreditNoteStatus.PROCESSED]),
            ]

        else:
            messages.error(request, f"Failed to load applications: {result.get('error')}")

    except Exception as e:
        logger.error(f"Applications query failed: {e}", exc_info=True)
        messages.error(request, f"Error: {str(e)}")

    return render(request, 'efris/credit_note_applications.html', context)


@login_required
def credit_note_application_detail_view(request, application_id):
    """
    T112/T118 - Credit Note Application Detail
    Display detailed information about a credit note application
    """
    company = request.tenant

    if not company.efris_enabled:
        messages.error(request, "EFRIS is not enabled for your company")
        return redirect('dashboard')

    try:
        client = EnhancedEFRISAPIClient(company)

        # Get basic application info (T112)
        basic_result = client.t112_query_credit_note_application_detail(application_id)

        if not basic_result.get('success'):
            error = basic_result.get('error') or "Unknown error"
            messages.error(request, f"Failed to load application: {error}")
            return redirect('efris:credit_note_applications')

        application_data = basic_result.get('application_detail', {})

        # ✅ EFRIS status codes (from T111 docs):
        # 101 = Approved
        # 102 = Submitted (Pending approval)
        # 103 = Rejected
        # 104 = Voided
        EFRIS_STATUS_MAP = {
            '101': 'Approved',
            '102': 'Submitted',
            '103': 'Rejected',
            '104': 'Voided',
        }

        # ✅ Read status - EFRIS may return as approveStatus or approveStatusCode
        approve_status = (
            application_data.get('approveStatus') or
            application_data.get('approveStatusCode') or
            ''
        )
        approve_status = str(approve_status).strip()

        # ✅ can_approve only when Submitted (102) - pending approval
        can_approve = approve_status == '102'

        # ✅ Reason code - T112 returns selectRefundReasonCode
        reason_code = str(
            application_data.get('selectRefundReasonCode') or
            application_data.get('reasonCode') or
            application_data.get('invoiceApplyCategoryCode') or
            ''
        )

        reason_codes = {
            '101': 'Return of products due to expiry or damage',
            '102': 'Cancellation of the purchase',
            '103': 'Invoice amount wrongly stated',
            '104': 'Partial or complete waive off',
            '105': 'Others',
        }

        basic_info = {
            'application_id': application_data.get('id') or application_id,
            'original_invoice_no': (
                application_data.get('oriInvoiceNo') or
                application_data.get('toinvoiceNo')
            ),
            'credit_note_no': application_data.get('referenceNo'),
            'application_date': application_data.get('applicationTime'),
            'status': EFRIS_STATUS_MAP.get(approve_status, f'Unknown ({approve_status})'),
            'approve_status': approve_status,
            'currency': application_data.get('currency') or 'UGX',
            'reason_code': reason_code,
            'reason_description': reason_codes.get(reason_code, reason_code),
            'reason': application_data.get('reason') or application_data.get('remarks'),
            'contact_name': application_data.get('contactName'),
            'contact_mobile': (
                application_data.get('contactMobileNum') or
                application_data.get('mobilePhone')
            ),
            'contact_email': application_data.get('contactEmail'),
            'remarks': application_data.get('remarks'),
            'gross_amount': float(
                application_data.get('totalAmount') or
                application_data.get('grossAmount') or 0
            ),
            'net_amount': 0,
            'tax_amount': 0,
            'applicant_tin': application_data.get('tin'),
            'applicant_name': application_data.get('legalName'),
            'buyer_tin': application_data.get('buyerTin'),
            'buyer_name': application_data.get('buyerLegalName'),
            'buyer_email': (
                application_data.get('buyerEmailAddress') or
                application_data.get('buyerEmail')
            ),
            'buyer_mobile': application_data.get('buyerMobilePhone'),
            'approve_remarks': application_data.get('approveRemarks'),
            'issued_date': (
                application_data.get('refundIssuedDate') or
                application_data.get('issuedDate')
            ),
            'task_id': application_data.get('taskId'),
            'address': application_data.get('address'),
            'can_approve': can_approve,
        }

        # Validate if application can be approved
        validation_errors = []
        if can_approve:
            if not basic_info['task_id']:
                validation_errors.append("Task ID is missing - cannot approve")
            if not basic_info['original_invoice_no']:
                validation_errors.append("Original invoice number is missing")

        basic_info['validation_errors'] = validation_errors

        # Process detail result (T118)
        goods_details = []
        tax_details = []
        payment_methods = []
        summary = {}

        detail_result = client.t118_query_credit_debit_note_detail(application_id)
        if detail_result.get('success'):
            goods_details = detail_result.get('goods_details', [])
            tax_details = detail_result.get('tax_details', [])
            payment_methods = detail_result.get('payment_methods', [])

            detail_summary = detail_result.get('summary', {})
            summary = {
                'gross_amount': float(detail_summary.get('grossAmount') or 0),
                'net_amount': float(detail_summary.get('netAmount') or 0),
                'tax_amount': float(detail_summary.get('taxAmount') or 0),
                'previous_gross_amount': float(detail_summary.get('previousGrossAmount') or 0),
                'previous_net_amount': float(detail_summary.get('previousNetAmount') or 0),
                'previous_tax_amount': float(detail_summary.get('previousTaxAmount') or 0),
                'remarks': detail_summary.get('remarks'),
                'item_count': len(goods_details),
            }

            basic_info['net_amount'] = summary['net_amount']
            basic_info['tax_amount'] = summary['tax_amount']

            if can_approve and summary.get('gross_amount', 0) >= 0:
                validation_errors.append("Summary gross amount must be negative for credit note")

        context = {
            'page_title': f'Credit Note Application {application_id}',
            'application': basic_info,
            'goods_details': goods_details,
            'tax_details': tax_details,
            'summary': summary,
            'payment_methods': payment_methods,
            'application_id': application_id,
            'company': company,
            'debug': request.GET.get('debug', False),
            'status_class': CreditNoteStatus,
            'approval_class': ApprovalAction,
        }

        return render(request, 'efris/credit_note_application_detail.html', context)

    except Exception as e:
        logger.error(f"Application detail failed: {e}", exc_info=True)
        messages.error(request, f"Error: {str(e)}")
        return redirect('efris:credit_note_applications')


import json


@login_required
@require_http_methods(["POST"])
def approve_credit_note_application(request, application_id):
    """
    T113 - Approve/Reject Credit Note Application
    """
    company = request.tenant

    if not company.efris_enabled:
        return JsonResponse({
            'success': False,
            'error': 'EFRIS is not enabled for your company'
        }, status=403)

    try:
        # Parse request data
        if request.content_type == 'application/json':
            try:
                data = json.loads(request.body)
            except json.JSONDecodeError:
                return JsonResponse({
                    'success': False,
                    'error': 'Invalid JSON data'
                }, status=400)
        else:
            data = request.POST

        # Extract fields
        reference_no = data.get('reference_no', '').strip()
        approve_action = data.get('approve_status', '').strip()
        task_id = data.get('task_id', '').strip()
        remark = data.get('remark', '').strip()
        app_id = data.get('application_id', '').strip()

        # Validate basic fields
        missing_fields = []
        if not reference_no:
            missing_fields.append('reference_no')
        if not approve_action:
            missing_fields.append('approve_status')
        if not remark:
            missing_fields.append('remark')

        if missing_fields:
            return JsonResponse({
                'success': False,
                'error': f"Missing required fields: {', '.join(missing_fields)}"
            }, status=400)

        if approve_action not in ['101', '103']:
            return JsonResponse({
                'success': False,
                'error': 'Invalid approval action. Must be 101 (Approve) or 103 (Reject)'
            }, status=400)

        if len(remark) > 1024:
            return JsonResponse({
                'success': False,
                'error': f'Remark too long ({len(remark)} characters). Maximum is 1024'
            }, status=400)

        # Get detailed application info from T112
        client = EnhancedEFRISAPIClient(company)

        logger.info("=" * 80)
        logger.info(f"APPROVAL PROCESS START - Application ID: {application_id}")
        logger.info("=" * 80)

        status_check = client.t112_query_credit_note_application_detail(application_id)

        if not status_check.get('success'):
            return JsonResponse({
                'success': False,
                'error': f"Failed to get application details: {status_check.get('error')}"
            }, status=400)

        application_detail = status_check.get('application_detail', {})

        # Log all T112 fields for debugging
        logger.info("T112 Application Details:")
        logger.info(f"  - ID: {application_detail.get('id')}")
        logger.info(f"  - referenceNo: {application_detail.get('referenceNo')}")
        logger.info(f"  - approveStatusCode: {application_detail.get('approveStatusCode')}")
        logger.info(f"  - taskId: {application_detail.get('taskId')}")
        logger.info(f"  - oriInvoiceNo: {application_detail.get('oriInvoiceNo')}")
        logger.info(f"  - invoiceApplyCategoryCode: {application_detail.get('invoiceApplyCategoryCode')}")
        logger.info(f"  - source: {application_detail.get('source')}")

        current_status = application_detail.get('approveStatusCode')

        # Get taskId from T112
        if not task_id:
            task_id = application_detail.get('taskId', '')
            logger.info(f"TaskId from T112: '{task_id}'")

        # Verify taskId exists
        if not task_id:
            logger.error("CRITICAL: taskId is missing from T112 response!")
            logger.error(f"Full T112 response: {json.dumps(application_detail, indent=2)}")
            return JsonResponse({
                'success': False,
                'error': 'Task ID not found. This application may not be eligible for approval through this interface.'
            }, status=400)

        # Verify referenceNo matches
        t112_reference = application_detail.get('referenceNo', '')
        if t112_reference and t112_reference != reference_no:
            logger.warning(f"Reference number mismatch! T112: '{t112_reference}', Provided: '{reference_no}'")
            # Use the one from T112 as it's authoritative
            reference_no = t112_reference
            logger.info(f"Using reference number from T112: {reference_no}")

        # Check status
        logger.info(f"Current approveStatusCode: {current_status}")

        if current_status != '102':
            status_names = {'101': 'Approved', '102': 'Pending', '103': 'Rejected'}
            error_msg = f'Application status is {status_names.get(current_status, current_status)} ({current_status}). Only Pending (102) applications can be approved.'
            logger.error(error_msg)
            return JsonResponse({
                'success': False,
                'error': error_msg
            }, status=400)

        # Final values summary before T113 call
        logger.info("=" * 80)
        logger.info("CALLING T113 WITH:")
        logger.info(f"  referenceNo: '{reference_no}'")
        logger.info(f"  approveStatus: '{approve_action}'")
        logger.info(f"  taskId: '{task_id}'")
        logger.info(f"  remark: '{remark[:50]}...' (len: {len(remark)})")
        logger.info("=" * 80)

        # Call T113
        result = client.t113_approve_credit_note_application(
            reference_no=reference_no,
            approve_status=approve_action,
            task_id=task_id,
            remark=remark
        )

        action_display = 'Approved' if approve_action == '101' else 'Rejected'

        if result.get('success'):
            try:
                audit_data = {
                    'reference_no': reference_no,
                    'approve_action': approve_action,
                    'task_id': task_id,
                    'application_id': application_id
                }

                FiscalizationAudit.objects.create(
                    company=company,
                    user=request.user,
                    action=f'CREDIT_NOTE_{action_display.upper()}',
                    efris_return_code='00',
                    efris_return_message=f"Application {reference_no} {action_display}",
                    request_data=json.dumps(audit_data)
                )
            except Exception as audit_error:
                logger.error(f"Audit logging failed: {audit_error}")

            logger.info(f"✅ SUCCESS: Application {reference_no} {action_display}")

            return JsonResponse({
                'success': True,
                'message': result.get('message', f'Application {action_display} successfully'),
                'status': action_display
            })

        else:
            error_msg = result.get('error', 'Unknown error')
            return_code = result.get('error_code', 'ERROR')

            try:
                FiscalizationAudit.objects.create(
                    company=company,
                    user=request.user,
                    action='CREDIT_NOTE_APPROVAL_FAILED',
                    efris_return_code=return_code,
                    efris_return_message=error_msg,
                    request_data=json.dumps({
                        'reference_no': reference_no,
                        'approve_action': approve_action,
                        'task_id': task_id,
                        'application_id': application_id,
                        'error': error_msg
                    })
                )
            except Exception as audit_error:
                logger.error(f"Audit logging failed: {audit_error}")

            logger.error(f"❌ FAILED: {error_msg} (code: {return_code})")

            return JsonResponse({
                'success': False,
                'error': error_msg,
                'error_code': return_code
            }, status=400)

    except Exception as e:
        logger.error(f"Exception in approval: {e}", exc_info=True)

        try:
            FiscalizationAudit.objects.create(
                company=company,
                user=request.user,
                action='CREDIT_NOTE_APPROVAL_ERROR',
                efris_return_code='SYSTEM_ERROR',
                efris_return_message=str(e),
                request_data=json.dumps({
                    'application_id': application_id,
                    'error': str(e)
                })
            )
        except:
            pass

        return JsonResponse({
            'success': False,
            'error': f'System error: {str(e)}'
        }, status=500)


@login_required
def refresh_application_status(request, application_id):
    """
    Refresh the status of a credit note application
    Useful when waiting for URA to process an approval
    """
    company = request.tenant

    if not company.efris_enabled:
        messages.error(request, "EFRIS is not enabled for your company")
        return redirect('efris:credit_note_applications')

    try:
        client = EnhancedEFRISAPIClient(company)
        result = client.t112_query_credit_note_application_detail(application_id)

        if result.get('success'):
            current_status = result.get('application_detail', {}).get('approveStatusCode')
            status_display = CreditNoteStatus.get_display(current_status)

            messages.success(
                request,
                f"Status refreshed: {status_display}"
            )
        else:
            messages.error(request, f"Failed to refresh status: {result.get('error')}")

    except Exception as e:
        logger.error(f"Status refresh failed: {e}", exc_info=True)
        messages.error(request, f"Error refreshing status: {str(e)}")

    return redirect('efris:credit_note_application_detail', application_id=application_id)


@login_required
@require_http_methods(["POST"])
def cancel_credit_debit_note(request):
    """
    T114 - Cancel Credit/Debit Note
    """
    company = request.tenant

    if not company.efris_enabled:
        return JsonResponse({
            'success': False,
            'error': 'EFRIS is not enabled for your company'
        })

    try:
        ori_invoice_id = request.POST.get('ori_invoice_id')
        invoice_no = request.POST.get('invoice_no')
        reason_code = request.POST.get('reason_code')
        category_code = request.POST.get('category_code')
        reason = request.POST.get('reason')

        if not all([ori_invoice_id, invoice_no, reason_code, category_code]):
            return JsonResponse({
                'success': False,
                'error': 'Missing required fields'
            })

        # Handle file attachments if any
        attachments = []
        if request.FILES.get('attachment'):
            import base64
            file = request.FILES['attachment']
            file_content = base64.b64encode(file.read()).decode('utf-8')
            file_type = file.name.split('.')[-1].lower()

            attachments.append({
                'fileName': file.name,
                'fileType': file_type,
                'fileContent': file_content
            })

        client = EnhancedEFRISAPIClient(company)
        result = client.t114_cancel_credit_debit_note(
            ori_invoice_id=ori_invoice_id,
            invoice_no=invoice_no,
            reason_code=reason_code,
            invoice_apply_category_code=category_code,
            reason=reason,
            attachment_list=attachments if attachments else None
        )

        if result.get('success'):
            return JsonResponse({
                'success': True,
                'message': result.get('message')
            })
        else:
            return JsonResponse({
                'success': False,
                'error': result.get('error')
            })

    except Exception as e:
        logger.error(f"Cancellation failed: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
@require_http_methods(["POST"])
def void_credit_note_application(request):
    """
    T120 - Void Credit/Debit Note Application
    """
    company = request.tenant

    if not company.efris_enabled:
        return JsonResponse({
            'success': False,
            'error': 'EFRIS is not enabled for your company'
        })

    try:
        business_key = request.POST.get('business_key')
        reference_no = request.POST.get('reference_no')

        if not all([business_key, reference_no]):
            return JsonResponse({
                'success': False,
                'error': 'Missing required fields'
            })

        client = EnhancedEFRISAPIClient(company)
        result = client.t120_void_credit_debit_note_application(
            business_key=business_key,
            reference_no=reference_no
        )

        if result.get('success'):
            return JsonResponse({
                'success': True,
                'message': result.get('message')
            })
        else:
            return JsonResponse({
                'success': False,
                'error': result.get('error')
            })

    except Exception as e:
        logger.error(f"Void failed: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


# ============================================================================
# EXCHANGE RATE VIEWS
# ============================================================================

@login_required
def exchange_rates_view(request):
    """
    T126 - Exchange Rates Display
    Show current exchange rates for all currencies
    """
    company = request.tenant

    if not company.efris_enabled:
        messages.error(request, "EFRIS is not enabled for your company")
        return redirect('dashboard')

    context = {
        'page_title': 'EFRIS Exchange Rates',
        'company': company
    }

    try:
        issue_date = request.GET.get('date')  # Optional date filter

        client = EnhancedEFRISAPIClient(company)
        result = client.t126_get_all_exchange_rates(issue_date=issue_date)

        if result.get('success'):
            context['rates'] = result.get('rates', [])
            context['total_currencies'] = result.get('total_currencies', 0)
            context['issue_date'] = issue_date or timezone.now().date()
        else:
            messages.error(request, f"Failed to load exchange rates: {result.get('error')}")

    except Exception as e:
        logger.error(f"Exchange rates query failed: {e}", exc_info=True)
        messages.error(request, f"Error: {str(e)}")

    return render(request, 'efris/exchange_rates.html', context)


@login_required
def get_exchange_rate_api(request):
    """
    T121 - Get Single Exchange Rate (API endpoint)
    """
    company = request.tenant

    if not company.efris_enabled:
        return JsonResponse({
            'success': False,
            'error': 'EFRIS is not enabled for your company'
        })

    try:
        currency = request.GET.get('currency')
        issue_date = request.GET.get('date')

        if not currency:
            return JsonResponse({
                'success': False,
                'error': 'Currency code is required'
            })

        client = EnhancedEFRISAPIClient(company)
        result = client.t121_get_exchange_rate(
            currency=currency,
            issue_date=issue_date
        )

        return JsonResponse(result)

    except Exception as e:
        logger.error(f"Exchange rate query failed: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


# ============================================================================
# EXCISE DUTY VIEWS
# ============================================================================

@login_required
def excise_duty_list_view(request):
    """
    T125 - Excise Duty List
    Display all excise duty rates and categories
    """
    company = request.tenant

    if not company.efris_enabled:
        messages.error(request, "EFRIS is not enabled for your company")
        return redirect('dashboard')

    context = {
        'page_title': 'EFRIS Excise Duty Rates',
        'company': company
    }

    try:
        client = EnhancedEFRISAPIClient(company)
        result = client.t125_query_excise_duty()

        if result.get('success'):
            excise_duties = result.get('excise_duties', [])

            # Paginate results
            paginator = Paginator(excise_duties, 20)
            page_number = request.GET.get('page', 1)
            page_obj = paginator.get_page(page_number)

            context['excise_duties'] = page_obj
            context['total_count'] = len(excise_duties)
        else:
            messages.error(request, f"Failed to load excise duties: {result.get('error')}")

    except Exception as e:
        logger.error(f"Excise duty query failed: {e}", exc_info=True)
        messages.error(request, f"Error: {str(e)}")

    return render(request, 'efris/excise_duty_list.html', context)


# ============================================================================
# BATCH UPLOAD VIEWS
# ============================================================================
@login_required
def batch_invoice_upload_view(request):
    """
    T129 - Batch Invoice Upload
    Upload multiple invoices at once and UPDATE the database
    """
    company = request.tenant

    if not company.efris_enabled:
        messages.error(request, "EFRIS is not enabled for your company")
        return redirect('dashboard')

    context = {
        'page_title': 'Batch Invoice Upload',
        'company': company
    }

    if request.method == 'POST':
        try:
            # Get invoice IDs to upload
            invoice_ids = request.POST.getlist('invoice_ids')

            if not invoice_ids:
                messages.error(request, "No invoices selected for upload")
                return redirect('efris:batch_invoice_upload')

            # Prepare batch data
            from invoices.models import Invoice
            from sales.models import Sale
            from .services import EFRISDataTransformer

            invoices_data = []
            invoice_mapping = {}
            transformer = EFRISDataTransformer(company)

            for idx, invoice_id in enumerate(invoice_ids):
                try:
                    invoice = Invoice.objects.select_related('sale').get(id=invoice_id)
                    invoice_data = transformer.build_invoice_data(invoice)

                    # Convert to JSON string
                    invoice_content = json.dumps(invoice_data, separators=(',', ':'))

                    # Create signature
                    client = EnhancedEFRISAPIClient(company)
                    private_key = client._load_private_key()
                    signature = client.security_manager.sign_content(
                        invoice_content,
                        algorithm="SHA1"
                    )

                    invoice_payload = {
                        "invoiceContent": invoice_content,
                        "invoiceSignature": signature
                    }

                    invoices_data.append(invoice_payload)
                    invoice_mapping[idx] = invoice

                except Invoice.DoesNotExist:
                    logger.warning(f"Invoice {invoice_id} not found")
                    continue
                except Exception as e:
                    logger.error(f"Failed to prepare invoice {invoice_id}: {e}", exc_info=True)
                    continue

            if not invoices_data:
                messages.error(request, "No valid invoices to upload")
                return redirect('efris:batch_invoice_upload')

            # Upload batch
            client = EnhancedEFRISAPIClient(company)
            result = client.t129_batch_invoice_upload(invoices_data)

            if result.get('success'):
                success_count = 0
                failed_count = 0

                results_list = result.get('results', [])

                for idx, invoice_result in enumerate(results_list):
                    try:
                        # Get the corresponding invoice
                        invoice = invoice_mapping.get(idx)

                        if not invoice:
                            logger.warning(f"No invoice mapping found for index {idx}")
                            continue

                        # Check if this invoice was successful
                        invoice_return_code = invoice_result.get('invoiceReturnCode') or invoice_result.get(
                            'returnCode')

                        if invoice_return_code == '00':
                            # ✅ CRITICAL FIX: Parse the invoiceContent JSON string
                            invoice_content_str = invoice_result.get('invoiceContent', '{}')

                            try:
                                invoice_content = json.loads(invoice_content_str)

                                # Extract fiscal data from nested structure
                                basic_info = invoice_content.get('basicInformation', {})
                                summary = invoice_content.get('summary', {})

                                fiscal_invoice_no = basic_info.get('invoiceNo', '')
                                fiscal_antifake_code = basic_info.get('antifakeCode', '')
                                fiscal_qr_code = summary.get('qrCode', '')

                                logger.info(
                                    f"📋 Extracted fiscal data - InvoiceNo: {fiscal_invoice_no}, AntifakeCode: {fiscal_antifake_code}")

                            except json.JSONDecodeError as e:
                                logger.error(f"Failed to parse invoiceContent JSON: {e}")
                                fiscal_invoice_no = ''
                                fiscal_antifake_code = ''
                                fiscal_qr_code = ''

                            # ✅ SUCCESS: Update the invoice
                            success_count += 1

                            invoice.fiscal_document_number = fiscal_invoice_no
                            invoice.fiscal_number = fiscal_invoice_no
                            invoice.verification_code = fiscal_antifake_code
                            invoice.qr_code = fiscal_qr_code
                            invoice.is_fiscalized = True
                            invoice.fiscalization_time = timezone.now()
                            invoice.fiscalization_status = 'fiscalized'
                            invoice.fiscalization_error = None
                            invoice.created_by = request.user  # ✅ Track who fiscalized

                            invoice.save(update_fields=[
                                'fiscal_document_number', 'fiscal_number',
                                'verification_code', 'qr_code', 'is_fiscalized',
                                'fiscalization_time', 'fiscalization_status',
                                'fiscalization_error', 'fiscalized_by'
                            ])

                            # ✅ CRITICAL: Update the Sale model too
                            if invoice.sale:
                                sale = invoice.sale
                                sale.efris_invoice_number = fiscal_invoice_no
                                sale.verification_code = fiscal_antifake_code
                                sale.qr_code = fiscal_qr_code
                                sale.is_fiscalized = True
                                sale.fiscalization_time = timezone.now()
                                sale.fiscalization_status = 'fiscalized'
                                sale.fiscalized_by = request.user  # ✅ Track who fiscalized

                                sale.save(update_fields=[
                                    'efris_invoice_number', 'verification_code', 'qr_code',
                                    'is_fiscalized', 'fiscalization_time', 'fiscalization_status',
                                    'fiscalized_by'
                                ])

                            logger.info(
                                f"✅ Successfully updated Invoice {invoice.id} and Sale {invoice.sale_id} with fiscal data")

                        else:
                            # ❌ FAILED: Log the error
                            failed_count += 1
                            error_msg = invoice_result.get('invoiceReturnMessage') or invoice_result.get(
                                'returnMessage', 'Unknown error')

                            invoice.fiscalization_status = 'failed'
                            invoice.fiscalization_error = error_msg
                            invoice.save(update_fields=['fiscalization_status', 'fiscalization_error'])

                            if invoice.sale:
                                invoice.sale.fiscalization_status = 'failed'
                                invoice.sale.save(update_fields=['fiscalization_status'])

                            logger.error(f"❌ Invoice {invoice.id} failed: {error_msg}")

                    except Exception as e:
                        failed_count += 1
                        logger.error(f"Error processing result for index {idx}: {e}", exc_info=True)

                # Show summary message
                messages.success(
                    request,
                    f"Batch upload completed: {success_count} successful, {failed_count} failed"
                )

                # Store results for display
                request.session['batch_upload_results'] = results_list
                return redirect('efris:batch_upload_results')
            else:
                messages.error(request, f"Batch upload failed: {result.get('error')}")

        except Exception as e:
            logger.error(f"Batch upload failed: {e}", exc_info=True)
            messages.error(request, f"Error: {str(e)}")

    # Get pending invoices for upload
    try:
        from invoices.models import Invoice
        pending_invoices = Invoice.objects.filter(
            is_fiscalized=False,
            sale__status__in=['COMPLETED', 'PAID']
        ).select_related('sale', 'sale__customer', 'sale__store').order_by('-created_at')[:50]

        context['pending_invoices'] = pending_invoices
    except Exception as e:
        logger.error(f"Failed to load pending invoices: {e}")
        context['pending_invoices'] = []

    return render(request, 'efris/batch_invoice_upload.html', context)


@login_required
def batch_upload_results_view(request):
    """Display results from batch invoice upload"""
    company = request.tenant

    results = request.session.get('batch_upload_results', [])

    context = {
        'page_title': 'Batch Upload Results',
        'company': company,
        'results': results,
        'total_count': len(results),
        'success_count': sum(1 for r in results if r.get('invoiceReturnCode') == '00'),
        'failed_count': sum(1 for r in results if r.get('invoiceReturnCode') != '00')
    }

    # Clear session data after displaying
    if 'batch_upload_results' in request.session:
        del request.session['batch_upload_results']

    return render(request, 'efris/batch_upload_results.html', context)


# ============================================================================
# API ENDPOINTS (for AJAX calls)
# ============================================================================

@login_required
def query_cancel_credit_note_detail_api(request):
    """
    T122 - Query Cancel Credit Note Detail (API endpoint)
    """
    company = request.tenant

    if not company.efris_enabled:
        return JsonResponse({
            'success': False,
            'error': 'EFRIS is not enabled for your company'
        })

    try:
        invoice_no = request.GET.get('invoice_no')

        if not invoice_no:
            return JsonResponse({
                'success': False,
                'error': 'Invoice number is required'
            })

        client = EnhancedEFRISAPIClient(company)
        result = client.t122_query_cancel_credit_note_detail(invoice_no)

        return JsonResponse(result)

    except Exception as e:
        logger.error(f"Query failed: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
def check_invoice_eligibility_api(request):
    """Check if an invoice can have a credit note issued"""
    company = request.tenant

    if not company.efris_enabled:
        return JsonResponse({
            'success': False,
            'error': 'EFRIS is not enabled for your company'
        })

    try:
        invoice_no = request.GET.get('invoice_no')

        if not invoice_no:
            return JsonResponse({
                'success': False,
                'error': 'Invoice number is required'
            })

        client = EnhancedEFRISAPIClient(company)
        result = client.get_invoice_with_credit_note_eligibility(invoice_no)

        return JsonResponse(result)

    except Exception as e:
        logger.error(f"Eligibility check failed: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


@login_required
def search_invoices_api(request):
    """API endpoint for invoice search (for AJAX)"""
    company = request.tenant

    if not company.efris_enabled:
        return JsonResponse({
            'success': False,
            'error': 'EFRIS is not enabled for your company'
        })

    try:
        # Get search parameters
        params = {
            'invoice_no': request.GET.get('invoice_no'),
            'buyer_tin': request.GET.get('buyer_tin'),
            'start_date': request.GET.get('start_date'),
            'end_date': request.GET.get('end_date'),
            'invoice_type': request.GET.get('invoice_type'),
            'page_no': int(request.GET.get('page', 1)),
            'page_size': int(request.GET.get('page_size', 20))
        }

        # Remove None values
        params = {k: v for k, v in params.items() if v}

        client = EnhancedEFRISAPIClient(company)
        result = client.t106_query_invoices(**params)

        return JsonResponse(result)

    except Exception as e:
        logger.error(f"Invoice search API failed: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        })


# ============================================================================
# DASHBOARD AND SUMMARY VIEWS
# ============================================================================

@login_required
def efris_dashboard_view(request):
    """
    EFRIS Dashboard
    Show overview of EFRIS operations and statistics
    """
    company = request.tenant

    if not company.efris_enabled:
        messages.error(request, "EFRIS is not enabled for your company")
        return redirect('dashboard')

    context = {
        'page_title': 'EFRIS Dashboard',
        'company': company
    }

    try:
        client = EnhancedEFRISAPIClient(company)

        # Get pending credit note applications
        pending_result = client.get_pending_credit_note_applications()
        context['pending_applications'] = pending_result.get('applications', [])[:5]
        context['pending_count'] = len(pending_result.get('applications', []))

        # Get recent API logs
        recent_logs = EFRISAPILog.objects.filter(
            company=company
        ).order_by('-request_time')[:10]
        context['recent_logs'] = recent_logs

        # Get fiscalization statistics
        from datetime import timedelta
        thirty_days_ago = timezone.now() - timedelta(days=30)

        total_fiscalized = FiscalizationAudit.objects.filter(
            company=company,
            action='FISCALIZE',
            created_at__gte=thirty_days_ago
        ).count()

        successful_fiscalized = FiscalizationAudit.objects.filter(
            company=company,
            action='FISCALIZE',
            efris_return_code='00',
            created_at__gte=thirty_days_ago
        ).count()

        context['stats'] = {
            'total_fiscalized_30d': total_fiscalized,
            'successful_fiscalized_30d': successful_fiscalized,
            'success_rate': (successful_fiscalized / total_fiscalized * 100) if total_fiscalized > 0 else 0
        }

        # Get exchange rates
        rates_result = client.get_current_exchange_rates()
        if rates_result.get('success'):
            context['exchange_rates'] = list(rates_result.get('rates', {}).items())[:5]

    except Exception as e:
        logger.error(f"Dashboard data loading failed: {e}", exc_info=True)
        messages.warning(request, "Some dashboard data could not be loaded")

    return render(request, 'efris/dashboarded.html', context)



@login_required
def efris_reports_view(request):
    """
    EFRIS Reports View
    Generate various reports based on EFRIS data
    """
    company = request.tenant

    if not company.efris_enabled:
        messages.error(request, "EFRIS is not enabled for your company")
        return redirect('dashboard')

    context = {
        'page_title': 'EFRIS Reports',
        'company': company
    }

    report_type = request.GET.get('type', 'summary')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if not start_date:
        start_date = (timezone.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    if not end_date:
        end_date = timezone.now().strftime('%Y-%m-%d')

    context['start_date'] = start_date
    context['end_date'] = end_date
    context['report_type'] = report_type

    try:
        client = EnhancedEFRISAPIClient(company)

        if report_type == 'invoices':
            # Invoice report - FIXED: Use proper page size
            result = client.search_invoices_by_date_range(
                start_date=start_date,
                end_date=end_date,
                page_size=50  # Safe page size
            )

            if result.get('success'):
                invoices = result.get('invoices', [])
                context['invoices'] = invoices
                context['total_invoices'] = len(invoices)

                # Calculate totals
                total_amount = sum(float(inv.get('grossAmount', 0)) for inv in invoices)
                total_tax = sum(float(inv.get('taxAmount', 0)) for inv in invoices)

                context['summary'] = {
                    'total_amount': total_amount,
                    'total_tax': total_tax,
                    'average_amount': total_amount / len(invoices) if invoices else 0
                }
            else:
                messages.error(request, f"Failed to load invoices: {result.get('error')}")

        elif report_type == 'credit_notes':
            # Credit notes report - FIXED: Use proper page size
            result = client.t111_query_credit_note_applications(
                start_date=start_date,
                end_date=end_date,
                query_type="1",  # My applications
                page_size=50
            )

            if result.get('success'):
                applications = result.get('applications', [])
                context['applications'] = applications
                context['total_applications'] = len(applications)

                # Group by status
                approved = [a for a in applications if a.get('approveStatus') == '101']
                pending = [a for a in applications if a.get('approveStatus') == '102']
                rejected = [a for a in applications if a.get('approveStatus') == '103']

                context['status_breakdown'] = {
                    'approved': len(approved),
                    'pending': len(pending),
                    'rejected': len(rejected)
                }
            else:
                messages.error(request, f"Failed to load applications: {result.get('error')}")

        elif report_type == 'api_logs':
            # API logs report
            logs = EFRISAPILog.objects.filter(
                company=company,
              request_time__date__gte=start_date,
              request_time__date__lte=end_date
            ).order_by('-request_time')

            # Paginate
            paginator = Paginator(logs, 50)
            page_number = request.GET.get('page', 1)
            context['logs'] = paginator.get_page(page_number)

    except Exception as e:
        logger.error(f"Report generation failed: {e}", exc_info=True)
        messages.error(request, f"Error generating report: {str(e)}")

    return render(request, 'efris/reports.html', context)


# ============================================================================
# EXPORT FUNCTIONS
# ============================================================================

@login_required
def export_invoices_csv(request):
    """Export invoice search results to CSV"""
    import csv

    company = request.tenant

    if not company.efris_enabled:
        messages.error(request, "EFRIS is not enabled for your company")
        return redirect('dashboard')

    try:
        # Get search parameters from session or request
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        invoice_type = request.GET.get('invoice_type')

        client = EnhancedEFRISAPIClient(company)
        result = client.search_invoices_by_date_range(
            start_date=start_date,
            end_date=end_date,
            invoice_type=invoice_type,
            page_size=100
        )

        if not result.get('success'):
            messages.error(request, f"Export failed: {result.get('error')}")
            return redirect('efris:invoice_search')

        # Create CSV response
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="efris_invoices_{timezone.now().strftime("%Y%m%d")}.csv"'

        writer = csv.writer(response)

        # Write header
        writer.writerow([
            'Invoice No',
            'Issue Date',
            'Buyer TIN',
            'Buyer Name',
            'Currency',
            'Gross Amount',
            'Tax Amount',
            'Invoice Type',
            'Status'
        ])

        # Write data
        for invoice in result.get('invoices', []):
            writer.writerow([
                invoice.get('invoiceNo', ''),
                invoice.get('issuedDate', ''),
                invoice.get('buyerTin', ''),
                invoice.get('buyerLegalName', ''),
                invoice.get('currency', ''),
                invoice.get('grossAmount', ''),
                invoice.get('taxAmount', ''),
                invoice.get('invoiceType', ''),
                'Invalid' if invoice.get('isInvalid') == '1' else 'Valid'
            ])

        return response

    except Exception as e:
        logger.error(f"CSV export failed: {e}", exc_info=True)
        messages.error(request, f"Export error: {str(e)}")
        return redirect('efris:invoice_search')


@login_required
def export_credit_notes_pdf(request):
    """Export credit note applications to PDF"""
    from django.template.loader import render_to_string
    from weasyprint import HTML
    import tempfile

    company = request.tenant

    if not company.efris_enabled:
        messages.error(request, "EFRIS is not enabled for your company")
        return redirect('dashboard')

    try:
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')

        client = EnhancedEFRISAPIClient(company)
        result = client.t111_query_credit_note_applications(
            start_date=start_date,
            end_date=end_date,
            page_size=100
        )

        if not result.get('success'):
            messages.error(request, f"Export failed: {result.get('error')}")
            return redirect('efris:credit_note_applications')

        # Render HTML
        html_string = render_to_string('efris/pdf/credit_notes_report.html', {
            'company': company,
            'applications': result.get('applications', []),
            'start_date': start_date,
            'end_date': end_date,
            'generated_at': timezone.now()
        })

        # Generate PDF
        html = HTML(string=html_string)
        result_pdf = html.write_pdf()

        # Create response
        response = HttpResponse(result_pdf, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="credit_notes_{timezone.now().strftime("%Y%m%d")}.pdf"'

        return response

    except Exception as e:
        logger.error(f"PDF export failed: {e}", exc_info=True)
        messages.error(request, f"Export error: {str(e)}")
        return redirect('efris:credit_note_applications')