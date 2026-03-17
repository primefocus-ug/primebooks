"""
changelog/views.py

Changes from previous version:
  - context processor now respects release_type and is_minor_push
    when deciding whether to show the modal
  - added changelog_admin_preview view for the admin Preview button
  - added push_release view for the per-row Push button in admin list

URL wiring — add to tenancy/public_urls.py:
    from django.urls import path, include
    path('changelog/', include('changelog.urls')),
    path('announcements/', include('changelog.urls')),
"""

import json
import re
from django.http                    import HttpResponse, JsonResponse
from django.views.decorators.http   import require_POST, require_GET
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.utils                   import timezone
from django.db.models               import Q
from django.shortcuts               import get_object_or_404
from django.urls                    import reverse

from .models import (
    ChangelogRelease, ChangelogView,
    Announcement, AnnouncementDismissal,
)


# ═════════════════════════════════════════════════════════════
# Context Processor
# ═════════════════════════════════════════════════════════════

def _is_public_schema():
    """
    Return True when the active DB connection is on the public schema.
    changelog's ChangelogRelease/Announcement models live in SHARED_APPS
    (public schema) so they are always accessible. However we still skip
    the full context on the public schema admin to avoid unnecessary DB
    hits and any edge-case issues with AnnouncementDismissal user_id
    lookups when there are no tenant users present.
    """
    try:
        from django.db import connection
        schema = getattr(connection, 'schema_name', None)
        if schema is None:
            schema = getattr(connection, 'get_schema', lambda: None)()
        return schema == 'public'
    except Exception:
        return False


def changelog_context(request):
    """
    Injects changelog + announcement data into every authenticated template.

    Announcements and the changelog modal are fetched independently so that
    a missing release, schema guard, or any exception in one path never
    silences the other.

    Show logic:
      For major/minor releases:
        → Show if the user has no ChangelogView record for this release
          (i.e. they've never seen it), OR if is_minor_push=True and their
          view record has dismissed_at set (meaning they saw it before but
          a new push requires them to see it again).

      For patch releases:
        → Only show if is_minor_push=True (admin explicitly pushed it).
          Without a push, patch releases are silent.

      opted_out = True:
        → Never show, regardless of push.
    """
    if not getattr(request, 'user', None) or not request.user.is_authenticated:
        return _empty_context()

    user_id = request.user.id

    # ── Announcements ──────────────────────────────────────────────
    # Fetched first, independently — a broken changelog release must never
    # silence announcements.  Announcement model is in SHARED_APPS so it is
    # always reachable regardless of the active schema.
    active_announcements = []
    try:
        dismissed_ann_ids = AnnouncementDismissal.objects.filter(
            user_id=user_id
        ).values_list('announcement_id', flat=True)

        now = timezone.now()
        active_announcements = list(
            Announcement.objects
            .filter(is_active=True, starts_at__lte=now)
            .exclude(pk__in=dismissed_ann_ids)
            .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=now))
            .order_by('-starts_at')
        )
    except Exception:
        pass  # never let announcement errors break the page

    # ── Changelog modal ────────────────────────────────────────────
    # Skip on the public-schema admin panel — no tenant users there and
    # ChangelogView cross-schema lookups can cause edge-case DB issues.
    show_release = None
    resume_slide = 0
    opted_out    = False

    if not _is_public_schema():
        try:
            release = ChangelogRelease.get_latest_active()
        except Exception:
            release = None

        if release:
            view_record = ChangelogView.objects.filter(
                user_id=user_id, release=release
            ).first()

            if view_record and view_record.opted_out:
                # User permanently opted out — never show
                show_release = None
                opted_out    = True

            elif view_record and view_record.dismissed_at:
                # User has previously seen and dismissed this release.
                # Only re-show if admin pushed a new minor update.
                if release.is_minor_push:
                    show_release = release
                    resume_slide = 0  # always start from beginning on a push
                else:
                    show_release = None

            elif view_record and not view_record.dismissed_at:
                # User opened modal but never dismissed — resume where they left off
                show_release = release
                resume_slide = view_record.last_slide

            else:
                # No view record at all — first time seeing this release
                # For patch releases, only show if admin explicitly pushed
                if release.release_type == 'patch' and not release.is_minor_push:
                    show_release = None
                else:
                    show_release = release
                    resume_slide = 0

    slides_data = _build_slides_data(show_release)

    return {
        'changelog_release':      show_release,
        'changelog_slides':       slides_data,
        'changelog_resume_slide': resume_slide,
        'changelog_opted_out':    opted_out,
        'active_announcements':   active_announcements,
    }


def _empty_context():
    return {
        'changelog_release':      None,
        'changelog_slides':       [],
        'changelog_resume_slide': 0,
        'changelog_opted_out':    False,
        'active_announcements':   [],
    }


