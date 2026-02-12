from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from datetime import datetime, timedelta
from .services import EnhancedEFRISAPIClient
from company.models import Company
import json
import logging

logger=logging.getLogger(__name__)

@login_required
def credit_note_application(request):
    """T110 - Apply Credit Note (Detailed Form)"""
    company = request.tenant

    if not company.efris_enabled:
        messages.error(request, "EFRIS is not enabled for your company")
        return redirect('dashboard')

    if request.method == 'POST':
        original_invoice_no = request.POST.get('original_invoice_no')
        reason_code = request.POST.get('reason_code')
        reason = request.POST.get('reason')
        credit_type = request.POST.get('credit_type', 'full')

        contact_name = request.POST.get('contact_name')
        contact_mobile = request.POST.get('contact_mobile')
        contact_email = request.POST.get('contact_email')
        remarks = request.POST.get('remarks')

        try:
            with EnhancedEFRISAPIClient(company) as client:
                # Build credit note data
                if credit_type == 'full':
                    build_result = client.build_credit_note_from_invoice(
                        original_invoice_no=original_invoice_no,
                        reason_code=reason_code,
                        reason=reason if reason_code == '105' else None,
                        contact_name=contact_name,
                        contact_mobile=contact_mobile,
                        contact_email=contact_email,
                        remarks=remarks
                    )
                else:
                    # Partial credit note
                    credit_items = []
                    item_count = int(request.POST.get('item_count', 0))

                    for i in range(item_count):
                        item_name = request.POST.get(f'item_name_{i}')
                        item_qty = request.POST.get(f'item_qty_{i}')

                        if item_name and item_qty:
                            qty_value = float(item_qty)
                            if qty_value > 0:
                                qty_value = -qty_value

                            credit_items.append({
                                'item': item_name,
                                'qty': qty_value
                            })

                    if not credit_items:
                        messages.error(request, "No items selected for partial credit note")
                        return redirect('efris:credit_note_application')

                    build_result = client.build_credit_note_from_invoice(
                        original_invoice_no=original_invoice_no,
                        reason_code=reason_code,
                        reason=reason if reason_code == '105' else None,
                        credit_items=credit_items,
                        contact_name=contact_name,
                        contact_mobile=contact_mobile,
                        contact_email=contact_email,
                        remarks=remarks
                    )

                if not build_result.get('success'):
                    messages.error(request, f"Failed to build credit note: {build_result.get('error')}")
                    return redirect('efris:credit_note_application')

                # Apply credit note
                credit_note_data = build_result['credit_note_data']
                result = client.t110_apply_credit_note(credit_note_data)

                if result.get('success'):
                    # Save record
                    try:
                        from efris.models import CreditNoteApplication
                        CreditNoteApplication.objects.create(
                            company=company,
                            original_invoice_no=original_invoice_no,
                            original_invoice_id=credit_note_data.get('oriInvoiceId', ''),
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
                        f"✓ Credit note submitted! Reference: {result.get('reference_no')}"
                    )
                    return redirect('efris:dashboard')
                else:
                    messages.error(request, f"Application failed: {result.get('error')}")

        except Exception as e:
            logger.error(f"Credit note application error: {e}", exc_info=True)
            messages.error(request, f"Error: {str(e)}")

    # GET request
    return render(request, 'efris/advanced/credit_note_application.html', {
        'page_title': 'Apply Credit Note',
        'reason_codes': [
            ('101', 'Return of products due to expiry or damage'),
            ('102', 'Cancellation of the purchase'),
            ('103', 'Invoice amount wrongly stated'),
            ('104', 'Partial or complete waive off'),
            ('105', 'Others (Please specify)')
        ]
    })


