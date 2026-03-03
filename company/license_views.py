"""
companies/license_views.py
======================================
Desktop license endpoints.

Endpoints
---------
POST /api/desktop/license/generate/
    Authenticated. Desktop calls this after payment with machine_id.
    Generates an HMAC-signed license key, stores it on the Company,
    and returns it. The customer then pastes it into the desktop app.

POST /api/desktop/license/activate/
    Authenticated. Desktop calls this to validate a license key that
    the customer has already entered. Returns ok/error.

License key format
------------------
Base64-encoded JSON payload + HMAC-SHA256 signature:
    <base64(json_payload)>.<base64(hmac_signature)>

Payload fields:
    company_id   str   "PF-N798701"
    email        str   "admin@company.com"
    machine_id   str   SHA-256 of hardware fingerprint
    schema_name  str   "aba"
    plan         str   "PRO"
    issued_at    str   ISO date "2026-03-02"
    expires_at   str   ISO date "2027-03-02"
    version      int   1  (bump if format changes)

Setup
-----
Add to Django settings (or .env):
    LICENSE_HMAC_SECRET = "your-secret-key-here"

Use the SAME value in the desktop DATA_DIR/.config.ini:
    [security]
    hmac_secret = your-secret-key-here

This shared secret is the only thing linking server-issued licenses
to desktop validation — keep it out of version control.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from datetime import date, timedelta

from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_secret() -> bytes:
    secret = getattr(settings, "LICENSE_HMAC_SECRET", "")
    if not secret:
        raise ValueError(
            "LICENSE_HMAC_SECRET is not set in Django settings. "
            "Add it to your settings.py or .env file."
        )
    return secret.encode() if isinstance(secret, str) else secret


def _sign_payload(payload: dict) -> str:
    """
    Produce a license key string:
        <base64url(json_payload)>.<base64url(hmac_sha256)>
    """
    payload_bytes  = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    payload_b64    = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode()
    sig            = hmac.new(_get_secret(), payload_b64.encode(), hashlib.sha256).digest()
    sig_b64        = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
    return f"{payload_b64}.{sig_b64}"


def _verify_key(license_key: str) -> tuple[bool, dict]:
    """
    Verify signature and return (valid, payload_dict).
    Returns (False, {}) on any error.
    """
    try:
        parts = license_key.strip().split(".")
        if len(parts) != 2:
            return False, {}

        payload_b64, sig_b64 = parts

        # Verify HMAC
        expected_sig = hmac.new(
            _get_secret(),
            payload_b64.encode(),
            hashlib.sha256,
        ).digest()
        given_sig = base64.urlsafe_b64decode(sig_b64 + "==")
        if not hmac.compare_digest(expected_sig, given_sig):
            return False, {}

        # Decode payload
        payload_bytes = base64.urlsafe_b64decode(payload_b64 + "==")
        payload       = json.loads(payload_bytes)
        return True, payload

    except Exception as e:
        logger.warning(f"License key verification error: {e}")
        return False, {}


def _expiry_for_plan(plan_name: str, subscription_ends_at) -> str:
    """
    Determine license expiry date.
    Priority:
      1. Company.subscription_ends_at  (paid plan, exact billing date)
      2. 1 year from today             (fallback for trial → paid transition)
    """
    if subscription_ends_at:
        return subscription_ends_at.isoformat()
    # Fallback: 1 year
    return (date.today() + timedelta(days=365)).isoformat()


# ---------------------------------------------------------------------------
# Endpoint: Generate license
# ---------------------------------------------------------------------------

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def generate_license(request):
    """
    POST /api/desktop/license/generate/

    Body:
        {
            "machine_id": "<sha256 fingerprint from desktop>",
            "company_id": "PF-N798701"     // optional if inferable from request user
        }

    Returns:
        {
            "license_key": "<key>",
            "expires_at":  "2027-03-02",
            "plan":        "PRO",
            "company_id":  "PF-N798701"
        }
    """
    machine_id = request.data.get("machine_id", "").strip()
    if not machine_id:
        return Response({"error": "machine_id is required"}, status=400)

    # Resolve company — use company_id from request body if provided,
    # otherwise fall back to the authenticated user's company.
    from apps.companies.models import Company  # adjust import path to your project

    company_id = request.data.get("company_id", "").strip()
    try:
        if company_id:
            company = Company.objects.get(company_id=company_id)
        else:
            # Try to get company from user's schema
            company = Company.objects.get(schema_name=request.user.schema_name)
    except Company.DoesNotExist:
        return Response({"error": "Company not found"}, status=404)
    except AttributeError:
        return Response({"error": "company_id is required"}, status=400)

    # Only generate for active or trial companies
    if company.status in ("ARCHIVED", "SUSPENDED"):
        return Response(
            {"error": f"Cannot generate license — company status is {company.status}"},
            status=403,
        )

    plan_name  = company.plan.name if company.plan else "FREE"
    expires_at = _expiry_for_plan(plan_name, company.subscription_ends_at)

    payload = {
        "version":     1,
        "company_id":  company.company_id,
        "email":       company.email or request.user.email,
        "machine_id":  machine_id,
        "schema_name": company.schema_name,
        "plan":        plan_name,
        "issued_at":   date.today().isoformat(),
        "expires_at":  expires_at,
    }

    try:
        license_key = _sign_payload(payload)
    except ValueError as e:
        logger.error(f"License generation failed: {e}")
        return Response({"error": str(e)}, status=500)

    # Store the latest license key on the company for reference
    # (add a license_key field to Company if you want to store it,
    #  or use a separate DesktopLicense model — optional)
    logger.info(
        f"License generated for {company.company_id} "
        f"(plan={plan_name}, expires={expires_at}, machine={machine_id[:8]}...)"
    )

    return Response({
        "license_key": license_key,
        "company_id":  company.company_id,
        "plan":        plan_name,
        "issued_at":   date.today().isoformat(),
        "expires_at":  expires_at,
        "email":       payload["email"],
    })


# ---------------------------------------------------------------------------
# Endpoint: Activate / validate license
# ---------------------------------------------------------------------------

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def activate_license(request):
    """
    POST /api/desktop/license/activate/

    Body:
        {
            "license_key": "<key>",
            "machine_id":  "<sha256 fingerprint>"
        }

    Returns 200 on success:
        {
            "valid":       true,
            "company_id":  "PF-N798701",
            "plan":        "PRO",
            "expires_at":  "2027-03-02",
            "days_remaining": 365
        }

    Returns 400 on failure:
        {
            "valid":   false,
            "error":   "License has expired"
        }
    """
    license_key = request.data.get("license_key", "").strip()
    machine_id  = request.data.get("machine_id",  "").strip()

    if not license_key:
        return Response({"valid": False, "error": "license_key is required"}, status=400)
    if not machine_id:
        return Response({"valid": False, "error": "machine_id is required"}, status=400)

    valid, payload = _verify_key(license_key)
    if not valid:
        return Response({"valid": False, "error": "Invalid license key"}, status=400)

    # Check machine binding
    if payload.get("machine_id") != machine_id:
        logger.warning(
            f"License machine_id mismatch for {payload.get('company_id')} — "
            f"expected {payload.get('machine_id', '')[:8]}... got {machine_id[:8]}..."
        )
        return Response(
            {"valid": False, "error": "License is bound to a different machine"},
            status=400,
        )

    # Check expiry
    try:
        expires = date.fromisoformat(payload["expires_at"])
        today   = date.today()
        if expires < today:
            return Response(
                {"valid": False, "error": "License has expired"},
                status=400,
            )
        days_remaining = (expires - today).days
    except (KeyError, ValueError):
        return Response(
            {"valid": False, "error": "License payload is malformed"},
            status=400,
        )

    logger.info(
        f"License activated for {payload.get('company_id')} "
        f"(plan={payload.get('plan')}, days_remaining={days_remaining})"
    )

    return Response({
        "valid":          True,
        "company_id":     payload.get("company_id"),
        "email":          payload.get("email"),
        "plan":           payload.get("plan"),
        "schema_name":    payload.get("schema_name"),
        "issued_at":      payload.get("issued_at"),
        "expires_at":     payload.get("expires_at"),
        "days_remaining": days_remaining,
    })