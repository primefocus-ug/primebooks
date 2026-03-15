"""
onboarding/admin.py
"""

from django.contrib import admin
from django.utils.html import format_html
from .models import OnboardingProgress, ONBOARDING_STEPS


@admin.register(OnboardingProgress)
class OnboardingProgressAdmin(admin.ModelAdmin):
    list_display   = (
        'user', 'progress_bar', 'percent_label',
        'is_complete', 'dismissed', 'welcome_seen',
        'started_at', 'completed_at',
    )
    list_filter    = ('dismissed', 'welcome_seen',
                      'company_profile', 'first_product',
                      'invite_user', 'first_invoice', 'efris_config')
    search_fields  = ('user__username', 'user__email', 'user__first_name', 'user__last_name')
    readonly_fields = ('started_at', 'completed_at', 'percent_label', 'progress_bar')
    ordering       = ('-started_at',)

    fieldsets = (
        ('User', {
            'fields': ('user', 'started_at', 'completed_at'),
        }),
        ('Progress', {
            'fields': (
                'progress_bar',
                ('company_profile', 'first_product'),
                ('invite_user',     'first_invoice'),
                ('efris_config',),
            ),
        }),
        ('Preferences', {
            'fields': ('dismissed', 'welcome_seen'),
        }),
    )

    @admin.display(description='Progress')
    def progress_bar(self, obj):
        pct = obj.percent
        colour = '#22c55e' if pct == 100 else '#3b82f6' if pct >= 50 else '#f59e0b'
        return format_html(
            '<div style="background:#e5e7eb;border-radius:4px;width:160px;height:10px;overflow:hidden">'
            '<div style="background:{};width:{}%;height:100%;border-radius:4px;transition:width 0.3s"></div>'
            '</div>',
            colour, pct,
        )

    @admin.display(description='%')
    def percent_label(self, obj):
        pct = obj.percent
        colour = '#22c55e' if pct == 100 else '#3b82f6' if pct >= 50 else '#f59e0b'
        return format_html(
            '<span style="color:{};font-weight:700">{}%</span>', colour, pct,
        )

    @admin.display(description='Complete', boolean=True)
    def is_complete(self, obj):
        return obj.is_complete

    actions = ['reset_progress', 'mark_all_complete']

    @admin.action(description='Reset onboarding progress for selected users')
    def reset_progress(self, request, queryset):
        from .models import ALL_STEP_KEYS
        for progress in queryset:
            for key in ALL_STEP_KEYS:
                setattr(progress, key, False)
            progress.completed_at  = None
            progress.dismissed     = False
            progress.welcome_seen  = False
            progress.save()
        self.message_user(request, f'Reset {queryset.count()} onboarding record(s).')

    @admin.action(description='Mark all steps complete for selected users')
    def mark_all_complete(self, request, queryset):
        from django.utils import timezone
        from .models import ALL_STEP_KEYS
        for progress in queryset:
            for key in ALL_STEP_KEYS:
                setattr(progress, key, True)
            progress.completed_at = timezone.now()
            progress.save()
        self.message_user(request, f'Completed {queryset.count()} onboarding record(s).')