@login_required
@require_http_methods(["POST"])
def api_get_invoice_for_credit_note(request):
    """
    AJAX endpoint to fetch invoice details for credit note
    FIXED: Query EFRIS directly via T108 instead of local database
    """
    company = request.tenant

    try:
        data = json.loads(request.body)
        invoice_no = data.get('invoice_no')

        if not invoice_no:
            return JsonResponse({
                'success': False,
                'error': 'Invoice number is required'
            }, status=400)

        logger.info(f"Fetching invoice {invoice_no} from EFRIS for credit note")

        # ✅ QUERY EFRIS DIRECTLY USING T108
        with EnhancedEFRISAPIClient(company) as client:
            result = client.t108_query_invoice_detail(invoice_no)

            if not result.get('success'):
                return JsonResponse({
                    'success': False,
                    'error': result.get('error', f'Invoice {invoice_no} not found in EFRIS')
                })

            invoice_data = result.get('invoice')

            if not invoice_data:
                return JsonResponse({
                    'success': False,
                    'error': f'Invoice {invoice_no} not found in EFRIS'
                })

            # ✅ Extract data from EFRIS T108 response
            basic_info = invoice_data.get('basicInformation', {})
            buyer_details = invoice_data.get('buyerDetails', {})
            goods_details = invoice_data.get('goodsDetails', [])
            summary = invoice_data.get('summary', {})

            # ✅ Get EFRIS invoice ID (required for credit note)
            efris_invoice_id = basic_info.get('invoiceId')

            if not efris_invoice_id:
                return JsonResponse({
                    'success': False,
                    'error': f'Invoice {invoice_no} is missing EFRIS invoice ID'
                })

            # ✅ Build items list from EFRIS goods details
            items = []
            for item in goods_details:
                items.append({
                    'item': item.get('item', ''),
                    'itemCode': item.get('itemCode', ''),
                    'qty': float(item.get('qty', 0)),
                    'remainQty': float(item.get('qty', 0)),  # For partial credits
                    'unitOfMeasure': item.get('unitOfMeasure', '101'),
                    'unitPrice': item.get('unitPrice', '0.00'),
                    'total': item.get('total', '0.00'),
                    'remainAmount': item.get('total', '0.00'),
                    'taxRate': item.get('taxRate', '0.18'),
                    'tax': item.get('tax', '0.00')
                })

            # ✅ Return structured response
            return JsonResponse({
                'success': True,
                'invoice': {
                    'invoiceNo': invoice_no,
                    'efrisInvoiceId': efris_invoice_id,
                    'items': items,
                    'currency': basic_info.get('currency', 'UGX'),
                    'grossAmount': summary.get('grossAmount', '0.00'),
                    'netAmount': summary.get('netAmount', '0.00'),
                    'taxAmount': summary.get('taxAmount', '0.00'),
                    'buyer': buyer_details.get('buyerLegalName', 'Walk-in Customer'),
                    'buyerTin': buyer_details.get('buyerTin', ''),
                    'issueDate': basic_info.get('issuedDate', '')
                }
            })

    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid JSON data'
        }, status=400)
    except Exception as e:
        logger.error(f"Error fetching invoice for credit note: {e}", exc_info=True)

        return JsonResponse({
            'success': False,
            'error': f'Server error: {str(e)}'
        }, status=500)


