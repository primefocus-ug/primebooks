"""
MTN Mobile Money API - Service Layer
All API calls are centralised here.
"""

import uuid
import base64
import requests
from momo_project import momo_config as cfg


def _headers_basic():
    """Basic auth header for token endpoint."""
    credentials = f"{cfg.API_USER}:{cfg.API_KEY}"
    encoded = base64.b64encode(credentials.encode()).decode()
    return {
        "Authorization": f"Basic {encoded}",
        "Ocp-Apim-Subscription-Key": cfg.SUBSCRIPTION_KEY,
        "Content-Type": "application/json",
    }


def _headers_bearer(token, reference_id=None, callback_url=None):
    """Bearer auth header for all other endpoints."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Ocp-Apim-Subscription-Key": cfg.SUBSCRIPTION_KEY,
        "X-Target-Environment": cfg.TARGET_ENVIRONMENT,
        "Content-Type": "application/json",
    }
    if reference_id:
        headers["X-Reference-Id"] = reference_id
    if callback_url:
        headers["X-Callback-Url"] = callback_url
    return headers


# ------------------------------------------------------------------
# PROVISIONING (Sandbox only)
# ------------------------------------------------------------------

def provision_create_api_user():
    """Create an API user (sandbox only). Returns (ref_id, status_code)."""
    ref_id = str(uuid.uuid4())
    url = f"{cfg.BASE_URL}/v1_0/apiuser"
    headers = {
        "X-Reference-Id": ref_id,
        "Ocp-Apim-Subscription-Key": cfg.SUBSCRIPTION_KEY,
        "Content-Type": "application/json",
    }
    body = {"providerCallbackHost": cfg.PROVIDER_CALLBACK_HOST}
    resp = requests.post(url, json=body, headers=headers)
    return {"reference_id": ref_id, "status_code": resp.status_code, "body": resp.text}


def provision_get_api_user(ref_id):
    """Get API user details."""
    url = f"{cfg.BASE_URL}/v1_0/apiuser/{ref_id}"
    headers = {"Ocp-Apim-Subscription-Key": cfg.SUBSCRIPTION_KEY}
    resp = requests.get(url, headers=headers)
    return {"status_code": resp.status_code, "body": resp.json() if resp.content else {}}


def provision_create_api_key(ref_id):
    """Create API key for a user (sandbox only)."""
    url = f"{cfg.BASE_URL}/v1_0/apiuser/{ref_id}/apikey"
    headers = {"Ocp-Apim-Subscription-Key": cfg.SUBSCRIPTION_KEY}
    resp = requests.post(url, headers=headers)
    return {"status_code": resp.status_code, "body": resp.json() if resp.content else {}}


# ------------------------------------------------------------------
# AUTHENTICATION
# ------------------------------------------------------------------

def create_access_token():
    """Get a Bearer token. Returns the token string or raises."""
    url = f"{cfg.BASE_URL}/collection/token/"
    resp = requests.post(url, headers=_headers_basic())
    resp.raise_for_status()
    return resp.json()["access_token"]


# ------------------------------------------------------------------
# ACCOUNT
# ------------------------------------------------------------------

def get_account_balance(token):
    url = f"{cfg.BASE_URL}/collection/v1_0/account/balance"
    resp = requests.get(url, headers=_headers_bearer(token))
    return {"status_code": resp.status_code, "body": resp.json() if resp.content else {}}


def get_account_balance_in_currency(token, currency):
    url = f"{cfg.BASE_URL}/collection/v1_0/account/balance/{currency}"
    resp = requests.get(url, headers=_headers_bearer(token))
    return {"status_code": resp.status_code, "body": resp.json() if resp.content else {}}


def validate_account_holder(token, id_type, account_id):
    """Check if an account holder is active. id_type: msisdn or email."""
    url = f"{cfg.BASE_URL}/collection/v1_0/accountholder/{id_type}/{account_id}/active"
    resp = requests.get(url, headers=_headers_bearer(token))
    return {"status_code": resp.status_code, "active": resp.text.strip() == "true"}


def get_basic_user_info(token, id_type, account_id):
    url = f"{cfg.BASE_URL}/collection/v1_0/accountholder/{id_type}/{account_id}/basicuserinfo"
    resp = requests.get(url, headers=_headers_bearer(token))
    return {"status_code": resp.status_code, "body": resp.json() if resp.content else {}}


# ------------------------------------------------------------------
# REQUEST TO PAY
# ------------------------------------------------------------------

def request_to_pay(token, amount, currency, payer_msisdn, payer_message="", payee_note="", external_id=None, callback_url=None):
    """Initiate a Request to Pay. Returns reference_id for status polling."""
    ref_id = str(uuid.uuid4())
    url = f"{cfg.BASE_URL}/collection/v1_0/requesttopay"
    body = {
        "amount": str(amount),
        "currency": currency,
        "externalId": external_id or str(uuid.uuid4()),
        "payer": {"partyIdType": "MSISDN", "partyId": payer_msisdn},
        "payerMessage": payer_message,
        "payeeNote": payee_note,
    }
    resp = requests.post(url, json=body, headers=_headers_bearer(token, ref_id, callback_url))
    return {"reference_id": ref_id, "status_code": resp.status_code, "body": resp.text}


def get_request_to_pay_status(token, reference_id):
    url = f"{cfg.BASE_URL}/collection/v1_0/requesttopay/{reference_id}"
    resp = requests.get(url, headers=_headers_bearer(token))
    return {"status_code": resp.status_code, "body": resp.json() if resp.content else {}}


def send_delivery_notification(token, reference_id, message, language=None):
    url = f"{cfg.BASE_URL}/collection/v1_0/requesttopay/{reference_id}/deliverynotification"
    headers = _headers_bearer(token)
    headers["notificationMessage"] = message[:160]
    if language:
        headers["Language"] = language
    body = {"notificationMessage": message[:160]}
    resp = requests.post(url, json=body, headers=headers)
    return {"status_code": resp.status_code, "body": resp.text}


# ------------------------------------------------------------------
# REQUEST TO WITHDRAW
# ------------------------------------------------------------------

def request_to_withdraw(token, amount, currency, payer_msisdn, payer_message="", payee_note="", version="v2_0", callback_url=None):
    ref_id = str(uuid.uuid4())
    url = f"{cfg.BASE_URL}/collection/{version}/requesttowithdraw"
    body = {
        "amount": str(amount),
        "currency": currency,
        "externalId": str(uuid.uuid4()),
        "payer": {"partyIdType": "MSISDN", "partyId": payer_msisdn},
        "payerMessage": payer_message,
        "payeeNote": payee_note,
    }
    resp = requests.post(url, json=body, headers=_headers_bearer(token, ref_id, callback_url))
    return {"reference_id": ref_id, "status_code": resp.status_code, "body": resp.text}


def get_withdraw_status(token, reference_id):
    url = f"{cfg.BASE_URL}/collection/v1_0/requesttowithdraw/{reference_id}"
    resp = requests.get(url, headers=_headers_bearer(token))
    return {"status_code": resp.status_code, "body": resp.json() if resp.content else {}}


# ------------------------------------------------------------------
# INVOICES
# ------------------------------------------------------------------

def create_invoice(token, amount, currency, validity_seconds, payee_msisdn, payer_msisdn=None, description="", external_id=None, callback_url=None):
    ref_id = str(uuid.uuid4())
    url = f"{cfg.BASE_URL}/collection/v2_0/invoice"
    body = {
        "externalId": external_id or str(uuid.uuid4()),
        "amount": str(amount),
        "currency": currency,
        "validityDuration": str(validity_seconds),
        "payee": {"partyIdType": "MSISDN", "partyId": payee_msisdn},
        "description": description,
    }
    if payer_msisdn:
        body["intendedPayer"] = {"partyIdType": "MSISDN", "partyId": payer_msisdn}
    resp = requests.post(url, json=body, headers=_headers_bearer(token, ref_id, callback_url))
    return {"reference_id": ref_id, "status_code": resp.status_code, "body": resp.text}


def get_invoice_status(token, reference_id):
    url = f"{cfg.BASE_URL}/collection/v2_0/invoice/{reference_id}"
    resp = requests.get(url, headers=_headers_bearer(token))
    return {"status_code": resp.status_code, "body": resp.json() if resp.content else {}}


def cancel_invoice(token, reference_id, external_id=None):
    url = f"{cfg.BASE_URL}/collection/v2_0/invoice/{reference_id}"
    headers = _headers_bearer(token)
    headers["X-Reference-Id"] = str(uuid.uuid4())
    body = {"externalId": external_id or str(uuid.uuid4())}
    resp = requests.delete(url, json=body, headers=headers)
    return {"status_code": resp.status_code, "body": resp.text}


# ------------------------------------------------------------------
# PAYMENTS
# ------------------------------------------------------------------

def create_payment(token, amount, currency, customer_reference, service_provider, external_id=None, callback_url=None):
    ref_id = str(uuid.uuid4())
    url = f"{cfg.BASE_URL}/collection/v2_0/payment"
    body = {
        "externalTransactionId": external_id or str(uuid.uuid4()),
        "money": {"amount": str(amount), "currency": currency},
        "customerReference": customer_reference,
        "serviceProviderUserName": service_provider,
    }
    resp = requests.post(url, json=body, headers=_headers_bearer(token, ref_id, callback_url))
    return {"reference_id": ref_id, "status_code": resp.status_code, "body": resp.text}


def get_payment_status(token, reference_id):
    url = f"{cfg.BASE_URL}/collection/v2_0/payment/{reference_id}"
    resp = requests.get(url, headers=_headers_bearer(token))
    return {"status_code": resp.status_code, "body": resp.json() if resp.content else {}}


# ------------------------------------------------------------------
# PRE-APPROVALS
# ------------------------------------------------------------------

def create_pre_approval(token, payer_msisdn, currency, message, validity_seconds, callback_url=None):
    ref_id = str(uuid.uuid4())
    url = f"{cfg.BASE_URL}/collection/v2_0/preapproval"
    body = {
        "payer": {"partyIdType": "MSISDN", "partyId": payer_msisdn},
        "payerCurrency": currency,
        "payerMessage": message,
        "validityTime": validity_seconds,
    }
    resp = requests.post(url, json=body, headers=_headers_bearer(token, ref_id, callback_url))
    return {"reference_id": ref_id, "status_code": resp.status_code, "body": resp.text}


def get_pre_approval_status(token, reference_id):
    url = f"{cfg.BASE_URL}/collection/v2_0/preapproval/{reference_id}"
    resp = requests.get(url, headers=_headers_bearer(token))
    return {"status_code": resp.status_code, "body": resp.json() if resp.content else {}}


def get_approved_pre_approvals(token, id_type, account_id):
    url = f"{cfg.BASE_URL}/collection/v1_0/preapprovals/{id_type}/{account_id}"
    resp = requests.get(url, headers=_headers_bearer(token))
    return {"status_code": resp.status_code, "body": resp.json() if resp.content else []}


def cancel_pre_approval(token, preapproval_id):
    url = f"{cfg.BASE_URL}/collection/v1_0/preapproval/{preapproval_id}"
    resp = requests.delete(url, headers=_headers_bearer(token))
    return {"status_code": resp.status_code, "body": resp.text}
