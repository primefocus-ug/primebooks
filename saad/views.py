# saad/views.py
import hashlib
import logging

from django.utils import timezone
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
import json

from .models import PrimeBooksVersion, CrashReport

logger = logging.getLogger(__name__)


def _parse_version(v: str) -> tuple:
    try:
        return tuple(int(x) for x in str(v).strip().split("."))
    except Exception:
        return (0,)


def _get_token_payload(request):
    """Extract and validate Bearer token. Return payload dict or None."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:]
    # Plug in your JWT/token validation here.
    # e.g.:
    #   from rest_framework_simplejwt.tokens import AccessToken, TokenError
    #   try:
    #       payload = AccessToken(token)
    #       return {"user_id": payload["user_id"], "token": token}
    #   except TokenError:
    #       return None
    return {"token": token}


# ── 1. Desktop update check (authenticated) ───────────────────────────────────
#
# Called by updater.py on startup and every CHECK_INTERVAL (4 h).
# Returns a flat JSON object — shape must NOT change (desktop relies on it).
#
# GET /api/v1/updates/check/?version=1.0.0
# Headers: Authorization: Bearer <token>

@require_http_methods(["GET"])
def update_check(request):
    payload = _get_token_payload(request)
    if payload is None:
        return JsonResponse({"detail": "Unauthorized"}, status=401)

    active = PrimeBooksVersion.objects.filter(is_active=True).first()
    if not active:
        return JsonResponse({"update_available": False})

    client_version = request.GET.get("version", "0.0.0")

    if _parse_version(active.version) <= _parse_version(client_version):
        return JsonResponse({"update_available": False})

    # effective_windows_url() returns the uploaded file URL if a file was
    # uploaded, otherwise falls back to the legacy manual download_url.
    windows_url = active.effective_windows_url()

    if not windows_url:
        # No Windows build available for this release — tell client no update.
        logger.warning(
            f"update_check: active version v{active.version} has no Windows URL. "
            f"Upload a Windows installer or set download_url."
        )
        return JsonResponse({"update_available": False})

    data = {
        "update_available": True,
        "version":          active.version,
        "is_critical":      active.is_critical,
        "changelog":        active.changelog,
        # download_url is always the flat Windows installer URL —
        # updater.py downloads whatever URL is here.
        "download_url":     windows_url,
    }
    if active.min_version:
        data["min_version"] = active.min_version

    logger.info(
        f"update_check: serving v{active.version} to client v{client_version} "
        f"(critical={active.is_critical})"
    )
    return JsonResponse(data)


# ── 2. Public releases list (no auth) ─────────────────────────────────────────
#
# Called by the Download Center page (download.html) via fetch().
# Returns ALL versions ordered newest-first so the page can build:
#   - Latest release card per platform
#   - Full version history with expandable changelogs
#
# GET /api/v1/releases/
# No authentication required — this is a public endpoint.

@require_http_methods(["GET"])
def releases_list(request):
    """
    Public endpoint consumed by the Download Center frontend.

    Query params (all optional):
      ?platform=windows|macos|linux   filter to versions that have a build
                                      for the given platform
      ?limit=N                        max rows returned (default 50)

    Response shape:
    [
      {
        "version":        "1.2.0",
        "release_date":   "2025-03-10T00:00:00+00:00",
        "is_critical":    false,
        "changelog":      "• Bug fixes\n• Performance",
        "platforms":      ["windows", "macos", "linux"],
        "platforms_info": {
          "windows": {
            "download_url": "https://…/media/primebooks/releases/windows/setup.exe",
            "file_size":    "48.3 MB",
            "min_os":       "Windows 10 64-bit",
            "sha256":       "",
            "label":        "Windows Installer (.exe)",
            "alt_builds":   [{"label": "Portable (.zip)", "url": "…"}]
          },
          "macos":   { … },
          "linux":   { … }
        }
      },
      …
    ]
    """
    platform_filter = request.GET.get("platform", "").strip().lower()
    try:
        limit = min(int(request.GET.get("limit", 50)), 200)
    except (ValueError, TypeError):
        limit = 50

    qs = PrimeBooksVersion.objects.order_by("-released_at", "-created_at")[:limit]

    results = []
    for version in qs:
        data = version.to_releases_api_dict()

        # Apply platform filter if requested
        if platform_filter and platform_filter not in data["platforms"]:
            continue

        results.append(data)

    return JsonResponse(results, safe=False)


# ── 3. Crash report intake (authenticated) ────────────────────────────────────
#
# POST /api/v1/crash-reports/
# Headers: Authorization: Bearer <token>, Content-Type: application/json

@csrf_exempt
@require_http_methods(["POST"])
def crash_report(request):
    payload = _get_token_payload(request)
    if payload is None:
        return JsonResponse({"detail": "Unauthorized"}, status=401)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON"}, status=400)

    traceback_str = body.get("traceback", "")
    if not traceback_str:
        return JsonResponse({"detail": "traceback required"}, status=400)

    # Fingerprint = hash of the last meaningful traceback line.
    lines = [l.strip() for l in traceback_str.splitlines() if l.strip()]
    fingerprint_src = lines[-1] if lines else traceback_str
    fingerprint = hashlib.sha256(fingerprint_src.encode()).hexdigest()[:16]

    client_ip = (
        request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
        or request.META.get("REMOTE_ADDR")
    )

    existing = CrashReport.objects.filter(fingerprint=fingerprint).first()
    if existing:
        existing.occurrence_count += 1
        existing.last_seen_at = timezone.now()
        existing.save(update_fields=["occurrence_count", "last_seen_at"])
        logger.debug(
            f"crash_report: duplicate fingerprint {fingerprint} "
            f"(count={existing.occurrence_count})"
        )
    else:
        CrashReport.objects.create(
            schema_name      = body.get("schema_name", ""),
            app_version      = body.get("app_version", ""),
            platform         = body.get("platform", ""),
            traceback        = traceback_str,
            context          = body.get("context", {}),
            fingerprint      = fingerprint,
            client_ip        = client_ip,
        )
        logger.info(
            f"crash_report: new crash from "
            f"{body.get('schema_name', '?')} v{body.get('app_version', '?')}"
        )

    return JsonResponse({"status": "ok"}, status=201)