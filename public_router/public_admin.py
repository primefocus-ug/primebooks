from django.utils.translation import gettext_lazy as _
from django.contrib import messages
from django.utils.html import format_html
from public_accounts.admin_site import public_admin, PublicModelAdmin
from .models import TenantSignupRequest, SubdomainReservation, PublicNewsletterSubscriber


class TenantSignupRequestAdmin(PublicModelAdmin):
    """Admin interface for TenantSignupRequest"""

    list_display = [
        'company_name', 'subdomain', 'email', 'selected_plan',
        'status_badge', 'tenant_created_badge', 'created_at', 'actions_column'
    ]

    list_filter = [
        'status', 'selected_plan', 'tenant_created', 'country', 'created_at'
    ]

    search_fields = [
        'company_name', 'trading_name', 'subdomain', 'email',
        'admin_email', 'first_name', 'last_name'
    ]

    readonly_fields = [
        'request_id', 'created_at', 'updated_at', 'completed_at',
        'tenant_created', 'created_company_id', 'created_schema_name', 'retry_count'
    ]

    ordering = ['-created_at']

    fieldsets = (
        (_('Request Information'), {
            'fields': (
                'request_id', 'status', 'tenant_created',
                'created_company_id', 'created_schema_name', 'retry_count'
            )
        }),
        (_('Company Information'), {
            'fields': (
                'company_name', 'trading_name', 'subdomain',
                'industry', 'business_type', 'estimated_users'
            )
        }),
        (_('Contact Information'), {
            'fields': (
                'email', 'phone', 'country'
            )
        }),
        (_('Admin User Information'), {
            'fields': (
                'first_name', 'last_name', 'admin_email', 'admin_phone'
            )
        }),
        (_('Plan Selection'), {
            'fields': ('selected_plan',)
        }),
        (_('Technical Details'), {
            'fields': (
                'error_message', 'ip_address', 'user_agent', 'referral_source'
            ),
            'classes': ('collapse',)
        }),
        (_('Important Dates'), {
            'fields': ('created_at', 'updated_at', 'completed_at'),
            'classes': ('collapse',)
        }),
    )

    actions = [
        'mark_as_processing', 'mark_as_completed', 'mark_as_failed', 'retry_processing'
    ]

    def status_badge(self, obj):
        status_colors = {
            'PENDING': 'warning',
            'PROCESSING': 'info',
            'COMPLETED': 'success',
            'FAILED': 'danger',
        }
        color = status_colors.get(obj.status, 'secondary')
        return format_html(
            '<span class="badge bg-{}">{}</span>',
            color,
            obj.get_status_display()
        )

    status_badge.short_description = _('Status')
    status_badge.admin_order_field = 'status'

    def tenant_created_badge(self, obj):
        if obj.tenant_created:
            return format_html('<span class="badge bg-success">✓ {}</span>', _('Created'))
        return format_html('<span class="badge bg-secondary">{}</span>', _('Not Created'))

    tenant_created_badge.short_description = _('Tenant Created')
    tenant_created_badge.admin_order_field = 'tenant_created'

    def actions_column(self, obj):
        # All user-supplied values must go through format_html, never via .format()
        # before format_html sees them — otherwise schema names with ' or " can
        # break out of the onclick attribute.
        parts = []
        if obj.status in ['PENDING', 'FAILED']:
            parts.append(format_html(
                '<span class="badge bg-secondary" title="{}">{}</span>',
                _('Select this row and use the Actions menu above to retry'),
                _('Retry via action menu'),
            ))
        if obj.tenant_created and obj.created_schema_name:
            parts.append(format_html('<code>{}</code>', obj.created_schema_name))
        if parts:
            return format_html(' '.join(['{}'] * len(parts)), *parts)
        return '-'

    actions_column.short_description = _('Actions')

    def mark_as_processing(self, request, queryset):
        from django.utils import timezone
        updated = queryset.update(status='PROCESSING', updated_at=timezone.now())
        self.message_user(
            request,
            _('{} signup request(s) marked as processing.').format(updated),
            messages.SUCCESS
        )

    mark_as_processing.short_description = _("Mark selected as processing")

    def mark_as_completed(self, request, queryset):
        from django.utils import timezone
        # WARNING: This only flips the status flag — it does NOT create the tenant schema.
        # Use "Retry processing" to actually provision a tenant.
        # Only use this to mark requests that were provisioned manually outside this system.
        updated = queryset.update(status='COMPLETED', updated_at=timezone.now())
        self.message_user(
            request,
            _('{} signup request(s) marked as completed '
              '(status flag only — no tenant was created by this action).').format(updated),
            messages.WARNING
        )

    mark_as_completed.short_description = _("Mark selected as completed (status only)")

    def mark_as_failed(self, request, queryset):
        from django.utils import timezone
        updated = queryset.update(status='FAILED', updated_at=timezone.now())
        self.message_user(
            request,
            _('{} signup request(s) marked as failed.').format(updated),
            messages.WARNING
        )

    mark_as_failed.short_description = _("Mark selected as failed")

    def retry_processing(self, request, queryset):
        from .tasks import create_tenant_async
        from .models import TenantApprovalWorkflow
        from django.core.cache import cache
        from django.utils import timezone
        import secrets
        import string

        queued = 0
        skipped = 0

        for signup in queryset:
            if signup.status not in ['PENDING', 'FAILED']:
                skipped += 1
                continue

            # Retrieve the stored password from the approval workflow, or generate
            # a new one. The original form POST password is gone at this point so
            # we rely on what was stored during the first approval attempt.
            password = None
            try:
                workflow = getattr(signup, 'approval_workflow', None)
                if workflow and workflow.generated_password:
                    password = workflow.generated_password
            except Exception:
                pass

            if not password:
                alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
                password = ''.join(secrets.choice(alphabet) for _ in range(12))
                try:
                    workflow, _ = TenantApprovalWorkflow.objects.get_or_create(
                        signup_request=signup
                    )
                    workflow.generated_password = password
                    workflow.save(update_fields=['generated_password', 'updated_at'])
                except Exception as e:
                    self.message_user(
                        request,
                        _('Could not save password for {}: {}').format(
                            signup.company_name, str(e)
                        ),
                        messages.ERROR
                    )
                    continue

            # Mark as processing
            signup.status = 'PROCESSING'
            signup.retry_count += 1
            signup.error_message = ''
            signup.save(update_fields=[
                'status', 'retry_count', 'error_message', 'updated_at'
            ])

            # Fire the Celery task — this is what was missing before
            try:
                task = create_tenant_async.apply_async(
                    args=[str(signup.request_id), password],
                    countdown=2,
                )
                cache.set(
                    f'signup_task_{signup.request_id}',
                    {
                        'task_id': task.id,
                        'retried_by': str(request.user),
                        'retried_at': timezone.now().isoformat(),
                    },
                    timeout=3600
                )
                queued += 1
            except Exception as e:
                signup.status = 'FAILED'
                signup.error_message = f'Task dispatch failed: {str(e)}'
                signup.save(update_fields=['status', 'error_message', 'updated_at'])
                self.message_user(
                    request,
                    _('Failed to queue task for {}: {}').format(
                        signup.company_name, str(e)
                    ),
                    messages.ERROR
                )

        if queued:
            self.message_user(
                request,
                _('{} signup request(s) queued for retry. '
                  'Refresh in 30–60 seconds to see the result.').format(queued),
                messages.SUCCESS
            )
        if skipped:
            self.message_user(
                request,
                _('{} request(s) skipped — only PENDING or FAILED can be retried.').format(
                    skipped
                ),
                messages.WARNING
            )

    retry_processing.short_description = _("Retry processing selected requests")


