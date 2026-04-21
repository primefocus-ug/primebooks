# primebooks/middleware/debug_403.py — replace entirely

import logging
import traceback

logger = logging.getLogger('django.request')

TARGET = 'price-reduction-requests'


class Debug403Middleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if TARGET not in request.path:
            return self.get_response(request)

        logger.info(
            "DEBUG_403 >>> ENTER %s user=%s",
            request.path,
            getattr(request, 'user', 'no-user-yet'),
        )

        response = self._call_with_patches(request)

        logger.info("DEBUG_403 >>> EXIT status=%s", response.status_code)
        return response

    def _call_with_patches(self, request):
        # ── 1. Patch DRF's permission_denied ──────────────────────────────
        drf_patcher = _patch_drf_permission_denied()

        # ── 2. Patch Django's PermissionDenied exception handler ──────────
        django_patcher = _patch_django_permission_denied()

        # ── 3. NEW: Patch HttpResponseForbidden.__init__ directly ─────────
        #    This catches raw HttpResponseForbidden() constructions that
        #    bypass both the exception system and DRF's permission layer.
        forbidden_patcher = _patch_http_response_forbidden()

        try:
            response = self.get_response(request)
        finally:
            drf_patcher()
            django_patcher()
            forbidden_patcher()

        if response.status_code == 403:
            logger.error(
                "DEBUG_403 >>> 403 reached middleware STILL uncaught — "
                "something returned a 403 response object that was not "
                "constructed via HttpResponseForbidden() (e.g. HttpResponse(status=403)). "
                "Stack at middleware exit:\n%s",
                ''.join(traceback.format_stack()),
            )

        return response


# ─────────────────────────────────────────────────────────────────────────────
# Patch helpers
# ─────────────────────────────────────────────────────────────────────────────

def _patch_http_response_forbidden():
    """
    Monkey-patch HttpResponseForbidden.__init__ so we get a full stack
    trace at the exact point the 403 response object is *constructed*,
    not just when it arrives back at middleware.

    This catches patterns like:
        return HttpResponseForbidden()          # direct construction
        return HttpResponseForbidden("reason")  # with message
    but NOT:
        return HttpResponse(status=403)         # bypasses this patch too
    A second patch on HttpResponse.__init__ handles that case.
    """
    from django.http import HttpResponseForbidden, HttpResponse

    # ── Patch HttpResponseForbidden ──
    original_forbidden_init = HttpResponseForbidden.__init__

    def patched_forbidden_init(self, *args, **kwargs):
        logger.error(
            "DEBUG_403 >>> HttpResponseForbidden() constructed here:\n%s",
            ''.join(traceback.format_stack()),
        )
        original_forbidden_init(self, *args, **kwargs)

    HttpResponseForbidden.__init__ = patched_forbidden_init

    # ── Also patch HttpResponse.__init__ to catch HttpResponse(status=403) ──
    original_response_init = HttpResponse.__init__

    def patched_response_init(self, *args, **kwargs):
        if kwargs.get('status') == 403 or (args and args[0] == 403):
            logger.error(
                "DEBUG_403 >>> HttpResponse(status=403) constructed here:\n%s",
                ''.join(traceback.format_stack()),
            )
        original_response_init(self, *args, **kwargs)

    HttpResponse.__init__ = patched_response_init

    def undo():
        HttpResponseForbidden.__init__ = original_forbidden_init
        HttpResponse.__init__ = original_response_init

    return undo


def _patch_drf_permission_denied():
    """
    Intercept APIView.permission_denied() — called by DRF before raising
    PermissionDenied, so we can log which view and permission class said no.
    """
    try:
        from rest_framework.views import APIView
    except ImportError:
        return lambda: None

    original = APIView.permission_denied

    def patched(self, request, message=None, code=None):
        logger.error(
            "DEBUG_403 >>> DRF permission_denied in view=%s\n"
            "  message=%r  code=%r\n"
            "  permission_classes=%s\n"
            "Stack:\n%s",
            type(self).__name__,
            message,
            code,
            [pc.__name__ for pc in getattr(type(self), 'permission_classes', [])],
            ''.join(traceback.format_stack()),
        )
        original(self, request, message=message, code=code)

    APIView.permission_denied = patched
    return lambda: setattr(APIView, 'permission_denied', original)


def _patch_django_permission_denied():
    """
    Intercept Django's response_for_exception so we catch PermissionDenied
    exceptions from non-DRF views and middleware.
    """
    try:
        import django.core.handlers.exception as exc_module
    except ImportError:
        return lambda: None

    original_convert = exc_module.response_for_exception

    def patched_convert(request, exc):
        from django.core.exceptions import PermissionDenied as DjangoPermDenied
        if isinstance(exc, DjangoPermDenied):
            logger.error(
                "DEBUG_403 >>> Django PermissionDenied raised\n"
                "  exc=%r\n"
                "Stack:\n%s",
                exc,
                ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
            )
        return original_convert(request, exc)

    exc_module.response_for_exception = patched_convert
    return lambda: setattr(exc_module, 'response_for_exception', original_convert)