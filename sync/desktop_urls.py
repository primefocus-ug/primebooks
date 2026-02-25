"""
sync/desktop_urls.py
====================
Desktop-specific endpoints mounted under /api/desktop/.

Register in your main urls.py:
    path("api/desktop/", include("sync.desktop_urls")),

These complement the existing:
    path("api/desktop/sync/current-user/", ...)
    path("api/desktop/sync/user/<str:email>/", ...)
"""
from django.urls import path
from .login_view import desktop_login

app_name = "sync_desktop"

urlpatterns = [
    path("auth/login/", desktop_login, name="desktop-login"),
]