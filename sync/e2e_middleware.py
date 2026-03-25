"""
sync/e2e_middleware.py  (Django server)
========================================
Decorator that transparently handles E2E encrypt/decrypt on sync views.

Apply @e2e_sync_view to sync_push and sync_pull.  The decorator:

  Push (POST with encrypted body):
    1. Detects "X-E2E: 1" header
    2. Decrypts request.data → replaces it with plaintext dict
    3. Calls the view normally
    4. Encrypts the Response data before returning

  Pull (GET with X-EPK header):
    1. Detects "X-EPK" header
    2. Derives session key from client's ephemeral public key
    3. Calls the view normally (no body to decrypt on GET)
    4. Encrypts the Response data before returning

  No E2E header:
    - If SYNC_E2E_REQUIRED=True in settings → HTTP 400
    - If SYNC_E2E_REQUIRED=False           → pass through unmodified (grace mode)

Error responses
---------------
  400 {"detail": "E2E_MISSING"}        — encrypted required but no header
  400 {"detail": "E2E_DECRYPT_FAILED"} — bad envelope, tampered payload, stale key
  400 {"detail": "E2E_NO_EPK"}         — pull request missing X-EPK header
  500 {"detail": "E2E_ENCRYPT_FAILED"} — response encryption failed (server bug)

Wiring
------
  In sync/push_view.py:

      from .e2e_middleware import e2e_sync_view

      @api_view(["POST"])
      @permission_classes([IsAuthenticated])
      @e2e_sync_view          ← add this
      def sync_push(request):
          # request.data is now the decrypted dict, same as before
          ...

  In sync/pull_view.py:

      @api_view(["GET"])
      @permission_classes([IsAuthenticated])
      @e2e_sync_view          ← add this
      def sync_pull(request):
          # Response is auto-encrypted before returning
          ...

Django settings
---------------
  SYNC_E2E_REQUIRED = True    # enforce E2E on all sync requests
  SYNC_E2E_PRIVATE_KEY = "..."  # base64 X25519 private key from keygen.py
"""

from __future__ import annotations

import logging
from functools import wraps
from typing import Callable

from rest_framework.request import Request
from rest_framework.response import Response

from .e2e_crypto import ServerSyncCrypto

logger = logging.getLogger(__name__)


def _e2e_required() -> bool:
    from django.conf import settings
    return getattr(settings, "SYNC_E2E_REQUIRED", True)


def e2e_sync_view(view_func: Callable) -> Callable:
    """
    Decorator for sync_push and sync_pull.
    Transparently decrypts the request and encrypts the response.
    """
    @wraps(view_func)
    def wrapper(request: Request, *args, **kwargs) -> Response:
        method = request.method.upper()

        # ── Determine whether this request is E2E-encrypted ───────────────
        has_e2e_header = request.headers.get("X-E2E") == "1"
        has_epk_header = bool(request.headers.get("X-EPK", "").strip())

        is_push = method == "POST"
        is_pull = method == "GET"

        # Grace mode check
        if not has_e2e_header and not has_epk_header:
            if _e2e_required():
                logger.warning(
                    f"[e2e] {method} {request.path} — "
                    f"E2E required but no X-E2E/X-EPK header from "
                    f"{request.user}"
                )
                return Response(
                    {"detail": "E2E_MISSING",
                     "message": "This endpoint requires end-to-end encryption. "
                                "Please update your PrimeBooks client."},
                    status=400,
                )
            # Grace mode — pass through unencrypted
            logger.debug(f"[e2e] grace mode — {method} {request.path} unencrypted")
            return view_func(request, *args, **kwargs)

        session_key: bytes | None = None

        # ── PUSH: decrypt request body ────────────────────────────────────
        if is_push and has_e2e_header:
            try:
                envelope = request.data
                plaintext_data, session_key = ServerSyncCrypto.decrypt_request(envelope)
            except ValueError as e:
                logger.warning(
                    f"[e2e] push decrypt failed — "
                    f"user={request.user} path={request.path} error={e}"
                )
                return Response(
                    {"detail": "E2E_DECRYPT_FAILED",
                     "message": "Could not decrypt request payload. "
                                "Your client key may be outdated — please update."},
                    status=400,
                )
            except Exception as e:
                logger.error(f"[e2e] push decrypt unexpected error: {e}", exc_info=True)
                return Response({"detail": "E2E_DECRYPT_FAILED"}, status=400)

            # Monkey-patch request.data with decrypted plaintext
            # DRF's Request stores data in _data — replacing it is safe here
            request._data = plaintext_data
            logger.debug(
                f"[e2e] push decrypted — user={request.user} "
                f"tables={list(plaintext_data.get('changes', {}).keys())}"
            )

        # ── PULL: derive session key from X-EPK header ────────────────────
        elif is_pull and has_epk_header:
            epk_b64 = request.headers.get("X-EPK", "").strip()
            if not epk_b64:
                return Response(
                    {"detail": "E2E_NO_EPK",
                     "message": "Pull request missing X-EPK header."},
                    status=400,
                )
            try:
                session_key, pull_nonce = ServerSyncCrypto.decrypt_pull_request_header(epk_b64)
                # Stash pull_nonce on request so we can use it in encrypt_response
                request._e2e_pull_nonce = pull_nonce
            except ValueError as e:
                logger.warning(f"[e2e] pull EPK derive failed: {e}")
                return Response(
                    {"detail": "E2E_DECRYPT_FAILED",
                     "message": "Invalid X-EPK header."},
                    status=400,
                )

        # ── Call the actual view ──────────────────────────────────────────
        response: Response = view_func(request, *args, **kwargs)

        # ── Encrypt the response if we have a session key ─────────────────
        if session_key is None:
            # Should not happen if headers were present — return as-is
            return response

        if not isinstance(response, Response):
            return response

        # For pull, use the pre-generated nonce stored on request
        # For push, encrypt_response generates a fresh nonce internally
        try:
            # Override session_key for pull to use the nonce-bound key
            if is_pull and hasattr(request, "_e2e_pull_nonce"):
                from .e2e_crypto import _derive_session_key, _load_server_private_key, _b64d, _b64e, _NONCE_BYTES
                import os
                from cryptography.hazmat.primitives.ciphers.aead import AESGCM
                import json as _json

                # Re-encrypt response data using the pull nonce
                nonce      = request._e2e_pull_nonce
                aesgcm     = AESGCM(session_key)
                plaintext  = _json.dumps(response.data, separators=(",", ":")).encode()
                ct_and_tag = aesgcm.encrypt(nonce, plaintext, None)
                envelope   = {
                    "v":     1,
                    "nonce": _b64e(nonce),
                    "ct":    _b64e(ct_and_tag[:-16]),
                    "tag":   _b64e(ct_and_tag[-16:]),
                }
            else:
                envelope = ServerSyncCrypto.encrypt_response(response.data, session_key)

        except Exception as e:
            logger.error(f"[e2e] response encryption failed: {e}", exc_info=True)
            return Response({"detail": "E2E_ENCRYPT_FAILED"}, status=500)

        response.data = envelope
        response["X-E2E"] = "1"
        return response

    return wrapper