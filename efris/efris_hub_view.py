"""
EFRIS Unified View — views_unified.py
======================================
All page-rendering views consolidated into one view: efris_hub_view()
The active tab is driven by ?tab=<name> in the URL.

URL setup (replace individual URL patterns with ONE):
    path('hub/', views.efris_hub_view, name='hub'),
    # or keep old names as redirects — see bottom of file

JSON/AJAX endpoints are UNCHANGED — they stay as-is.
Detail views (invoice_detail, credit_note_application_detail, print_credit_note)
are UNCHANGED — they work on a per-record basis and don't belong in a hub.
"""

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


# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS (shared across tabs)
# ─────────────────────────────────────────────────────────────────────────────

REASON_CODES = {
    '101': 'Return of products due to expiry or damage',
    '102': 'Cancellation of the purchase',
    '103': 'Invoice amount wrongly stated',
    '104': 'Partial or complete waive off',
    '105': 'Others',
}

REASON_CODES_LIST = list(REASON_CODES.items())

EFRIS_STATUS_MAP = {
    '101': 'Approved',
    '102': 'Submitted',
    '103': 'Rejected',
    '104': 'Voided',
    '105': 'Processed',
}


class CreditNoteStatus:
    PENDING   = '101'
    APPROVED  = '102'
    REJECTED  = '103'
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
    def get_display(cls, code):
        return cls.STATUS_DISPLAY.get(code, f'Unknown ({code})')

    @classmethod
    def can_approve(cls, code):
        return code == cls.PENDING


class ApprovalAction:
    APPROVE = '101'
    REJECT  = '103'
    ACTION_DISPLAY = {'101': 'Approved', '103': 'Rejected'}


# ─────────────────────────────────────────────────────────────────────────────
# VALID TABS — maps tab name → page title
# ─────────────────────────────────────────────────────────────────────────────

TABS = {
    'dashboard':           'EFRIS Dashboard',
    'invoice_search':      'Invoice Search',
    'normal_invoices':     'Normal Invoices',
    'credit_notes':        'Credit / Debit Notes',
    'exception_logs':      'Exception Logs',
    'system_upgrade':      'System Upgrade',
    'certificate_upload':  'Certificate Upload',
    'branches':            'Branches',
    'taxpayer_check':      'Taxpayer Exemption Check',
    'exchange_rates':      'Exchange Rates',
    'excise_duty':         'Excise Duty',
    'reports':             'Reports',
    'batch_upload':        'Batch Invoice Upload',
    'commodity_categories':'Commodity Category Updates',
}

DEFAULT_TAB = 'dashboard'


# ─────────────────────────────────────────────────────────────────────────────
# GUARD HELPER
# ─────────────────────────────────────────────────────────────────────────────

def _efris_guard(request, company):
    """Returns True if EFRIS is enabled, otherwise sets error message and returns False."""
    if not company.efris_enabled:
        messages.error(request, "EFRIS is not enabled for your company")
        return False
    return True


# ─────────────────────────────────────────────────────────────────────────────
# TAB HANDLERS — each returns a dict merged into context
# ─────────────────────────────────────────────────────────────────────────────

def _tab_dashboard(request, company):
    ctx = {}
    try:
        client = EnhancedEFRISAPIClient(company)

        pending_result = client.get_pending_credit_note_applications()
        ctx['pending_applications'] = pending_result.get('applications', [])[:5]
        ctx['pending_count'] = len(pending_result.get('applications', []))

        ctx['recent_logs'] = EFRISAPILog.objects.filter(
            company=company
        ).order_by('-request_time')[:10]

        thirty_days_ago = timezone.now() - timedelta(days=30)
        total = FiscalizationAudit.objects.filter(
            company=company, action='FISCALIZE',
            created_at__gte=thirty_days_ago
        ).count()
        success = FiscalizationAudit.objects.filter(
            company=company, action='FISCALIZE',
            efris_return_code='00',
            created_at__gte=thirty_days_ago
        ).count()

        ctx['stats'] = {
            'total_fiscalized_30d':   total,
            'successful_fiscalized_30d': success,
            'success_rate': (success / total * 100) if total > 0 else 0,
        }

        rates_result = client.get_current_exchange_rates()
        if rates_result.get('success'):
            ctx['exchange_rates'] = list(rates_result.get('rates', {}).items())[:5]

    except Exception as e:
        logger.error(f"Dashboard data loading failed: {e}", exc_info=True)
        messages.warning(request, "Some dashboard data could not be loaded")
    return ctx


def _tab_invoice_search(request, company):
    ctx = {}
    if request.method == 'POST' or request.GET.get('search'):
        try:
            search_params = {
                'invoice_no':        request.POST.get('invoice_number') or request.GET.get('invoice_number'),
                'buyer_tin':         request.POST.get('buyer_tin') or request.GET.get('buyer_tin'),
                'buyer_legal_name':  request.POST.get('buyer_legal_name') or request.GET.get('buyer_legal_name'),
                'invoice_type':      request.POST.get('invoice_type') or request.GET.get('invoice_type'),
                'invoice_kind':      request.POST.get('invoice_kind') or request.GET.get('invoice_kind'),
                'start_date':        request.POST.get('start_date') or request.GET.get('start_date'),
                'end_date':          request.POST.get('end_date') or request.GET.get('end_date'),
                'is_invalid':        request.POST.get('is_invalid') or request.GET.get('is_invalid'),
                'is_refund':         request.POST.get('is_refund') or request.GET.get('is_refund'),
                'reference_no':      request.POST.get('reference_no') or request.GET.get('reference_no'),
                'page_no':           int(request.GET.get('page', 1)),
            }
            search_params = {k: v for k, v in search_params.items() if v}
            client = EnhancedEFRISAPIClient(company)
            result = client.t106_query_invoices(**search_params)
            if result.get('success'):
                ctx['invoices']          = result.get('invoices', [])
                ctx['pagination']        = result.get('pagination', {})
                ctx['search_performed']  = True
                ctx['search_params']     = search_params
            else:
                messages.error(request, f"Search failed: {result.get('error')}")
        except Exception as e:
            logger.error(f"Invoice search failed: {e}", exc_info=True)
            messages.error(request, f"Search error: {str(e)}")
    return ctx


