"""
reports/admin.py
"""

from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from .models import Suggestion, SuggestionUpdate, SuggestionFeedback


class SuggestionUpdateInline(admin.StackedInline):
    model       = SuggestionUpdate
    extra       = 1
    fields      = ('update_type', 'message', ('old_status', 'new_status'), 'is_internal')
    readonly_fields = ()

    def get_queryset(self, request):
        return super().get_queryset(request)


class SuggestionFeedbackInline(admin.TabularInline):
    model           = SuggestionFeedback
    extra           = 0
    readonly_fields = ('rating', 'resolved_ok', 'comment', 'submitted_at')
    can_delete      = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Suggestion)
class SuggestionAdmin(admin.ModelAdmin):
    list_display  = (
        'ticket_badge', 'title', 'type', 'priority_badge',
        'status_badge', 'submitted_by', 'assigned_to', 'created_at',
    )
    list_filter   = ('type', 'priority', 'status', 'created_at')
    search_fields = ('ticket_number', 'title', 'description',
                     'submitted_by__username', 'submitted_by__email')
    ordering      = ('-created_at',)
    readonly_fields = ('ticket_number', 'submitted_by', 'affected_url',
                       'affected_record', 'created_at', 'updated_at',
                       'resolved_at', 'screenshot_preview')
    inlines       = [SuggestionUpdateInline, SuggestionFeedbackInline]

    fieldsets = (
        ('Ticket', {
            'fields': ('ticket_number', 'submitted_by', 'created_at', 'updated_at'),
        }),
        ('Classification', {
            'fields': (('type', 'priority', 'status'), 'assigned_to'),
        }),
        ('Content', {
            'fields': ('title', 'description', 'affected_url', 'affected_record', 'screenshot_preview'),
        }),
        ('Admin Only', {
            'fields': ('internal_note', 'resolved_at'),
            'classes': ('collapse',),
        }),
    )

    # ── Custom display ──────────────────────────────────────

    @admin.display(description='Ticket')
    def ticket_badge(self, obj):
        return format_html(
            '<span style="font-family:monospace;font-weight:600;color:#3b82f6">{}</span>',
            obj.ticket_number,
        )

    @admin.display(description='Priority')
    def priority_badge(self, obj):
        colours = {'low':'#22c55e','medium':'#f59e0b','high':'#ef4444','urgent':'#dc2626'}
        c = colours.get(obj.priority, '#6b7280')
        return format_html(
            '<span style="color:{};font-weight:600;text-transform:capitalize">{}</span>',
            c, obj.get_priority_display(),
        )

    @admin.display(description='Status')
    def status_badge(self, obj):
        colours = {
            'open':'#3b82f6','in_progress':'#8b5cf6',
            'waiting':'#f59e0b','resolved':'#22c55e','closed':'#6b7280',
        }
        c = colours.get(obj.status, '#6b7280')
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:12px;font-size:0.75rem;font-weight:600">{}</span>',
            c, obj.get_status_display(),
        )

    @admin.display(description='Screenshot')
    def screenshot_preview(self, obj):
        if obj.screenshot:
            return format_html(
                '<a href="{}" target="_blank">'
                '<img src="{}" style="max-width:300px;max-height:200px;border-radius:8px;border:1px solid #e5e7eb">'
                '</a>',
                obj.screenshot.url, obj.screenshot.url,
            )
        return '—'

    # ── Actions ──────────────────────────────────────────────

    actions = ['mark_in_progress', 'mark_resolved', 'mark_closed', 'send_acknowledgement']

    @admin.action(description='Mark selected as In Progress')
    def mark_in_progress(self, request, queryset):
        for report in queryset:
            old = report.status
            report.status = 'in_progress'
            report.save()
            SuggestionUpdate.objects.create(
                report=report, author=request.user,
                update_type='status_change',
                old_status=old, new_status='in_progress',
                message='Status updated to In Progress.',
            )
            _notify_user(report, 'Your report is now being reviewed.',
                         f'Hi {report.submitted_by},\n\nYour ticket {report.ticket_number} is now In Progress.\n\nPrimeBooks Support')
        self.message_user(request, f'{queryset.count()} report(s) marked In Progress.')

    @admin.action(description='Mark selected as Resolved')
    def mark_resolved(self, request, queryset):
        for report in queryset:
            old = report.status
            report.status = 'resolved'
            report.resolved_at = timezone.now()
            report.save()
            SuggestionUpdate.objects.create(
                report=report, author=request.user,
                update_type='status_change',
                old_status=old, new_status='resolved',
                message='This issue has been resolved.',
            )
            _notify_user(report, f'Your ticket {report.ticket_number} has been resolved.',
                         f'Hi {report.submitted_by},\n\nGood news — ticket {report.ticket_number} has been resolved.\n\n'
                         f'Was this resolved to your satisfaction?\n'
                         f'✅ Yes: {getattr(settings, "SITE_URL", "")}/suggestions/{report.ticket_number}/?resolved=1\n'
                         f'❌ No:  {getattr(settings, "SITE_URL", "")}/suggestions/{report.ticket_number}/?resolved=0\n\n'
                         f'PrimeBooks Support')
        self.message_user(request, f'{queryset.count()} report(s) marked Resolved.')

    @admin.action(description='Mark selected as Closed')
    def mark_closed(self, request, queryset):
        queryset.update(status='closed')
        self.message_user(request, f'{queryset.count()} report(s) closed.')

    @admin.action(description='Send acknowledgement email')
    def send_acknowledgement(self, request, queryset):
        for report in queryset:
            _notify_user(
                report,
                f'We received your report [{report.ticket_number}]',
                f'Hi {report.submitted_by},\n\nThank you for contacting us. '
                f'Your ticket number is {report.ticket_number}.\n'
                f'We will get back to you as soon as possible.\n\nPrimeBooks Support',
            )
        self.message_user(request, f'Acknowledgement sent for {queryset.count()} report(s).')

    def save_formset(self, request, form, formset, change):
        """Auto-set author on inline ReportUpdate, send email on public replies."""
        instances = formset.save(commit=False)
        for instance in instances:
            if isinstance(instance, SuggestionUpdate):
                if not instance.pk:
                    instance.author = request.user
                instance.save()
                # Email user on non-internal replies
                if not instance.is_internal and instance.message:
                    report = instance.report
                    _notify_user(
                        report,
                        f'Update on your ticket [{report.ticket_number}]',
                        f'Hi {report.submitted_by},\n\n'
                        f'There is an update on ticket {report.ticket_number}:\n\n'
                        f'{instance.message}\n\nPrimeBooks Support',
                    )
        formset.save_m2m()