@login_required
def credit_note_application_status(request, reference_no):
    """Check status of credit note application"""
    company = request.tenant

    try:
        with EnhancedEFRISAPIClient(company) as client:
            # Query using T111
            result = client.t111_query_credit_note_applications(
                reference_no=reference_no,
                query_type="1",  # My applications
                page_size=1
            )

            if result.get('success'):
                applications = result.get('applications', [])
                if applications:
                    application = applications[0]

                    # FIX: Use correct status mapping per EFRIS T111 documentation
                    # 101 = Approved, 102 = Submitted/Pending, 103 = Rejected, 104 = Voided
                    status_mapping = {
                        '101': 'Approved',
                        '102': 'Submitted/Pending',
                        '103': 'Rejected',
                        '104': 'Voided/Cancelled',
                        '105': 'Processed',
                    }

                    app_status = application.get('approveStatus')
                    application['status_display'] = status_mapping.get(app_status, f"Unknown ({app_status})")

                    # Add reason description if available
                    reason_codes = {
                        '101': 'Return of products due to expiry or damage',
                        '102': 'Cancellation of the purchase',
                        '103': 'Invoice amount wrongly stated',
                        '104': 'Partial or complete waive off',
                        '105': 'Others',
                    }

                    reason_code = application.get('invoiceApplyCategoryCode')
                    if reason_code in reason_codes:
                        application['reason_description'] = reason_codes[reason_code]

                    # Try to get detailed info from T112 using the ID field
                    application_id = application.get('id')
                    detailed_info = {}
                    if application_id:
                        try:
                            detail_result = client.t112_query_credit_note_application_detail(application_id)
                            if detail_result.get('success'):
                                detailed_info = detail_result.get('application_detail', {})
                                logger.info(f"T112 details retrieved for ID {application_id}")
                            else:
                                logger.warning(f"T112 failed for ID {application_id}: {detail_result.get('error')}")
                        except Exception as detail_error:
                            logger.warning(f"Could not get T112 details for ID {application_id}: {detail_error}")

                    # Merge detailed info with application data
                    if detailed_info:
                        application['detailed_reason'] = detailed_info.get('reason')
                        application['approveRemarks'] = detailed_info.get('approveRemarks')
                        application['remarks'] = detailed_info.get('remarks')
                        application['contactName'] = detailed_info.get('contactName')
                        application['contactEmail'] = detailed_info.get('contactEmail')
                        application['contactMobileNum'] = detailed_info.get('contactMobileNum')

                    # Add some debug info for troubleshooting
                    application['debug_info'] = {
                        'reference_no_from_url': reference_no,
                        'application_id': application_id,
                        'has_t112_details': bool(detailed_info),
                        'approve_status': app_status,
                    }

                    return render(request, 'efris/advanced/credit_note_status.html', {
                        'page_title': f'Credit Note Status: {reference_no}',
                        'application': application,
                        'reference_no': reference_no,
                        'company': company,
                        'debug': request.GET.get('debug', False),
                    })
                else:
                    messages.warning(request, f"No application found with reference: {reference_no}")
            else:
                messages.error(request, f"Query failed: {result.get('error')}")
    except Exception as e:
        logger.error(f"Status check failed for {reference_no}: {e}", exc_info=True)
        messages.error(request, f"Error: {str(e)}")

    return redirect('efris:credit_note_applications')

@login_required
def commodity_category_by_date(request):
    """T146 - Query Commodity Category/Excise Duty by Date"""
    company = request.tenant

    if request.method == 'POST':
        category_code = request.POST.get('category_code')
        query_type = request.POST.get('query_type')
        issue_date = request.POST.get('issue_date')

        try:
            with EnhancedEFRISAPIClient(company) as client:
                result = client.t146_query_commodity_category_excise_by_date(
                    category_code=category_code,
                    query_type=query_type,
                    issue_date=issue_date
                )

                if result.get('success'):
                    messages.success(request, f"Query successful")
                    return render(request, 'efris/advanced/commodity_category_date_result.html', {
                        'page_title': 'Commodity Category/Excise Duty Result',
                        'result': result
                    })
                else:
                    messages.error(request, f"Query failed: {result.get('error')}")
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")

    return render(request, 'efris/advanced/commodity_category_by_date.html', {
        'page_title': 'Query Commodity Category/Excise Duty by Date'
    })


@login_required
def fuel_types_list(request):
    """T162 - Query Fuel Types"""
    company = request.tenant

    try:
        with EnhancedEFRISAPIClient(company) as client:
            result = client.t162_query_fuel_types()

            if result.get('success'):
                return render(request, 'efris/advanced/fuel_types.html', {
                    'page_title': 'Fuel Types',
                    'fuel_types': result.get('fuel_types', [])
                })
            else:
                messages.error(request, f"Failed to fetch fuel types: {result.get('error')}")
    except Exception as e:
        messages.error(request, f"Error: {str(e)}")

    return render(request, 'efris/advanced/fuel_types.html', {
        'page_title': 'Fuel Types',
        'fuel_types': []
    })


