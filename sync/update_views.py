"""
sync/update_views.py
====================
Two endpoints wired into your existing sync app.

  GET  /api/v1/updates/check/        (tenant urlconf — urls.py)
       Checks for a newer AppVersion in the PUBLIC schema.
       Called by the desktop on startup + every 4 hours.

  POST /api/v1/crash-reports/        (tenant urlconf — urls.py)
       Accepts a crash report from the desktop and writes it to
       the PUBLIC schema CrashReport table.

Both live behind IsAuthenticated — the desktop's existing JWT handles
auth automatically, no changes needed on the client side.

django-tenants schema switching
---------------------------------
These views are served from a TENANT subdomain (ug.primebooks.sale) so
django-tenants has already set connection.schema_name = 'ug' by the time
the view runs. To read/write the PUBLIC schema models (AppVersion,
CrashReport) we use:

    with schema_context('public'):
        AppVersion.objects.filter(...)

This is the correct, documented django-tenants pattern. It temporarily
switches the connection to 'public', runs the block, then restores the
tenant schema. It is safe inside a DRF view.
"""

import hashlib
import logging

from django.utils import timezone
from django_tenants.utils import schema_context
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .utils import get_client_ip

logger = logging.getLogger(__name__)


def _parse_version(v: str) -> tuple:
    """'1.2.3' → (1, 2, 3). Never raises."""
    try:
        return tuple(int(x) for x in str(v).strip().split("."))
    except Exception:
        return (0,)


def _get_schema_name(request) -> str:
    if hasattr(request, "tenant"):
        return request.tenant.schema_name
    return getattr(request, "schema_name", "")


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/v1/updates/check/
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def update_check(request):
    """
    Check whether a newer desktop version is available.

    Query params:
        version   client's current version string e.g. "1.0.0"
                  Defaults to "0.0.0" (always show update) if omitted.

    Response — update available:
        {
            "update_available": true,
            "version":          "1.2.0",
            "is_critical":      false,
            "changelog":        "• Bug fixes\n• Performance",
            "download_url":     "https://primebooks.sale/releases/PrimeBooks-1.2.0-setup.exe",
            "min_version":      "1.0.0",      // only if set
            "file_size_bytes":  8847360        // only if set
        }

    Response — no update:
        { "update_available": false }
    """
    from saad.models import PrimeBooksVersion

    client_version = request.GET.get("version", "0.0.0").strip()
    client_tuple   = _parse_version(client_version)
    schema_name    = _get_schema_name(request)

    logger.debug(
        f"update_check: user={request.user.email}, "
        f"schema={schema_name}, client_version={client_version}"
    )

    try:
        # AppVersion lives in the PUBLIC schema — switch context to read it
        with schema_context("public"):
            latest = (
                PrimeBooksVersion.objects
                .filter(is_active=True)
                .order_by("-created_at")
                .first()
            )
    except Exception as e:
        logger.error(f"update_check: DB error — {e}", exc_info=True)
        return Response({"update_available": False})

    if not latest:
        logger.debug("update_check: no active AppVersion found")
        return Response({"update_available": False})

    latest_tuple = _parse_version(latest.version)

    # Force critical if client is below min_version
    is_critical = latest.is_critical
    if latest.min_version:
        min_tuple = _parse_version(latest.min_version)
        if client_tuple < min_tuple:
            is_critical = True
            logger.info(
                f"update_check: {client_version} < min_version "
                f"{latest.min_version} — forcing critical (schema={schema_name})"
            )

    if latest_tuple <= client_tuple:
        logger.debug(
            f"update_check: up to date "
            f"(client={client_version}, latest={latest.version})"
        )
        return Response({"update_available": False})

    logger.info(
        f"update_check: update available {client_version} → {latest.version} "
        f"critical={is_critical} schema={schema_name}"
    )

    payload = {
        "update_available": True,
        "version":          latest.version,
        "is_critical":      is_critical,
        "changelog":        latest.changelog or "",
        "download_url":     latest.download_url,
    }
    if latest.min_version:
        payload["min_version"] = latest.min_version
    if latest.file_size_bytes:
        payload["file_size_bytes"] = latest.file_size_bytes

    return Response(payload)


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/v1/crash-reports/
# ─────────────────────────────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def crash_report_submit(request):
    """
    Accept and persist a crash report from the desktop.

    Body (JSON):
        {
            "app_version": "1.0.0",
            "platform":    "Windows-10-10.0.19041-SP0",
            "schema_name": "ug",            // optional — we read from request.tenant
            "traceback":   "Traceback ...",
            "context":     {}               // optional extra dict
        }

    Deduplication:
        SHA-256(schema_name | app_version | traceback) is the fingerprint.
        If a report with the same fingerprint already exists we just
        increment occurrence_count and update last_seen_at rather than
        creating a new row.

    Response:
        201  { "status": "received",      "deduplicated": false }
        201  { "status": "deduplicated",  "occurrence_count": 5 }
        400  { "detail": "traceback is required." }
    """
    from saad.models import CrashReport

    data        = request.data
    traceback   = (data.get("traceback") or "").strip()
    app_version = (data.get("app_version") or "").strip()
    # Prefer the real tenant schema over whatever the client sent
    schema_name = _get_schema_name(request) or (data.get("schema_name") or "").strip()
    plat        = (data.get("platform") or "").strip()
    context     = data.get("context") or {}
    client_ip   = get_client_ip(request)

    if not traceback:
        return Response({"detail": "traceback is required."}, status=400)

    # Fingerprint for deduplication
    raw         = f"{schema_name}|{app_version}|{traceback}"
    fingerprint = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:64]

    logger.info(
        f"crash_report: schema={schema_name} version={app_version} "
        f"fingerprint={fingerprint[:12]}…"
    )

    try:
        # CrashReport lives in PUBLIC schema — switch context to write it
        with schema_context("public"):
            existing = CrashReport.objects.filter(fingerprint=fingerprint).first()

            if existing:
                existing.occurrence_count += 1
                existing.last_seen_at      = timezone.now()
                if context and context != existing.context:
                    existing.context = context
                existing.save(update_fields=["occurrence_count", "last_seen_at", "context"])
                logger.debug(
                    f"crash_report: deduplicated — count={existing.occurrence_count}"
                )
                return Response({
                    "status":           "deduplicated",
                    "occurrence_count": existing.occurrence_count,
                }, status=201)

            CrashReport.objects.create(
                schema_name      = schema_name,
                app_version      = app_version,
                platform         = plat,
                traceback        = traceback,
                context          = context if isinstance(context, dict) else {},
                client_ip        = client_ip,
                fingerprint      = fingerprint,
                occurrence_count = 1,
                last_seen_at     = timezone.now(),
            )

        logger.info(
            f"crash_report: saved — schema={schema_name} version={app_version}"
        )
        return Response({"status": "received", "deduplicated": False}, status=201)

    except Exception as e:
        # Never let crash reporting cause a 500 — just log and ack
        logger.error(f"crash_report: save failed — {e}", exc_info=True)
        return Response({"status": "received", "deduplicated": False}, status=201)