def _notify_user(report, subject, body):
    """Send email to the report submitter. Silent fail if email not configured."""
    try:
        user = report.submitted_by
        if user and user.email:
            send_mail(
                subject=subject,
                message=body,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@primebooks.sale'),
                recipient_list=[user.email],
                fail_silently=True,
            )
    except Exception:
        pass


@admin.register(SuggestionUpdate)
class ReportUpdateAdmin(admin.ModelAdmin):
    list_display  = ('report', 'author', 'update_type', 'is_internal', 'created_at')
    list_filter   = ('update_type', 'is_internal')
    search_fields = ('report__ticket_number', 'message')
    readonly_fields = ('created_at',)


@admin.register(SuggestionFeedback)
class SuggestionFeedbackAdmin(admin.ModelAdmin):
    list_display  = ('report', 'rating_stars', 'resolved_icon', 'comment_preview', 'submitted_at')
    list_filter   = ('resolved_ok', 'rating', 'submitted_at')
    search_fields = ('report__ticket_number', 'comment', 'report__submitted_by__email')
    readonly_fields = ('report', 'rating', 'resolved_ok', 'comment', 'submitted_at')
    ordering      = ('-submitted_at',)

    @admin.display(description='Rating')
    def rating_stars(self, obj):
        filled = '★' * obj.rating
        empty  = '☆' * (5 - obj.rating)
        colour = {5:'#22c55e', 4:'#84cc16', 3:'#f59e0b', 2:'#f97316', 1:'#ef4444'}.get(obj.rating, '#6b7280')
        return format_html(
            '<span style="color:{};font-size:1rem;letter-spacing:1px">{}</span>'
            '<span style="color:#d1d5db;font-size:1rem;letter-spacing:1px">{}</span>',
            colour, filled, empty,
        )

    @admin.display(description='Resolved?')
    def resolved_icon(self, obj):
        if obj.resolved_ok:
            return format_html('<span style="color:#22c55e;font-weight:700">✓ Yes</span>')
        return format_html('<span style="color:#ef4444;font-weight:700">✗ No</span>')

    @admin.display(description='Comment')
    def comment_preview(self, obj):
        if obj.comment:
            return obj.comment[:80] + ('…' if len(obj.comment) > 80 else '')
        return '—'