def _normalize_embed_url(url):
    """
    Convert YouTube watch/share URLs to their embeddable /embed/ form.
    Returns the URL unchanged for non-YouTube or already-correct embed URLs.

    Handles:
      https://www.youtube.com/watch?v=VIDEO_ID
      https://youtu.be/VIDEO_ID
      https://www.youtube.com/shorts/VIDEO_ID
      https://www.youtube.com/embed/VIDEO_ID  ← already correct, left alone
    """
    if not url:
        return url
    match = re.search(
        r'(?:youtu\.be/|youtube\.com/(?:watch\?v=|shorts/))([\w-]+)',
        url,
    )
    if match:
        return f'https://www.youtube.com/embed/{match.group(1)}'
    return url


def _build_slides_data(release):
    if not release:
        return []
    return [
        {
            'id':                 slide.pk,
            'order':              slide.order,
            'tag':                slide.tag,
            'tag_display':        slide.get_tag_display(),
            'title':              slide.title,
            'description':        slide.description,
            'chips':              slide.chips,
            'media_type':         slide.media_type,
            'media_url':          _normalize_embed_url(slide.resolved_media_url),
            'media_alt':          slide.media_alt,
            'media_poster':       slide.resolved_media_poster,
            'before_image':       slide.resolved_before_image,
            'after_image':        slide.resolved_after_image,
            'highlight_selector': slide.highlight_selector,
            'highlight_label':    slide.highlight_label,
        }
        for slide in release.slides.all()
    ]


# ═════════════════════════════════════════════════════════════
# API: Dismiss changelog
# POST /changelog/dismiss/
# ═════════════════════════════════════════════════════════════

@login_required
@require_POST
def dismiss_changelog(request):
    try:
        data       = json.loads(request.body)
        release_id = int(data.get('release_id', 0))
        last_slide = int(data.get('last_slide', 0))
        opted_out  = bool(data.get('opted_out', False))
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({'error': 'Invalid payload'}, status=400)

    try:
        release = ChangelogRelease.objects.get(pk=release_id, is_active=True)
    except ChangelogRelease.DoesNotExist:
        return JsonResponse({'error': 'Release not found'}, status=404)

    ChangelogView.objects.update_or_create(
        user_id=request.user.id,
        release=release,
        defaults={
            'last_slide':   last_slide,
            'opted_out':    opted_out,
            'dismissed_at': timezone.now(),
        },
    )
    return JsonResponse({'ok': True})


# ═════════════════════════════════════════════════════════════
# API: Dismiss announcement
# POST /announcements/<pk>/dismiss/
# ═════════════════════════════════════════════════════════════

@login_required
@require_POST
def dismiss_announcement(request, pk):
    try:
        announcement = Announcement.objects.get(pk=pk, is_active=True)
    except Announcement.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)

    AnnouncementDismissal.objects.get_or_create(
        user_id=request.user.id,
        announcement=announcement,
    )
    return JsonResponse({'ok': True})


# ═════════════════════════════════════════════════════════════
# Admin: Push a release from URL (per-row button)
# GET /changelog/<pk>/push/   (staff only)
# ═════════════════════════════════════════════════════════════

@staff_member_required
def push_release(request, pk):
    """
    Called by the 📢 Push button in the admin list view.
    Triggers push_to_all_users() and redirects back to changelist.
    """
    from django.contrib import messages as django_messages

    release = get_object_or_404(ChangelogRelease, pk=pk, is_active=True)
    deleted = release.push_to_all_users(pushed_by_username=request.user.username)

    django_messages.success(
        request,
        f'✅ "{release.version_tag}" pushed to all users. '
        f'Cleared {deleted} existing view record(s). '
        f'Users will see the What\'s New modal on next login.',
    )
    return _redirect_to_changelist()


# ═════════════════════════════════════════════════════════════
# Admin: Preview a release modal
# GET /changelog/<pk>/preview/   (staff only)
# ═════════════════════════════════════════════════════════════

