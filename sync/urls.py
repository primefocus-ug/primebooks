"""
sync/urls.py
============
All desktop sync endpoints.

Register in your main urls.py with:
    path("api/v1/", include("sync.urls")),

AND the desktop auth login under the tenant subdomain:
    path("api/desktop/", include("sync.desktop_urls")),
"""
from django.urls import path
from .pull_view  import sync_pull
from .push_view  import sync_push
from .ping_view  import sync_ping
from .update_views import update_check, crash_report_submit


app_name = "sync"

urlpatterns = [
    # Core sync protocol — used by sync/engine.py
    path("sync/pull/",  sync_pull,  name="sync-pull"),
    path("sync/push/",  sync_push,  name="sync-push"),
    path("sync/ping/",  sync_ping,  name="sync-ping"),
    # ── Updates & crash reporting ─────────────────────────────────────────
    path("updates/check/",       update_check,          name="update-check"),
    path("crash-reports/",       crash_report_submit,   name="crash-report"),
]