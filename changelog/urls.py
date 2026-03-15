"""
changelog/urls.py

Add to tenancy/public_urls.py:
    path('changelog/', include('changelog.urls')),
    path('announcements/', include('changelog.urls')),
"""

from django.urls import path
from .views import (
    dismiss_changelog,
    dismiss_announcement,
    push_release,
    changelog_admin_preview,
)

urlpatterns = [
    path('changelog/dismiss/', dismiss_changelog, name='changelog_dismiss'),
    path('announcements/<int:pk>/dismiss/', dismiss_announcement, name='announcement_dismiss'),

    # Admin-only: push a release to all users (per-row button in list view)
    # Staff-only — protected by @staff_member_required in the view
    path('<int:pk>/push/',              push_release,           name='changelog_push'),

    # Admin-only: preview a release modal before pushing
    # Staff-only — protected by @staff_member_required in the view
    path('<int:pk>/preview/',           changelog_admin_preview, name='changelog_admin_preview'),
]