@staff_member_required
def changelog_admin_preview(request, pk):
    """
    Renders a standalone preview of the changelog modal for a given release.
    Linked from the "👁 Preview modal" button in the admin change form.
    Staff only — does NOT record a ChangelogView entry.
    """
    release     = get_object_or_404(ChangelogRelease, pk=pk)
    slides_data = _build_slides_data(release)

    # Build URLs
    push_url = reverse('changelog_push', args=[pk])
    back_url = reverse('admin:changelog_changelogrelease_change', args=[pk])
    slides_json = json.dumps(slides_data)

    # ── Build slides HTML separately to avoid nested f-string issues
    #    (nested triple-quoted f-strings are a SyntaxError in Python < 3.12)
    if slides_data:
        slide_parts = []
        for s in slides_data:
            tag_html = (
                '<div style="font-size:0.67rem;font-weight:700;text-transform:uppercase;'
                'letter-spacing:0.06em;color:#6366f1;margin-bottom:0.35rem">'
                + s['tag_display']
                + '</div>'
            )
            title_html = (
                '<div style="font-size:0.95rem;font-weight:700;color:#111827;margin-bottom:0.35rem">'
                + s['title']
                + '</div>'
            )
            desc_html = (
                '<div style="font-size:0.835rem;color:#6b7280;line-height:1.6">'
                + s['description']
                + '</div>'
            )
            slide_parts.append(
                '<div style="border:1px solid #e5e7eb;border-radius:10px;'
                'padding:1rem;margin-bottom:0.75rem">'
                + tag_html + title_html + desc_html
                + '</div>'
            )
        slides_html = ''.join(slide_parts)
    else:
        slides_html = (
            '<p style="color:#9ca3af;text-align:center;padding:2rem 0">'
            'No slides yet \u2014 add slides in the admin.</p>'
        )

    slide_count_label = '{} slide(s) \u00b7 {}'.format(
        len(slides_data),
        release.get_release_type_display(),
    )

    html = (
        '<!DOCTYPE html>'
        '<html lang="en" data-theme="light">'
        '<head>'
        '<meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Preview: ' + release.version_tag + '</title>'
        '<link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css" rel="stylesheet">'
        '<style>'
        'body{margin:0;background:#f3f4f6;font-family:system-ui,sans-serif}'
        '.preview-bar{'
            'position:fixed;top:0;left:0;right:0;z-index:99999;'
            'background:#1e293b;color:#f1f5f9;'
            'padding:0.6rem 1.25rem;'
            'display:flex;align-items:center;gap:1rem;font-size:0.82rem}'
        '.preview-bar strong{color:#818cf8}'
        '.preview-bar a{'
            'margin-left:auto;background:#8b5cf6;color:#fff;'
            'padding:0.3rem 0.9rem;border-radius:6px;text-decoration:none;'
            'font-weight:600;font-size:0.78rem}'
        '.preview-bar a.back{background:#374151;margin-left:0}'
        '.preview-notice{'
            'margin-top:44px;padding:0.5rem 1rem;'
            'background:#fef3c7;border-bottom:1px solid #fcd34d;'
            'font-size:0.78rem;color:#92400e;text-align:center}'
        '</style>'
        '</head>'
        '<body>'
        '<div class="preview-bar">'
            '<a href="' + back_url + '" class="back">\u2190 Back to admin</a>'
            '<span>Preview: <strong>' + release.version_tag + '</strong> \u2014 ' + release.title + '</span>'
            '<a href="' + push_url + '">\U0001f4e2 Push to all users</a>'
        '</div>'
        '<div class="preview-notice">'
            '\u26a0\ufe0f Admin preview \u2014 this modal will appear to users on their next login. '
            'View records are <strong>not</strong> recorded during preview.'
        '</div>'
        '<script>'
        'window.__PREVIEW_RELEASE__ = {'
            'id:' + str(release.pk) + ','
            'version_tag:"' + release.version_tag + '",'
            'title:"' + release.title.replace('"', '\\"') + '",'
            'subtitle:"' + release.subtitle.replace('"', '\\"') + '",'
            'slides:' + slides_json +
        '};'
        'window.__IS_PREVIEW__ = true;'
        '</script>'
        '<link rel="stylesheet" href="/static/css/changelog_modal.css" onerror="this.remove()">'
        '<div id="cl-preview-fallback" style="'
            'display:flex;align-items:center;justify-content:center;'
            'min-height:calc(100vh - 80px);padding:2rem">'
            '<div style="'
                'background:#fff;border:1px solid #e5e7eb;border-radius:16px;'
                'width:100%;max-width:640px;padding:2rem;'
                'box-shadow:0 20px 60px rgba(0,0,0,0.12);'
                'font-family:system-ui,sans-serif">'
                '<div style="display:flex;align-items:center;gap:0.75rem;margin-bottom:1.5rem">'
                    '<span style="'
                        'background:linear-gradient(135deg,#6366f1,#8b5cf6);'
                        'color:#fff;border-radius:20px;padding:0.2rem 0.75rem;'
                        'font-size:0.7rem;font-weight:700;letter-spacing:0.06em">'
                        '\u2736 WHAT\'S NEW'
                    '</span>'
                    '<code style="'
                        'background:#f3f4f6;border:1px solid #e5e7eb;border-radius:6px;'
                        'padding:0.15rem 0.5rem;font-size:0.7rem;color:#6b7280">'
                        + release.version_tag +
                    '</code>'
                    '<div>'
                        '<div style="font-size:0.85rem;font-weight:700;color:#111827">' + release.title + '</div>'
                        '<div style="font-size:0.72rem;color:#6b7280">' + release.subtitle + '</div>'
                    '</div>'
                '</div>'
                + slides_html +
                '<div style="'
                    'margin-top:1rem;padding-top:1rem;border-top:1px solid #e5e7eb;'
                    'font-size:0.75rem;color:#9ca3af;text-align:center">'
                    + slide_count_label +
                '</div>'
            '</div>'
        '</div>'
        '</body>'
        '</html>'
    )

    return HttpResponse(html)


def _redirect_to_changelist():
    from django.http import HttpResponseRedirect
    return HttpResponseRedirect(
        reverse('admin:changelog_changelogrelease_changelist')
    )