def _tab_normal_invoices(request, company):
    ctx = {
        'reason_codes': REASON_CODES_LIST,
    }
    if request.method == 'POST':
        invoice_no  = request.POST.get('invoice_no')
        invoice_id  = request.POST.get('invoice_id')
        reason_code = request.POST.get('reason_code', '102')
        reason      = request.POST.get('reason', '')
        try:
            with EnhancedEFRISAPIClient(company) as client:
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
                    return ctx, True  # signal redirect back to same tab

                credit_note_data = build_result['credit_note_data']
                result = client.t110_apply_credit_note(credit_note_data)

                if result.get('success'):
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
                        f"Credit note submitted! Reference: {result.get('reference_no')}"
                    )
                else:
                    messages.error(request, f"Application failed: {result.get('error')}")

        except Exception as e:
            logger.error(f"Credit note error: {e}", exc_info=True)
            messages.error(request, f"Error: {str(e)}")
        return ctx, True  # POST done — reload same tab

    # GET — load invoices
    try:
        page_no    = int(request.GET.get('page', 1))
        buyer_tin  = request.GET.get('buyer_tin')
        start_date = request.GET.get('start_date')
        end_date   = request.GET.get('end_date')
        client     = EnhancedEFRISAPIClient(company)
        result     = client.t107_query_normal_invoices(
            buyer_tin=buyer_tin, start_date=start_date,
            end_date=end_date, page_no=page_no, page_size=20
        )
        if result.get('success'):
            ctx['invoices']   = result.get('invoices', [])
            ctx['pagination'] = result.get('pagination', {})
        else:
            messages.error(request, f"Failed to load invoices: {result.get('error')}")
    except Exception as e:
        logger.error(f"Normal invoices query failed: {e}", exc_info=True)
        messages.error(request, f"Error: {str(e)}")
    return ctx


def _tab_credit_notes(request, company):
    ctx = {
        'status_class': CreditNoteStatus,
        'status_options': [
            ('', 'All Status'),
            (CreditNoteStatus.PENDING,   CreditNoteStatus.STATUS_DISPLAY[CreditNoteStatus.PENDING]),
            (CreditNoteStatus.APPROVED,  CreditNoteStatus.STATUS_DISPLAY[CreditNoteStatus.APPROVED]),
            (CreditNoteStatus.REJECTED,  CreditNoteStatus.STATUS_DISPLAY[CreditNoteStatus.REJECTED]),
            (CreditNoteStatus.CANCELLED, CreditNoteStatus.STATUS_DISPLAY[CreditNoteStatus.CANCELLED]),
            (CreditNoteStatus.PROCESSED, CreditNoteStatus.STATUS_DISPLAY[CreditNoteStatus.PROCESSED]),
        ],
    }
    try:
        page_no        = int(request.GET.get('page', 1))
        approve_status = request.GET.get('approve_status')
        category_code  = request.GET.get('category_code')
        start_date     = request.GET.get('start_date')
        end_date       = request.GET.get('end_date')
        query_type     = request.GET.get('query_type', '1')
        if query_type not in ['1', '2', '3']:
            query_type = '1'

        client = EnhancedEFRISAPIClient(company)
        result = client.t111_query_credit_note_applications(
            approve_status=approve_status,
            invoice_apply_category_code=category_code,
            start_date=start_date, end_date=end_date,
            query_type=query_type, page_no=page_no, page_size=20
        )

        if result.get('success'):
            applications = result.get('applications', [])
            status_map = {
                '101': 'Approved', '102': 'Submitted', '103': 'Rejected',
                '104': 'Voided',   '105': 'Processed',
            }
            for app in applications:
                app_status = app.get('approveStatus') or app.get('approve_status')
                app['approve_status']   = app_status
                app['status_display']   = status_map.get(app_status, f'Unknown ({app_status})')
                app['can_approve']      = (app_status == '102')
                reason_code = app.get('invoiceApplyCategoryCode') or app.get('invoice_apply_category_code')
                app['reason_description'] = REASON_CODES.get(reason_code, f"Code: {reason_code}")

            ctx['applications'] = applications
            ctx['pagination']   = result.get('pagination', {})
            ctx['filters']      = {
                'approve_status': approve_status, 'category_code': category_code,
                'start_date': start_date, 'end_date': end_date, 'query_type': query_type,
            }
        else:
            messages.error(request, f"Failed to load applications: {result.get('error')}")

    except Exception as e:
        logger.error(f"Applications query failed: {e}", exc_info=True)
        messages.error(request, f"Error: {str(e)}")
    return ctx


def _tab_exception_logs(request, company):
    ctx = {}
    try:
        from efris.models import EFRISExceptionLog
        uploaded           = request.GET.get('uploaded')
        interruption_type  = request.GET.get('type')
        start_date         = request.GET.get('start_date')
        end_date           = request.GET.get('end_date')

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

        paginator    = Paginator(logs, 50)
        page_obj     = paginator.get_page(request.GET.get('page', 1))
        ctx['logs']          = page_obj
        ctx['pending_count'] = EFRISExceptionLog.objects.filter(
            company=company, uploaded=False
        ).count()

    except Exception as e:
        logger.error(f"Failed to load exception logs: {e}", exc_info=True)
        messages.error(request, f"Error: {str(e)}")
    return ctx


def _tab_system_upgrade(request, company):
    ctx = {}
    try:
        client          = EnhancedEFRISAPIClient(company)
        current_version = getattr(settings, 'EFRIS_TCS_VERSION', '1')
        version_result  = client.t135_get_latest_tcs_version()
        if version_result.get('success'):
            latest_version       = version_result.get('latest_version', current_version)
            ctx['current_version'] = current_version
            ctx['latest_version']  = latest_version
            ctx['update_available'] = int(latest_version) > int(current_version)
        else:
            messages.warning(request, f"Could not check for updates: {version_result.get('error')}")
    except Exception as e:
        logger.error(f"System upgrade check failed: {e}", exc_info=True)
        messages.error(request, f"Error: {str(e)}")
    return ctx


def _tab_certificate_upload(request, company):
    ctx = {}
    if request.method == 'POST':
        try:
            certificate_file     = request.FILES.get('certificate_file')
            if not certificate_file:
                messages.error(request, "Please select a certificate file")
                return ctx
            if not (certificate_file.name.endswith('.crt') or certificate_file.name.endswith('.cer')):
                messages.error(request, "File must be .crt or .cer format")
                return ctx
            if certificate_file.size > 10 * 1024 * 1024:
                messages.error(request, "File size must be less than 10MB")
                return ctx

            import base64
            file_content = base64.b64encode(certificate_file.read()).decode('utf-8')
            client       = EnhancedEFRISAPIClient(company)
            result       = client.t136_upload_certificate_public_key(
                file_name=certificate_file.name, file_content=file_content
            )
            if result.get('success'):
                messages.success(request, f"Certificate {certificate_file.name} uploaded successfully")
                logger.info(f"Certificate uploaded: {certificate_file.name}, size: {certificate_file.size}")
            else:
                error_msg  = result.get('error', 'Unknown error')
                error_code = result.get('error_code')
                if error_code == '2096':
                    messages.error(request, "Upload failed: VerifyString error. Please check TIN configuration.")
                else:
                    messages.error(request, f"Upload failed: {error_msg}")
                logger.error(f"Certificate upload failed: {error_msg} (code: {error_code})")

        except Exception as e:
            logger.error(f"Certificate upload failed: {e}", exc_info=True)
            messages.error(request, f"Error: {str(e)}")
    return ctx