@login_required
def upload_shift_information(request):
    """T163 - Upload Shift Information"""
    company = request.tenant

    if request.method == 'POST':
        shift_data = {
            'shiftNo': request.POST.get('shift_no'),
            'startVolume': request.POST.get('start_volume'),
            'endVolume': request.POST.get('end_volume'),
            'fuelType': request.POST.get('fuel_type'),
            'goodsId': request.POST.get('goods_id'),
            'goodsCode': request.POST.get('goods_code'),
            'invoiceAmount': request.POST.get('invoice_amount'),
            'invoiceNumber': request.POST.get('invoice_number'),
            'nozzleNo': request.POST.get('nozzle_no'),
            'pumpNo': request.POST.get('pump_no'),
            'tankNo': request.POST.get('tank_no'),
            'userName': request.POST.get('user_name'),
            'userCode': request.POST.get('user_code'),
            'startTime': request.POST.get('start_time'),
            'endTime': request.POST.get('end_time')
        }

        try:
            with EnhancedEFRISAPIClient(company) as client:
                result = client.t163_upload_shift_information(shift_data)

                if result.get('success'):
                    messages.success(request, "Shift information uploaded successfully")
                    return redirect('efris:upload_shift_information')
                else:
                    messages.error(request, f"Upload failed: {result.get('error')}")
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")

    return render(request, 'efris/advanced/upload_shift_information.html', {
        'page_title': 'Upload Shift Information'
    })


@login_required
def update_buyer_details(request):
    """T166 - Update Buyer Details"""
    company = request.tenant

    if request.method == 'POST':
        buyer_data = {
            'invoiceNo': request.POST.get('invoice_no'),
            'buyerTin': request.POST.get('buyer_tin'),
            'buyerNinBrn': request.POST.get('buyer_nin_brn'),
            'buyerPassportNum': request.POST.get('buyer_passport_num'),
            'buyerLegalName': request.POST.get('buyer_legal_name'),
            'buyerBusinessName': request.POST.get('buyer_business_name'),
            'buyerAddress': request.POST.get('buyer_address'),
            'buyerEmailAddress': request.POST.get('buyer_email'),
            'buyerMobilePhone': request.POST.get('buyer_mobile'),
            'buyerLinePhone': request.POST.get('buyer_line_phone'),
            'buyerPlaceOfBusi': request.POST.get('buyer_place_of_business'),
            'buyerType': request.POST.get('buyer_type'),
            'buyerCitizenship': request.POST.get('buyer_citizenship'),
            'buyerSector': request.POST.get('buyer_sector'),
            'mvrn': request.POST.get('mvrn'),
            'createDateStr': request.POST.get('create_date')
        }

        # Remove empty values
        buyer_data = {k: v for k, v in buyer_data.items() if v}

        try:
            with EnhancedEFRISAPIClient(company) as client:
                result = client.t166_update_buyer_details(buyer_data)

                if result.get('success'):
                    messages.success(request, f"Buyer details updated for invoice {buyer_data['invoiceNo']}")
                    return redirect('efris:update_buyer_details')
                else:
                    messages.error(request, f"Update failed: {result.get('error')}")
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")

    return render(request, 'efris/advanced/update_buyer_details.html', {
        'page_title': 'Update Buyer Details'
    })


@login_required
def edc_invoice_inquiry(request):
    """T167 - EDC Invoice Inquiry"""
    company = request.tenant

    invoices = []
    pagination = {}

    if request.method == 'GET' and request.GET.get('search'):
        fuel_type = request.GET.get('fuel_type')
        invoice_no = request.GET.get('invoice_no')
        buyer_name = request.GET.get('buyer_name')
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        query_type = request.GET.get('query_type', '1')
        page_no = int(request.GET.get('page', 1))

        try:
            with EnhancedEFRISAPIClient(company) as client:
                result = client.t167_edc_invoice_inquiry(
                    fuel_type=fuel_type,
                    invoice_no=invoice_no,
                    buyer_legal_name=buyer_name,
                    start_date=start_date,
                    end_date=end_date,
                    query_type=query_type,
                    page_no=page_no,
                    page_size=20
                )

                if result.get('success'):
                    invoices = result.get('invoices', [])
                    pagination = result.get('pagination', {})
                else:
                    messages.error(request, f"Search failed: {result.get('error')}")
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")

    return render(request, 'efris/advanced/edc_invoice_inquiry.html', {
        'page_title': 'EDC Invoice Inquiry',
        'invoices': invoices,
        'pagination': pagination
    })