class SubdomainReservationAdmin(PublicModelAdmin):
    """Admin interface for SubdomainReservation"""

    list_display = [
        'subdomain', 'reason_badge', 'notes_preview', 'created_at'
    ]

    list_filter = ['reason', 'created_at']

    search_fields = ['subdomain', 'notes']

    readonly_fields = ['created_at']

    ordering = ['-created_at']

    fieldsets = (
        (_('Reservation Details'), {
            'fields': ('subdomain', 'reason', 'notes')
        }),
        (_('Metadata'), {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )

    def reason_badge(self, obj):
        reason_colors = {
            'SYSTEM': 'primary',
            'BRAND': 'info',
            'BLOCKED': 'danger',
        }
        color = reason_colors.get(obj.reason, 'secondary')
        return format_html(
            '<span class="badge bg-{}">{}</span>',
            color,
            obj.get_reason_display()
        )

    reason_badge.short_description = _('Reason')
    reason_badge.admin_order_field = 'reason'

    def notes_preview(self, obj):
        if obj.notes:
            return obj.notes[:50] + '...' if len(obj.notes) > 50 else obj.notes
        return '-'

    notes_preview.short_description = _('Notes Preview')


class PublicNewsletterSubscriberAdmin(PublicModelAdmin):
    """Admin interface for PublicNewsletterSubscriber"""

    list_display = [
        'email', 'name', 'status_badge', 'subscribed_at'
    ]

    list_filter = ['is_active', 'subscribed_at']

    search_fields = ['email', 'name']

    readonly_fields = ['subscribed_at']

    ordering = ['-subscribed_at']

    fieldsets = (
        (_('Subscriber Information'), {
            'fields': ('email', 'name', 'is_active')
        }),
        (_('Metadata'), {
            'fields': ('subscribed_at',),
            'classes': ('collapse',)
        }),
    )

    actions = ['activate_subscribers', 'deactivate_subscribers']

    def status_badge(self, obj):
        if obj.is_active:
            return format_html('<span class="badge bg-success">{}</span>', _('Active'))
        return format_html('<span class="badge bg-secondary">{}</span>', _('Inactive'))

    status_badge.short_description = _('Status')
    status_badge.admin_order_field = 'is_active'

    def activate_subscribers(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(
            request,
            _('{} subscriber(s) activated.').format(updated),
            messages.SUCCESS
        )

    activate_subscribers.short_description = _("Activate selected subscribers")

    def deactivate_subscribers(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(
            request,
            _('{} subscriber(s) deactivated.').format(updated),
            messages.WARNING
        )

    deactivate_subscribers.short_description = _("Deactivate selected subscribers")


# Register models with public admin
public_admin.register(TenantSignupRequest, TenantSignupRequestAdmin, app_label='public_accounts')
public_admin.register(SubdomainReservation, SubdomainReservationAdmin, app_label='public_accounts')
public_admin.register(PublicNewsletterSubscriber, PublicNewsletterSubscriberAdmin, app_label='public_accounts')