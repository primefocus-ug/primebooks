# saad/urls.py
from django.urls import path
from . import views

urlpatterns = [
    # ── Desktop client endpoints (authenticated via Bearer token) ──
    path("updates/check/",   views.update_check,   name="update-check"),
    path("crash-reports/",   views.crash_report,   name="crash-report"),

    # ── Public Download Center endpoint (no auth) ──
    # Consumed by download.html via fetch('/api/v1/releases/')
    path("releases/",        views.releases_list,  name="releases-list"),
]