@login_required
def fuel_equipment_query(request):
    """T169 - Query Fuel Equipment by Pump"""
    company = request.tenant
    equipment_data = None

    if request.method == 'POST':
        pump_id = request.POST.get('pump_id')

        try:
            with EnhancedEFRISAPIClient(company) as client:
                result = client.t169_query_fuel_equipment_by_pump(pump_id)

                if result.get('success'):
                    equipment_data = result
                    messages.success(request, f"Equipment data retrieved for pump {pump_id}")
                else:
                    messages.error(request, f"Query failed: {result.get('error')}")
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")

    return render(request, 'efris/advanced/fuel_equipment_query.html', {
        'page_title': 'Fuel Equipment Query',
        'equipment_data': equipment_data
    })



@login_required
def efd_location_query(request):
    """T170 - Query EFD Location"""
    company = request.tenant
    locations = []

    if request.method == 'POST':
        device_number = request.POST.get('device_number')
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')

        try:
            with EnhancedEFRISAPIClient(company) as client:
                result = client.t170_query_efd_location(
                    device_number=device_number,
                    start_date=start_date,
                    end_date=end_date
                )

                if result.get('success'):
                    locations = result.get('locations', [])
                    messages.success(request, f"Retrieved {len(locations)} location records")
                else:
                    messages.error(request, f"Query failed: {result.get('error')}")
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")

    # FIX: This return statement was missing before
    return render(request, 'efris/advanced/efd_location_query.html', {
        'page_title': 'EFD Location Query',
        'locations': locations
    })

@login_required
def frequent_contacts_management(request):
    """T181/T182 - Manage Frequent Contacts"""
    company = request.tenant
    contacts = []

    # Get contacts (T182)
    try:
        with EnhancedEFRISAPIClient(company) as client:
            result = client.t182_get_frequent_contacts()
            if result.get('success'):
                contacts = result.get('contacts', [])
    except Exception as e:
        messages.error(request, f"Error fetching contacts: {str(e)}")

    # Handle contact operations (T181)
    if request.method == 'POST':
        operation_type = request.POST.get('operation_type')

        contact_data = {
            'buyerType': request.POST.get('buyer_type'),
            'buyerTin': request.POST.get('buyer_tin'),
            'buyerNinBrn': request.POST.get('buyer_nin_brn'),
            'buyerLegalName': request.POST.get('buyer_legal_name'),
            'buyerBusinessName': request.POST.get('buyer_business_name'),
            'buyerEmail': request.POST.get('buyer_email'),
            'buyerLinePhone': request.POST.get('buyer_line_phone'),
            'buyerAddress': request.POST.get('buyer_address'),
            'buyerCitizenship': request.POST.get('buyer_citizenship'),
            'buyerPassportNum': request.POST.get('buyer_passport_num')
        }

        if operation_type in ['102', '103']:  # Modify or Delete
            contact_data['id'] = request.POST.get('contact_id')

        # Remove empty values
        contact_data = {k: v for k, v in contact_data.items() if v}

        try:
            with EnhancedEFRISAPIClient(company) as client:
                result = client.t181_upload_frequent_contacts(operation_type, contact_data)

                if result.get('success'):
                    operation_names = {'101': 'added', '102': 'updated', '103': 'deleted'}
                    messages.success(request, f"Contact {operation_names[operation_type]} successfully")
                    return redirect('efris:frequent_contacts_management')
                else:
                    messages.error(request, f"Operation failed: {result.get('error')}")
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")

    return render(request, 'efris/advanced/frequent_contacts.html', {
        'page_title': 'Frequent Contacts Management',
        'contacts': contacts
    })

