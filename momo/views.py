"""
MTN MoMo API - Django Views
Each view wraps a service call and returns JSON.
"""

import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from . import services


def _body(request):
    try:
        return json.loads(request.body)
    except Exception:
        return {}


def _get_fresh_token():
    return services.create_access_token()


# ── PROVISIONING ─────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["POST"])
def provision_create_user(request):
    return JsonResponse(services.provision_create_api_user())

@require_http_methods(["GET"])
def provision_get_user(request, ref_id):
    return JsonResponse(services.provision_get_api_user(ref_id))

@csrf_exempt
@require_http_methods(["POST"])
def provision_create_key(request, ref_id):
    return JsonResponse(services.provision_create_api_key(ref_id))

# ── TOKEN ─────────────────────────────────────────────────────────

@require_http_methods(["GET"])
def get_token(request):
    try:
        token = services.create_access_token()
        return JsonResponse({"access_token": token})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

# ── ACCOUNT ───────────────────────────────────────────────────────

@require_http_methods(["GET"])
def account_balance(request):
    token = request.GET.get("token") or _get_fresh_token()
    return JsonResponse(services.get_account_balance(token))

@require_http_methods(["GET"])
def account_balance_currency(request, currency):
    token = request.GET.get("token") or _get_fresh_token()
    return JsonResponse(services.get_account_balance_in_currency(token, currency))

@require_http_methods(["GET"])
def validate_holder(request, id_type, account_id):
    token = request.GET.get("token") or _get_fresh_token()
    return JsonResponse(services.validate_account_holder(token, id_type, account_id))

@require_http_methods(["GET"])
def basic_user_info(request, id_type, account_id):
    token = request.GET.get("token") or _get_fresh_token()
    return JsonResponse(services.get_basic_user_info(token, id_type, account_id))

# ── REQUEST TO PAY ────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["POST"])
def request_to_pay(request):
    data = _body(request)
    token = data.get("token") or _get_fresh_token()
    result = services.request_to_pay(
        token=token,
        amount=data["amount"],
        currency=data["currency"],
        payer_msisdn=data["payer_msisdn"],
        payer_message=data.get("payer_message", ""),
        payee_note=data.get("payee_note", ""),
        external_id=data.get("external_id"),
        callback_url=data.get("callback_url"),
    )
    return JsonResponse(result)

@require_http_methods(["GET"])
def request_to_pay_status(request, reference_id):
    token = request.GET.get("token") or _get_fresh_token()
    return JsonResponse(services.get_request_to_pay_status(token, reference_id))

@csrf_exempt
@require_http_methods(["POST"])
def delivery_notification(request, reference_id):
    data = _body(request)
    token = data.get("token") or _get_fresh_token()
    return JsonResponse(services.send_delivery_notification(token, reference_id, data["message"], data.get("language")))

# ── REQUEST TO WITHDRAW ───────────────────────────────────────────

@csrf_exempt
@require_http_methods(["POST"])
def request_to_withdraw(request):
    data = _body(request)
    token = data.get("token") or _get_fresh_token()
    result = services.request_to_withdraw(
        token=token,
        amount=data["amount"],
        currency=data["currency"],
        payer_msisdn=data["payer_msisdn"],
        payer_message=data.get("payer_message", ""),
        payee_note=data.get("payee_note", ""),
        version=data.get("version", "v2_0"),
        callback_url=data.get("callback_url"),
    )
    return JsonResponse(result)

@require_http_methods(["GET"])
def withdraw_status(request, reference_id):
    token = request.GET.get("token") or _get_fresh_token()
    return JsonResponse(services.get_withdraw_status(token, reference_id))

# ── INVOICES ──────────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["POST"])
def create_invoice(request):
    data = _body(request)
    token = data.get("token") or _get_fresh_token()
    result = services.create_invoice(
        token=token,
        amount=data["amount"],
        currency=data["currency"],
        validity_seconds=data.get("validity_seconds", 3600),
        payee_msisdn=data["payee_msisdn"],
        payer_msisdn=data.get("payer_msisdn"),
        description=data.get("description", ""),
        external_id=data.get("external_id"),
        callback_url=data.get("callback_url"),
    )
    return JsonResponse(result)

@require_http_methods(["GET"])
def invoice_status(request, reference_id):
    token = request.GET.get("token") or _get_fresh_token()
    return JsonResponse(services.get_invoice_status(token, reference_id))

@csrf_exempt
@require_http_methods(["DELETE"])
def cancel_invoice_view(request, reference_id):
    token = request.GET.get("token") or _get_fresh_token()
    return JsonResponse(services.cancel_invoice(token, reference_id))

# ── PAYMENTS ──────────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["POST"])
def create_payment(request):
    data = _body(request)
    token = data.get("token") or _get_fresh_token()
    result = services.create_payment(
        token=token,
        amount=data["amount"],
        currency=data["currency"],
        customer_reference=data["customer_reference"],
        service_provider=data["service_provider"],
        external_id=data.get("external_id"),
        callback_url=data.get("callback_url"),
    )
    return JsonResponse(result)

@require_http_methods(["GET"])
def payment_status(request, reference_id):
    token = request.GET.get("token") or _get_fresh_token()
    return JsonResponse(services.get_payment_status(token, reference_id))

# ── PRE-APPROVALS ─────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["POST"])
def create_pre_approval(request):
    data = _body(request)
    token = data.get("token") or _get_fresh_token()
    result = services.create_pre_approval(
        token=token,
        payer_msisdn=data["payer_msisdn"],
        currency=data["currency"],
        message=data.get("message", ""),
        validity_seconds=data.get("validity_seconds", 3600),
        callback_url=data.get("callback_url"),
    )
    return JsonResponse(result)

@require_http_methods(["GET"])
def pre_approval_status(request, reference_id):
    token = request.GET.get("token") or _get_fresh_token()
    return JsonResponse(services.get_pre_approval_status(token, reference_id))

@require_http_methods(["GET"])
def approved_pre_approvals(request, id_type, account_id):
    token = request.GET.get("token") or _get_fresh_token()
    return JsonResponse(services.get_approved_pre_approvals(token, id_type, account_id), safe=False)

@csrf_exempt
@require_http_methods(["DELETE"])
def cancel_pre_approval(request, preapproval_id):
    token = request.GET.get("token") or _get_fresh_token()
    return JsonResponse(services.cancel_pre_approval(token, preapproval_id))