def _tab_branches(request, company):
    ctx = {}
    try:
        client = EnhancedEFRISAPIClient(company)
        result = client.t138_get_all_branches()
        if result.get('success'):
            ctx['branches']       = result.get('branches', [])
            ctx['total_branches'] = len(ctx['branches'])
        else:
            messages.error(request, f"Failed to load branches: {result.get('error')}")
    except Exception as e:
        logger.error(f"Branches query failed: {e}", exc_info=True)
        messages.error(request, f"Error: {str(e)}")
    return ctx


def _tab_taxpayer_check(request, company):
    ctx = {}
    if request.method == 'POST':
        try:
            tin              = request.POST.get('tin')
            commodity_codes  = request.POST.get('commodity_codes', '')
            if not tin:
                messages.error(request, "TIN is required")
                return ctx
            client = EnhancedEFRISAPIClient(company)
            result = client.t137_check_exempt_deemed_taxpayer(
                tin=tin,
                commodity_category_codes=commodity_codes if commodity_codes else None
            )
            if result.get('success'):
                ctx['check_result']  = result
                ctx['searched_tin']  = tin
            else:
                messages.error(request, f"Check failed: {result.get('error')}")
        except Exception as e:
            logger.error(f"Exemption check failed: {e}", exc_info=True)
            messages.error(request, f"Error: {str(e)}")
    return ctx


def _tab_exchange_rates(request, company):
    ctx = {}
    try:
        issue_date = request.GET.get('date')
        client     = EnhancedEFRISAPIClient(company)
        result     = client.t126_get_all_exchange_rates(issue_date=issue_date)
        if result.get('success'):
            ctx['rates']            = result.get('rates', [])
            ctx['total_currencies'] = result.get('total_currencies', 0)
            ctx['issue_date']       = issue_date or timezone.now().date()
        else:
            messages.error(request, f"Failed to load exchange rates: {result.get('error')}")
    except Exception as e:
        logger.error(f"Exchange rates query failed: {e}", exc_info=True)
        messages.error(request, f"Error: {str(e)}")
    return ctx


def _tab_excise_duty(request, company):
    ctx = {}
    try:
        client = EnhancedEFRISAPIClient(company)
        result = client.t125_query_excise_duty()
        if result.get('success'):
            excise_duties  = result.get('excise_duties', [])
            paginator      = Paginator(excise_duties, 20)
            page_obj       = paginator.get_page(request.GET.get('page', 1))
            ctx['excise_duties'] = page_obj
            ctx['total_count']   = len(excise_duties)
        else:
            messages.error(request, f"Failed to load excise duties: {result.get('error')}")
    except Exception as e:
        logger.error(f"Excise duty query failed: {e}", exc_info=True)
        messages.error(request, f"Error: {str(e)}")
    return ctx