from company.models import EFRISHsCode

@login_required
def hs_code_list(request):
    """HS Code List (from database only)"""

    hs_codes = EFRISHsCode.objects.all().order_by("hs_code")

    return render(
        request,
        "efris/advanced/hs_code_list.html",
        {
            "page_title": "HS Code List",
            "hs_codes": hs_codes,
        },
    )

from efris.tasks import sync_hs_codes_task

@login_required
def sync_hs_codes(request):
    company = request.tenant
    # Pass company_id and current schema to Celery
    sync_hs_codes_task.delay(company_id=company.company_id,
                             schema_name=company.schema_name)
    messages.success(request, "HS code sync started in the background.")
    return redirect("efris:hs_code_list")

@login_required
def invoice_remain_details(request, invoice_no=None):
    """T186 - Query Invoice Remain Details"""
    company = request.tenant
    invoice_details = None

    if request.method == 'POST' or invoice_no:
        invoice_no = invoice_no or request.POST.get('invoice_no')

        try:
            with EnhancedEFRISAPIClient(company) as client:
                result = client.t186_query_invoice_remain_details(invoice_no)

                if result.get('success'):
                    invoice_details = result
                    messages.success(request, f"Invoice details retrieved for {invoice_no}")
                else:
                    messages.error(request, f"Query failed: {result.get('error')}")
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")

    return render(request, 'efris/advanced/invoice_remain_details.html', {
        'page_title': 'Invoice Remain Details',
        'invoice_details': invoice_details
    })

@login_required
def fdn_status_query(request):
    """T187 - Query Export FDN Status"""
    company = request.tenant
    fdn_status = None

    if request.method == 'POST':
        invoice_no = request.POST.get('invoice_no')

        try:
            with EnhancedEFRISAPIClient(company) as client:
                result = client.t187_query_fdn_status(invoice_no)

                if result.get('success'):
                    fdn_status = result
                    messages.success(request, f"FDN status retrieved for {invoice_no}")
                else:
                    messages.error(request, f"Query failed: {result.get('error')}")
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")

    return render(request, 'efris/advanced/fdn_status_query.html', {
        'page_title': 'FDN Status Query',
        'fdn_status': fdn_status
    })

@login_required
def agent_relations(request):
    """T179 - Query Agent Relations"""
    company = request.tenant
    agent_taxpayers = []

    if request.method == 'POST':
        tin = request.POST.get('tin')

        try:
            with EnhancedEFRISAPIClient(company) as client:
                result = client.t179_query_agent_relation_information(tin)

                if result.get('success'):
                    agent_taxpayers = result.get('agent_taxpayers', [])
                    messages.success(request, f"Retrieved {len(agent_taxpayers)} agent relations")
                else:
                    messages.error(request, f"Query failed: {result.get('error')}")
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")

    return render(request, 'efris/advanced/agent_relations.html', {
        'page_title': 'Agent Relations',
        'agent_taxpayers': agent_taxpayers
    })

@login_required
def principal_agent_info(request):
    """T180 - Query Principal Agent TIN Information"""
    company = request.tenant
    agent_info = None

    if request.method == 'POST':
        tin = request.POST.get('tin')
        branch_id = request.POST.get('branch_id')

        try:
            with EnhancedEFRISAPIClient(company) as client:
                result = client.t180_query_principal_agent_tin_information(tin, branch_id)

                if result.get('success'):
                    agent_info = result
                    messages.success(request, f"Principal agent info retrieved")
                else:
                    messages.error(request, f"Query failed: {result.get('error')}")
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")

    return render(request, 'efris/advanced/principal_agent_info.html', {
        'page_title': 'Principal Agent Information',
        'agent_info': agent_info
    })