def _tab_reports(request, company):
    ctx = {}
    report_type = request.GET.get('type', 'summary')
    start_date  = request.GET.get('start_date') or (timezone.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    end_date    = request.GET.get('end_date')   or timezone.now().strftime('%Y-%m-%d')
    ctx.update({'start_date': start_date, 'end_date': end_date, 'report_type': report_type})
    try:
        client = EnhancedEFRISAPIClient(company)
        if report_type == 'invoices':
            result = client.search_invoices_by_date_range(
                start_date=start_date, end_date=end_date, page_size=50
            )
            if result.get('success'):
                invoices = result.get('invoices', [])
                total_amount = sum(float(i.get('grossAmount', 0)) for i in invoices)
                total_tax    = sum(float(i.get('taxAmount', 0)) for i in invoices)
                ctx['invoices']      = invoices
                ctx['total_invoices'] = len(invoices)
                ctx['summary']       = {
                    'total_amount': total_amount,
                    'total_tax':    total_tax,
                    'average_amount': total_amount / len(invoices) if invoices else 0,
                }
            else:
                messages.error(request, f"Failed to load invoices: {result.get('error')}")

        elif report_type == 'credit_notes':
            result = client.t111_query_credit_note_applications(
                start_date=start_date, end_date=end_date, query_type="1", page_size=50
            )
            if result.get('success'):
                apps     = result.get('applications', [])
                approved = [a for a in apps if a.get('approveStatus') == '101']
                pending  = [a for a in apps if a.get('approveStatus') == '102']
                rejected = [a for a in apps if a.get('approveStatus') == '103']
                ctx['applications']      = apps
                ctx['total_applications'] = len(apps)
                ctx['status_breakdown']   = {
                    'approved': len(approved), 'pending': len(pending), 'rejected': len(rejected)
                }
            else:
                messages.error(request, f"Failed to load applications: {result.get('error')}")

        elif report_type == 'api_logs':
            logs = EFRISAPILog.objects.filter(
                company=company,
                request_time__date__gte=start_date,
                request_time__date__lte=end_date
            ).order_by('-request_time')
            paginator     = Paginator(logs, 50)
            ctx['logs']   = paginator.get_page(request.GET.get('page', 1))

    except Exception as e:
        logger.error(f"Report generation failed: {e}", exc_info=True)
        messages.error(request, f"Error generating report: {str(e)}")
    return ctx


def _tab_batch_upload(request, company):
    ctx = {}
    if request.method == 'POST':
        try:
            invoice_ids = request.POST.getlist('invoice_ids')
            if not invoice_ids:
                messages.error(request, "No invoices selected for upload")
                return ctx

            from invoices.models import Invoice
            from .services import EFRISDataTransformer

            invoices_data    = []
            invoice_mapping  = {}
            transformer      = EFRISDataTransformer(company)

            for idx, invoice_id in enumerate(invoice_ids):
                try:
                    invoice         = Invoice.objects.select_related('sale').get(id=invoice_id)
                    invoice_data    = transformer.build_invoice_data(invoice)
                    invoice_content = json.dumps(invoice_data, separators=(',', ':'))
                    client          = EnhancedEFRISAPIClient(company)
                    private_key     = client._load_private_key()
                    signature       = client.security_manager.sign_content(invoice_content, algorithm="SHA1")
                    invoices_data.append({"invoiceContent": invoice_content, "invoiceSignature": signature})
                    invoice_mapping[idx] = invoice
                except Invoice.DoesNotExist:
                    logger.warning(f"Invoice {invoice_id} not found")
                except Exception as e:
                    logger.error(f"Failed to prepare invoice {invoice_id}: {e}", exc_info=True)

            if not invoices_data:
                messages.error(request, "No valid invoices to upload")
                return ctx

            client = EnhancedEFRISAPIClient(company)
            result = client.t129_batch_invoice_upload(invoices_data)

            if result.get('success'):
                success_count = 0
                failed_count  = 0
                results_list  = result.get('results', [])

                for idx, invoice_result in enumerate(results_list):
                    try:
                        invoice              = invoice_mapping.get(idx)
                        if not invoice:
                            continue
                        invoice_return_code  = invoice_result.get('invoiceReturnCode') or invoice_result.get('returnCode')

                        if invoice_return_code == '00':
                            try:
                                invoice_content = json.loads(invoice_result.get('invoiceContent', '{}'))
                                basic_info      = invoice_content.get('basicInformation', {})
                                summary_info    = invoice_content.get('summary', {})
                                fiscal_no       = basic_info.get('invoiceNo', '')
                                antifake_code   = basic_info.get('antifakeCode', '')
                                qr_code         = summary_info.get('qrCode', '')
                            except json.JSONDecodeError as e:
                                logger.error(f"Failed to parse invoiceContent JSON: {e}")
                                fiscal_no = antifake_code = qr_code = ''

                            success_count += 1
                            invoice.fiscal_document_number = fiscal_no
                            invoice.fiscal_number          = fiscal_no
                            invoice.verification_code      = antifake_code
                            invoice.qr_code                = qr_code
                            invoice.is_fiscalized          = True
                            invoice.fiscalization_time     = timezone.now()
                            invoice.fiscalization_status   = 'fiscalized'
                            invoice.fiscalization_error    = None
                            invoice.created_by             = request.user
                            invoice.save(update_fields=[
                                'fiscal_document_number', 'fiscal_number', 'verification_code',
                                'qr_code', 'is_fiscalized', 'fiscalization_time',
                                'fiscalization_status', 'fiscalization_error', 'fiscalized_by'
                            ])

                            if invoice.sale:
                                sale = invoice.sale
                                sale.efris_invoice_number  = fiscal_no
                                sale.verification_code     = antifake_code
                                sale.qr_code               = qr_code
                                sale.is_fiscalized         = True
                                sale.fiscalization_time    = timezone.now()
                                sale.fiscalization_status  = 'fiscalized'
                                sale.fiscalized_by         = request.user
                                sale.save(update_fields=[
                                    'efris_invoice_number', 'verification_code', 'qr_code',
                                    'is_fiscalized', 'fiscalization_time',
                                    'fiscalization_status', 'fiscalized_by'
                                ])
                        else:
                            failed_count += 1
                            error_msg = invoice_result.get('invoiceReturnMessage') or invoice_result.get('returnMessage', 'Unknown error')
                            invoice.fiscalization_status = 'failed'
                            invoice.fiscalization_error  = error_msg
                            invoice.save(update_fields=['fiscalization_status', 'fiscalization_error'])
                            if invoice.sale:
                                invoice.sale.fiscalization_status = 'failed'
                                invoice.sale.save(update_fields=['fiscalization_status'])

                    except Exception as e:
                        failed_count += 1
                        logger.error(f"Error processing result for index {idx}: {e}", exc_info=True)

                messages.success(
                    request,
                    f"Batch upload completed: {success_count} successful, {failed_count} failed"
                )
                request.session['batch_upload_results'] = results_list
            else:
                messages.error(request, f"Batch upload failed: {result.get('error')}")

        except Exception as e:
            logger.error(f"Batch upload failed: {e}", exc_info=True)
            messages.error(request, f"Error: {str(e)}")

    # GET — load pending invoices
    try:
        from invoices.models import Invoice
        ctx['pending_invoices'] = Invoice.objects.filter(
            is_fiscalized=False,
            sale__status__in=['COMPLETED', 'PAID']
        ).select_related('sale', 'sale__customer', 'sale__store').order_by('-created_at')[:50]
    except Exception as e:
        logger.error(f"Failed to load pending invoices: {e}")
        ctx['pending_invoices'] = []

    # Batch results from previous upload (session)
    if 'batch_upload_results' in request.session:
        ctx['batch_results']       = request.session.pop('batch_upload_results')
        ctx['batch_total_count']   = len(ctx['batch_results'])
        ctx['batch_success_count'] = sum(1 for r in ctx['batch_results'] if r.get('invoiceReturnCode') == '00')
        ctx['batch_failed_count']  = sum(1 for r in ctx['batch_results'] if r.get('invoiceReturnCode') != '00')

    return ctx


def _tab_commodity_categories(request, company):
    ctx = {}
    if request.method == 'POST':
        try:
            current_version = request.POST.get('current_version', '1.0')
            client          = EnhancedEFRISAPIClient(company)
            result          = client.t134_get_commodity_category_incremental_update(current_version)
            if result.get('success'):
                categories    = result.get('categories', [])
                if categories:
                    updated_count = 0
                    for category in categories:
                        try:
                            from company.models import EFRISCommodityCategory
                            EFRISCommodityCategory.objects.update_or_create(
                                commodity_category_code=category.get('commodityCategoryCode'),
                                defaults={
                                    'commodity_category_name':  category.get('commodityCategoryName', ''),
                                    'parent_code':              category.get('parentCode', ''),
                                    'commodity_category_level': category.get('commodityCategoryLevel', '1'),
                                    'rate':                     category.get('rate', '0'),
                                    'is_leaf_node':             category.get('isLeafNode', '102'),
                                    'service_mark':             category.get('serviceMark', '102'),
                                    'is_zero_rate':             category.get('isZeroRate', '102'),
                                    'is_exempt':                category.get('isExempt', '102'),
                                    'enable_status_code':       category.get('enableStatusCode', '1'),
                                    'exclusion':                category.get('exclusion', '2'),
                                    'excisable':                category.get('excisable', '102'),
                                    'vat_out_scope_code':       category.get('vatOutScopeCode', '102'),
                                    'last_synced':              timezone.now(),
                                }
                            )
                            updated_count += 1
                        except Exception as cat_error:
                            logger.error(f"Failed to update category: {cat_error}")
                    messages.success(request, f"Successfully updated {updated_count} commodity categories")
                else:
                    messages.info(request, "No updates available. Your categories are up to date.")
            else:
                messages.error(request, f"Update failed: {result.get('error')}")
        except Exception as e:
            logger.error(f"Category update failed: {e}", exc_info=True)
            messages.error(request, f"Error: {str(e)}")

    try:
        from company.models import EFRISCommodityCategory
        ctx['total_categories'] = EFRISCommodityCategory.objects.count()
        ctx['last_sync']        = EFRISCommodityCategory.objects.order_by('-last_synced').first()
    except Exception:
        ctx['total_categories'] = 0
    return ctx


# ─────────────────────────────────────────────────────────────────────────────
# TAB DISPATCH TABLE
# ─────────────────────────────────────────────────────────────────────────────

TAB_HANDLERS = {
    'dashboard':            _tab_dashboard,
    'invoice_search':       _tab_invoice_search,
    'normal_invoices':      _tab_normal_invoices,
    'credit_notes':         _tab_credit_notes,
    'exception_logs':       _tab_exception_logs,
    'system_upgrade':       _tab_system_upgrade,
    'certificate_upload':   _tab_certificate_upload,
    'branches':             _tab_branches,
    'taxpayer_check':       _tab_taxpayer_check,
    'exchange_rates':       _tab_exchange_rates,
    'excise_duty':          _tab_excise_duty,
    'reports':              _tab_reports,
    'batch_upload':         _tab_batch_upload,
    'commodity_categories': _tab_commodity_categories,
}


# ─────────────────────────────────────────────────────────────────────────────
# THE ONE UNIFIED VIEW
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def efris_hub_view(request):
    """
    Single unified EFRIS view — all tabs handled here.
    URL: /efris/hub/?tab=<tab_name>

    Tab names:
        dashboard, invoice_search, normal_invoices, credit_notes,
        exception_logs, system_upgrade, certificate_upload, branches,
        taxpayer_check, exchange_rates, excise_duty, reports,
        batch_upload, commodity_categories
    """
    company = request.tenant

    if not _efris_guard(request, company):
        return redirect('dashboard')

    # Resolve active tab
    active_tab = request.GET.get('tab', DEFAULT_TAB)
    if active_tab not in TABS:
        active_tab = DEFAULT_TAB

    # Base context always available to every tab
    context = {
        'page_title':  TABS[active_tab],
        'company':     company,
        'active_tab':  active_tab,
        'tabs':        TABS,            # so the template can render the tab bar
        'status_class': CreditNoteStatus,
        'approval_class': ApprovalAction,
    }

    # Run the tab handler
    handler = TAB_HANDLERS[active_tab]
    result  = handler(request, company)

    # Some handlers return (ctx, should_reload) for POST-redirect-GET pattern
    if isinstance(result, tuple):
        tab_ctx, should_reload = result
        context.update(tab_ctx)
        if should_reload:
            return redirect(f"{request.path}?tab={active_tab}")
    else:
        context.update(result)

    return render(request, 'efris/hub.html', context)


# ─────────────────────────────────────────────────────────────────────────────
# UNCHANGED — JSON/AJAX ENDPOINTS (keep wired to their own URLs)
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@require_http_methods(["POST"])
def upload_exception_logs(request):
    company = request.tenant
    if not company.efris_enabled:
        return JsonResponse({'success': False, 'error': 'EFRIS is not enabled for your company'})
    try:
        client = EnhancedEFRISAPIClient(company)
        result = client.upload_pending_exception_logs_on_login()
        if result.get('success'):
            messages.success(request, f"Successfully uploaded {result.get('logs_count', 0)} exception logs")
        else:
            messages.error(request, f"Upload failed: {result.get('error')}")
        return JsonResponse(result)
    except Exception as e:
        logger.error(f"Exception log upload failed: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@require_http_methods(["POST"])
def download_upgrade_files(request):
    company = request.tenant
    if not company.efris_enabled:
        return JsonResponse({'success': False, 'error': 'EFRIS is not enabled for your company'})
    try:
        tcs_version = request.POST.get('tcs_version')
        os_type     = request.POST.get('os_type', '1')
        if not tcs_version:
            return JsonResponse({'success': False, 'error': 'TCS version is required'})
        client = EnhancedEFRISAPIClient(company)
        result = client.t133_download_tcs_upgrade_files(tcs_version, os_type)
        return JsonResponse(result)
    except Exception as e:
        logger.error(f"Upgrade file download failed: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def check_taxpayer_status_api(request):
    company = request.tenant
    if not company.efris_enabled:
        return JsonResponse({'success': False, 'error': 'EFRIS is not enabled for your company'})
    try:
        tin = request.GET.get('tin')
        if not tin:
            return JsonResponse({'success': False, 'error': 'TIN is required'})
        client = EnhancedEFRISAPIClient(company)
        return JsonResponse(client.t137_check_exempt_deemed_taxpayer(tin))
    except Exception as e:
        logger.error(f"API check failed: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def get_branches_api(request):
    company = request.tenant
    if not company.efris_enabled:
        return JsonResponse({'success': False, 'error': 'EFRIS is not enabled for your company'})
    try:
        client = EnhancedEFRISAPIClient(company)
        return JsonResponse(client.t138_get_all_branches())
    except Exception as e:
        logger.error(f"API query failed: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def get_exchange_rate_api(request):
    company = request.tenant
    if not company.efris_enabled:
        return JsonResponse({'success': False, 'error': 'EFRIS is not enabled for your company'})
    try:
        currency = request.GET.get('currency')
        if not currency:
            return JsonResponse({'success': False, 'error': 'Currency code is required'})
        client = EnhancedEFRISAPIClient(company)
        return JsonResponse(client.t121_get_exchange_rate(
            currency=currency, issue_date=request.GET.get('date')
        ))
    except Exception as e:
        logger.error(f"Exchange rate query failed: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def search_invoices_api(request):
    company = request.tenant
    if not company.efris_enabled:
        return JsonResponse({'success': False, 'error': 'EFRIS is not enabled for your company'})
    try:
        params = {
            'invoice_no':  request.GET.get('invoice_no'),
            'buyer_tin':   request.GET.get('buyer_tin'),
            'start_date':  request.GET.get('start_date'),
            'end_date':    request.GET.get('end_date'),
            'invoice_type':request.GET.get('invoice_type'),
            'page_no':     int(request.GET.get('page', 1)),
            'page_size':   int(request.GET.get('page_size', 20)),
        }
        params = {k: v for k, v in params.items() if v}
        client = EnhancedEFRISAPIClient(company)
        return JsonResponse(client.t106_query_invoices(**params))
    except Exception as e:
        logger.error(f"Invoice search API failed: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def check_invoice_eligibility_api(request):
    company = request.tenant
    if not company.efris_enabled:
        return JsonResponse({'success': False, 'error': 'EFRIS is not enabled for your company'})
    try:
        invoice_no = request.GET.get('invoice_no')
        if not invoice_no:
            return JsonResponse({'success': False, 'error': 'Invoice number is required'})
        client = EnhancedEFRISAPIClient(company)
        return JsonResponse(client.get_invoice_with_credit_note_eligibility(invoice_no))
    except Exception as e:
        logger.error(f"Eligibility check failed: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def query_cancel_credit_note_detail_api(request):
    company = request.tenant
    if not company.efris_enabled:
        return JsonResponse({'success': False, 'error': 'EFRIS is not enabled for your company'})
    try:
        invoice_no = request.GET.get('invoice_no')
        if not invoice_no:
            return JsonResponse({'success': False, 'error': 'Invoice number is required'})
        client = EnhancedEFRISAPIClient(company)
        return JsonResponse(client.t122_query_cancel_credit_note_detail(invoice_no))
    except Exception as e:
        logger.error(f"Query failed: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@require_http_methods(["POST"])
def approve_credit_note_application(request, application_id):
    company = request.tenant
    if not company.efris_enabled:
        return JsonResponse({'success': False, 'error': 'EFRIS is not enabled'}, status=403)
    try:
        if request.content_type == 'application/json':
            try:
                data = json.loads(request.body)
            except json.JSONDecodeError:
                return JsonResponse({'success': False, 'error': 'Invalid JSON data'}, status=400)
        else:
            data = request.POST

        reference_no    = data.get('reference_no', '').strip()
        approve_action  = data.get('approve_status', '').strip()
        task_id         = data.get('task_id', '').strip()
        remark          = data.get('remark', '').strip()

        missing = [f for f, v in [('reference_no', reference_no), ('approve_status', approve_action), ('remark', remark)] if not v]
        if missing:
            return JsonResponse({'success': False, 'error': f"Missing: {', '.join(missing)}"}, status=400)
        if approve_action not in ['101', '103']:
            return JsonResponse({'success': False, 'error': 'Invalid approval action'}, status=400)
        if len(remark) > 1024:
            return JsonResponse({'success': False, 'error': f'Remark too long ({len(remark)} chars)'}, status=400)

        client       = EnhancedEFRISAPIClient(company)
        status_check = client.t112_query_credit_note_application_detail(application_id)
        if not status_check.get('success'):
            return JsonResponse({'success': False, 'error': f"Could not get details: {status_check.get('error')}"}, status=400)

        detail          = status_check.get('application_detail', {})
        current_status  = detail.get('approveStatusCode')
        if not task_id:
            task_id = detail.get('taskId', '')
        if not task_id:
            return JsonResponse({'success': False, 'error': 'Task ID not found'}, status=400)

        t112_ref = detail.get('referenceNo', '')
        if t112_ref and t112_ref != reference_no:
            reference_no = t112_ref

        if current_status != '102':
            status_names = {'101': 'Approved', '102': 'Pending', '103': 'Rejected'}
            return JsonResponse({'success': False, 'error': f'Status is {status_names.get(current_status, current_status)}'}, status=400)

        result         = client.t113_approve_credit_note_application(
            reference_no=reference_no, approve_status=approve_action,
            task_id=task_id, remark=remark
        )
        action_display = 'Approved' if approve_action == '101' else 'Rejected'

        try:
            FiscalizationAudit.objects.create(
                company=company, user=request.user,
                action=f'CREDIT_NOTE_{action_display.upper()}',
                efris_return_code='00' if result.get('success') else result.get('error_code', 'ERROR'),
                efris_return_message=f"Application {reference_no} {action_display}",
                request_data=json.dumps({'reference_no': reference_no, 'approve_action': approve_action, 'application_id': application_id})
            )
        except Exception as audit_error:
            logger.error(f"Audit logging failed: {audit_error}")

        if result.get('success'):
            return JsonResponse({'success': True, 'message': result.get('message', f'{action_display} successfully'), 'status': action_display})
        else:
            return JsonResponse({'success': False, 'error': result.get('error', 'Unknown error'), 'error_code': result.get('error_code')}, status=400)

    except Exception as e:
        logger.error(f"Exception in approval: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': f'System error: {str(e)}'}, status=500)


@login_required
@require_http_methods(["POST"])
def cancel_credit_debit_note(request):
    company = request.tenant
    if not company.efris_enabled:
        return JsonResponse({'success': False, 'error': 'EFRIS is not enabled'})
    try:
        ori_invoice_id = request.POST.get('ori_invoice_id')
        invoice_no     = request.POST.get('invoice_no')
        reason_code    = request.POST.get('reason_code')
        category_code  = request.POST.get('category_code')
        reason         = request.POST.get('reason')
        if not all([ori_invoice_id, invoice_no, reason_code, category_code]):
            return JsonResponse({'success': False, 'error': 'Missing required fields'})
        attachments = []
        if request.FILES.get('attachment'):
            import base64
            f = request.FILES['attachment']
            attachments.append({
                'fileName': f.name, 'fileType': f.name.split('.')[-1].lower(),
                'fileContent': base64.b64encode(f.read()).decode('utf-8')
            })
        client = EnhancedEFRISAPIClient(company)
        result = client.t114_cancel_credit_debit_note(
            ori_invoice_id=ori_invoice_id, invoice_no=invoice_no, reason_code=reason_code,
            invoice_apply_category_code=category_code, reason=reason,
            attachment_list=attachments or None
        )
        return JsonResponse({'success': result.get('success'), 'message': result.get('message'), 'error': result.get('error')})
    except Exception as e:
        logger.error(f"Cancellation failed: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
@require_http_methods(["POST"])
def void_credit_note_application(request):
    company = request.tenant
    if not company.efris_enabled:
        return JsonResponse({'success': False, 'error': 'EFRIS is not enabled'})
    try:
        business_key = request.POST.get('business_key')
        reference_no = request.POST.get('reference_no')
        if not all([business_key, reference_no]):
            return JsonResponse({'success': False, 'error': 'Missing required fields'})
        client = EnhancedEFRISAPIClient(company)
        result = client.t120_void_credit_debit_note_application(business_key=business_key, reference_no=reference_no)
        return JsonResponse({'success': result.get('success'), 'message': result.get('message'), 'error': result.get('error')})
    except Exception as e:
        logger.error(f"Void failed: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)})


# ─────────────────────────────────────────────────────────────────────────────
# UNCHANGED — DETAIL / PRINT VIEWS (per-record, not in hub)
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def invoice_detail_view(request, invoice_no):
    company = request.tenant
    if not company.efris_enabled:
        messages.error(request, "EFRIS is not enabled for your company")
        return redirect('dashboard')
    try:
        with EnhancedEFRISAPIClient(company) as client:
            result = client.t108_query_invoice_detail(invoice_no)
            logger.info("EFRIS T108 Invoice Response for %s:\n%s", invoice_no, json.dumps(result, indent=4, default=str))
            if result.get('success'):
                invoice_data = result.get('invoice')
                if not invoice_data:
                    messages.error(request, f"Invoice {invoice_no} not found in EFRIS")
                    return redirect('efris:hub')
                return render(request, 'efris/invoice_detail.html', {
                    'page_title': f'Invoice Details - {invoice_no}',
                    'invoice': invoice_data, 'invoice_no': invoice_no, 'company': company
                })
            else:
                messages.error(request, f"Failed to load invoice: {result.get('error', 'Unknown error')}")
                return redirect('efris:hub')
    except Exception as e:
        logger.error(f"Invoice detail view failed for {invoice_no}: {e}", exc_info=True)
        messages.error(request, f"Error loading invoice: {str(e)}")
        return redirect('efris:hub')


@login_required
def credit_note_application_detail_view(request, application_id):
    company = request.tenant
    if not company.efris_enabled:
        messages.error(request, "EFRIS is not enabled for your company")
        return redirect('dashboard')
    try:
        client      = EnhancedEFRISAPIClient(company)
        invoice_no  = request.GET.get('invoice_no') or application_id
        if not invoice_no:
            messages.error(request, "Invoice number is required")
            return redirect('efris:hub')

        basic_result = client.t108_query_invoice_detail(invoice_no)
        if not basic_result.get('success'):
            messages.error(request, f"Failed to load application: {basic_result.get('error') or 'Unknown error'}")
            return redirect('efris:hub')

        invoice         = basic_result.get('invoice', {})
        basic_info_raw  = invoice.get('basicInformation', {})
        buyer           = invoice.get('buyerDetails', {})
        seller          = invoice.get('sellerDetails', {})
        extend          = invoice.get('extend', {})
        credit_extend   = invoice.get('creditNoteExtend', {})
        raw_summary     = invoice.get('summary', {})
        goods_details   = invoice.get('goodsDetails', [])
        tax_details     = invoice.get('taxDetails', [])
        payment_methods = invoice.get('payWay', [])

        credit_note_no      = basic_info_raw.get('invoiceNo')
        original_invoice_no = basic_info_raw.get('oriInvoiceNo')
        reason_code         = str(extend.get('reasonCode') or '')
        is_refund           = basic_info_raw.get('isRefund') == '1'
        is_invalid          = basic_info_raw.get('isInvalid') == '1'

        basic_info = {
            'application_id': application_id, 'credit_note_no': credit_note_no,
            'original_invoice_no': original_invoice_no,
            'issued_date': basic_info_raw.get('issuedDate'),
            'ori_issued_date': basic_info_raw.get('oriIssuedDate'),
            'currency': basic_info_raw.get('currency', 'UGX'),
            'operator': basic_info_raw.get('operator'), 'device_no': basic_info_raw.get('deviceNo'),
            'antifake_code': basic_info_raw.get('antifakeCode'),
            'is_invalid': is_invalid, 'is_refund': is_refund,
            'reason_code': reason_code, 'reason_description': REASON_CODES.get(reason_code, f'Code: {reason_code}'),
            'reason': extend.get('reason') or raw_summary.get('remarks'),
            'remarks': raw_summary.get('remarks'),
            'applicant_tin': seller.get('tin'), 'applicant_name': seller.get('legalName') or seller.get('businessName'),
            'address': seller.get('address'),
            'buyer_tin': buyer.get('buyerTin'), 'buyer_name': buyer.get('buyerLegalName') or buyer.get('buyerBusinessName'),
            'buyer_email': buyer.get('buyerEmailAddress') or buyer.get('buyerEmail'),
            'buyer_mobile': buyer.get('buyerMobilePhone'),
            'gross_amount': float(raw_summary.get('grossAmount') or 0),
            'net_amount': float(raw_summary.get('netAmount') or 0),
            'tax_amount': float(raw_summary.get('taxAmount') or 0),
            'qr_code': raw_summary.get('qrCode'),
            'approve_status': None, 'status': 'Invalid' if is_invalid else 'Issued',
            'can_approve': False, 'approve_remarks': None, 'task_id': None, 'validation_errors': [],
            'contact_name': buyer.get('buyerLegalName'), 'contact_mobile': buyer.get('buyerMobilePhone'),
            'contact_email': buyer.get('buyerEmailAddress'),
        }
        summary = {
            'gross_amount': float(raw_summary.get('grossAmount') or 0),
            'net_amount': float(raw_summary.get('netAmount') or 0),
            'tax_amount': float(raw_summary.get('taxAmount') or 0),
            'previous_gross_amount': float(credit_extend.get('preGrossAmount') or 0),
            'previous_net_amount': float(credit_extend.get('preNetAmount') or 0),
            'previous_tax_amount': float(credit_extend.get('preTaxAmount') or 0),
            'remarks': raw_summary.get('remarks'),
            'item_count': int(raw_summary.get('itemCount') or len(goods_details)),
            'qr_code': raw_summary.get('qrCode'),
        }
        return render(request, 'efris/credit_note_application_detail.html', {
            'page_title': f'Credit Note {credit_note_no}',
            'application': basic_info, 'goods_details': goods_details,
            'tax_details': tax_details, 'summary': summary,
            'payment_methods': payment_methods, 'application_id': application_id,
            'company': company, 'debug': request.GET.get('debug', False),
            'status_class': CreditNoteStatus, 'approval_class': ApprovalAction,
        })
    except Exception as e:
        logger.error(f"Application detail failed: {e}", exc_info=True)
        messages.error(request, f"Error: {str(e)}")
        return redirect('efris:hub')


@login_required
def refresh_application_status(request, application_id):
    company = request.tenant
    if not company.efris_enabled:
        messages.error(request, "EFRIS is not enabled for your company")
        return redirect('efris:hub')
    try:
        client  = EnhancedEFRISAPIClient(company)
        result  = client.t112_query_credit_note_application_detail(application_id)
        if result.get('success'):
            status = result.get('application_detail', {}).get('approveStatusCode')
            messages.success(request, f"Status refreshed: {CreditNoteStatus.get_display(status)}")
        else:
            messages.error(request, f"Failed to refresh status: {result.get('error')}")
    except Exception as e:
        logger.error(f"Status refresh failed: {e}", exc_info=True)
        messages.error(request, f"Error refreshing status: {str(e)}")
    return redirect('efris:credit_note_application_detail', application_id=application_id)


# ─────────────────────────────────────────────────────────────────────────────
# EXPORT VIEWS (keep their own URLs — they return file downloads)
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def export_invoices_csv(request):
    import csv
    company = request.tenant
    if not company.efris_enabled:
        messages.error(request, "EFRIS is not enabled for your company")
        return redirect('dashboard')
    try:
        client = EnhancedEFRISAPIClient(company)
        result = client.search_invoices_by_date_range(
            start_date=request.GET.get('start_date'), end_date=request.GET.get('end_date'),
            invoice_type=request.GET.get('invoice_type'), page_size=100
        )
        if not result.get('success'):
            messages.error(request, f"Export failed: {result.get('error')}")
            return redirect('efris:hub')
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="efris_invoices_{timezone.now().strftime("%Y%m%d")}.csv"'
        writer = csv.writer(response)
        writer.writerow(['Invoice No', 'Issue Date', 'Buyer TIN', 'Buyer Name', 'Currency', 'Gross Amount', 'Tax Amount', 'Invoice Type', 'Status'])
        for inv in result.get('invoices', []):
            writer.writerow([
                inv.get('invoiceNo', ''), inv.get('issuedDate', ''), inv.get('buyerTin', ''),
                inv.get('buyerLegalName', ''), inv.get('currency', ''), inv.get('grossAmount', ''),
                inv.get('taxAmount', ''), inv.get('invoiceType', ''),
                'Invalid' if inv.get('isInvalid') == '1' else 'Valid'
            ])
        return response
    except Exception as e:
        logger.error(f"CSV export failed: {e}", exc_info=True)
        messages.error(request, f"Export error: {str(e)}")
        return redirect('efris:hub')


@login_required
def export_credit_notes_pdf(request):
    from django.template.loader import render_to_string
    from weasyprint import HTML
    company = request.tenant
    if not company.efris_enabled:
        messages.error(request, "EFRIS is not enabled for your company")
        return redirect('dashboard')
    try:
        client = EnhancedEFRISAPIClient(company)
        result = client.t111_query_credit_note_applications(
            start_date=request.GET.get('start_date'), end_date=request.GET.get('end_date'), page_size=100
        )
        if not result.get('success'):
            messages.error(request, f"Export failed: {result.get('error')}")
            return redirect('efris:hub')
        html_string = render_to_string('efris/pdf/credit_notes_report.html', {
            'company': company, 'applications': result.get('applications', []),
            'start_date': request.GET.get('start_date'), 'end_date': request.GET.get('end_date'),
            'generated_at': timezone.now()
        })
        result_pdf = HTML(string=html_string).write_pdf()
        response = HttpResponse(result_pdf, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="credit_notes_{timezone.now().strftime("%Y%m%d")}.pdf"'
        return response
    except Exception as e:
        logger.error(f"PDF export failed: {e}", exc_info=True)
        messages.error(request, f"Export error: {str(e)}")
        return redirect('efris:hub')


# ─────────────────────────────────────────────────────────────────────────────
# COMPATIBILITY REDIRECTS
# Keep old URL names working by adding these to urls.py as redirect views,
# OR just point old URL names to efris_hub_view with a tab kwarg.
#
# Example urls.py:
#
#   from django.views.generic import RedirectView
#   from django.urls import reverse_lazy
#
#   urlpatterns = [
#       path('hub/', views.efris_hub_view, name='hub'),
#       path('hub/<str:tab>/', views.efris_hub_view, name='hub_tab'),  # optional
#
#       # Old URLs → redirect to hub tab
#       path('dashboard/',         views.tab_redirect('dashboard'),          name='dashboard'),
#       path('invoice-search/',    views.tab_redirect('invoice_search'),     name='invoice_search'),
#       path('normal-invoices/',   views.tab_redirect('normal_invoices'),    name='normal_invoices'),
#       path('credit-notes/',      views.tab_redirect('credit_notes'),       name='credit_note_applications'),
#       path('exception-logs/',    views.tab_redirect('exception_logs'),     name='exception_logs'),
#       path('system-upgrade/',    views.tab_redirect('system_upgrade'),     name='system_upgrade'),
#       path('certificate/',       views.tab_redirect('certificate_upload'), name='certificate_upload'),
#       path('branches/',          views.tab_redirect('branches'),           name='branches_list'),
#       path('taxpayer/',          views.tab_redirect('taxpayer_check'),     name='taxpayer_exemption_check'),
#       path('exchange-rates/',    views.tab_redirect('exchange_rates'),     name='exchange_rates'),
#       path('excise-duty/',       views.tab_redirect('excise_duty'),        name='excise_duty_list'),
#       path('reports/',           views.tab_redirect('reports'),            name='reports'),
#       path('batch-upload/',      views.tab_redirect('batch_upload'),       name='batch_invoice_upload'),
#       path('categories/',        views.tab_redirect('commodity_categories'), name='commodity_category_updates'),
#
#       # Per-record views stay as-is
#       path('invoices/<str:invoice_no>/',           views.invoice_detail_view,                 name='invoice_detail'),
#       path('credit-notes/<str:application_id>/',   views.credit_note_application_detail_view, name='credit_note_application_detail'),
#       path('credit-notes/<str:application_id>/print/', views.print_credit_note,               name='print_credit_note'),
#
#       # JSON endpoints stay as-is
#       path('api/upload-exception-logs/',    views.upload_exception_logs,              name='upload_exception_logs'),
#       path('api/download-upgrade/',         views.download_upgrade_files,             name='download_upgrade_files'),
#       path('api/taxpayer-status/',          views.check_taxpayer_status_api,          name='check_taxpayer_status_api'),
#       path('api/branches/',                 views.get_branches_api,                   name='get_branches_api'),
#       path('api/exchange-rate/',            views.get_exchange_rate_api,              name='get_exchange_rate_api'),
#       path('api/invoices/search/',          views.search_invoices_api,                name='search_invoices_api'),
#       path('api/invoices/eligibility/',     views.check_invoice_eligibility_api,      name='check_invoice_eligibility'),
#       path('api/credit-notes/<str:application_id>/approve/', views.approve_credit_note_application, name='approve_credit_note_application'),
#       path('api/credit-notes/cancel/',      views.cancel_credit_debit_note,           name='cancel_credit_debit_note'),
#       path('api/credit-notes/void/',        views.void_credit_note_application,       name='void_credit_note_application'),
#       path('api/cancel-detail/',            views.query_cancel_credit_note_detail_api,name='query_cancel_credit_note_detail'),
#
#       # Exports
#       path('export/invoices.csv',  views.export_invoices_csv,   name='export_invoices_csv'),
#       path('export/credit-notes.pdf', views.export_credit_notes_pdf, name='export_credit_notes_pdf'),
#   ]
# ─────────────────────────────────────────────────────────────────────────────

def tab_redirect(tab_name):
    """Helper: returns a view that redirects old URLs to the hub with the right tab."""
    @login_required
    def _view(request, **kwargs):
        return redirect(f"/efris/hub/?tab={tab_name}")
    return _view