@login_required
def ussd_account_creation(request):
    """T175 - Create USSD Account"""
    company = request.tenant

    if request.method == 'POST':
        tin = request.POST.get('tin')
        mobile_number = request.POST.get('mobile_number')

        try:
            with EnhancedEFRISAPIClient(company) as client:
                result = client.t175_create_ussd_taxpayer_account(tin, mobile_number)

                if result.get('success'):
                    messages.success(request, f"USSD account created for TIN: {tin}")
                    return redirect('efris:ussd_account_creation')
                else:
                    messages.error(request, f"Account creation failed: {result.get('error')}")
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")

    return render(request, 'efris/advanced/ussd_account_creation.html', {
        'page_title': 'USSD Account Creation'
    })

@login_required
def efd_transfer(request):
    """T178 - EFD Transfer"""
    company = request.tenant

    if request.method == 'POST':
        destination_branch_id = request.POST.get('destination_branch_id')
        remarks = request.POST.get('remarks')

        try:
            with EnhancedEFRISAPIClient(company) as client:
                result = client.t178_efd_transfer(destination_branch_id, remarks)

                if result.get('success'):
                    messages.success(request, "EFD transferred successfully")
                    return redirect('efris:efd_transfer')
                else:
                    messages.error(request, f"Transfer failed: {result.get('error')}")
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")

    return render(request, 'efris/advanced/efd_transfer.html', {
        'page_title': 'EFD Transfer'
    })

@login_required
def negative_stock_configuration(request):
    """T177 - Query Negative Stock Configuration"""
    company = request.tenant
    config_data = None

    try:
        with EnhancedEFRISAPIClient(company) as client:
            result = client.t177_query_negative_stock_configuration()

            if result.get('success'):
                config_data = result
            else:
                messages.error(request, f"Query failed: {result.get('error')}")
    except Exception as e:
        messages.error(request, f"Error: {str(e)}")

    return render(request, 'efris/advanced/negative_stock_config.html', {
        'page_title': 'Negative Stock Configuration',
        'config_data': config_data
    })

# API Endpoints for AJAX requests
@login_required
@require_http_methods(["POST"])
def api_upload_nozzle_status(request):
    """T172 - Upload Fuel Nozzle Status (AJAX)"""
    company = request.tenant

    try:
        data = json.loads(request.body)
        nozzle_id = data.get('nozzle_id')
        nozzle_no = data.get('nozzle_no')
        status = data.get('status')

        with EnhancedEFRISAPIClient(company) as client:
            result = client.t172_upload_fuel_nozzle_status(nozzle_id, nozzle_no, status)

            return JsonResponse(result)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
@require_http_methods(["POST"])
def api_upload_device_issuing_status(request):
    """T176 - Upload Device Issuing Status (AJAX)"""
    company = request.tenant

    try:
        data = json.loads(request.body)
        device_no = data.get('device_no')
        status = data.get('status')

        with EnhancedEFRISAPIClient(company) as client:
            result = client.t176_upload_device_issuing_status(device_no, status)

            return JsonResponse(result)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
@require_http_methods(["GET"])
def api_query_fuel_pump_version(request):
    """T168 - Query Fuel Pump Version (AJAX)"""
    company = request.tenant

    try:
        with EnhancedEFRISAPIClient(company) as client:
            result = client.t168_query_fuel_pump_version()

            return JsonResponse(result)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
@require_http_methods(["GET"])
def api_query_edc_uom_rates(request):
    """T171 - Query EDC UoM Exchange Rates (AJAX)"""
    company = request.tenant

    try:
        with EnhancedEFRISAPIClient(company) as client:
            result = client.t171_query_edc_uom_exchange_rate()

            return JsonResponse(result)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
@require_http_methods(["GET"])
def api_query_edc_device_version(request):
    """T173 - Query EDC Device Version (AJAX)"""
    company = request.tenant

    try:
        with EnhancedEFRISAPIClient(company) as client:
            result = client.t173_query_edc_device_version()

            return JsonResponse(result)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)