from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from django.contrib import messages
from django.utils import timezone
from django.contrib import admin
from public_accounts.admin_site import public_admin, PublicModelAdmin
from .models import SupportTicket, TicketReply, FAQ, ContactRequest


class TicketReplyInline(admin.TabularInline):
    """Inline for TicketReply"""
    model = TicketReply
    extra = 0
    readonly_fields = ['created_at']
    fields = ['sender_name', 'sender_email', 'message', 'is_internal_note', 'is_staff', 'created_at']

    def has_add_permission(self, request, obj):
        return True


class SupportTicketAdmin(PublicModelAdmin):
    """Admin interface for SupportTicket"""

    list_display = [
        'ticket_number', 'subject_preview', 'customer_info',
        'category_badge', 'priority_badge', 'status_badge',
        'assigned_to', 'created_at', 'actions_column'
    ]

    list_filter = [
        'status', 'priority', 'category', 'created_at', 'assigned_to_email'
    ]

    search_fields = [
        'ticket_number', 'subject', 'message', 'name', 'email', 'company_name'
    ]

    readonly_fields = [
        'ticket_id', 'ticket_number', 'created_at', 'updated_at',
        'first_response_at', 'resolved_at', 'closed_at',
        'response_time_minutes', 'resolution_time_minutes',
        'ip_address', 'user_agent', 'referrer'
    ]

    ordering = ['-created_at']

    fieldsets = (
        (_('Ticket Information'), {
            'fields': (
                'ticket_number', 'status', 'priority', 'category'
            )
        }),
        (_('Customer Information'), {
            'fields': (
                'name', 'email', 'phone', 'company_name'
            )
        }),
        (_('Ticket Details'), {
            'fields': (
                'subject', 'message'
            )
        }),
        (_('Assignment'), {
            'fields': (
                'assigned_to_email',
            )
        }),
        (_('Timestamps'), {
            'fields': (
                'created_at', 'updated_at', 'first_response_at',
                'resolved_at', 'closed_at'
            ),
            'classes': ('collapse',)
        }),
        (_('Metrics'), {
            'fields': (
                'response_time_minutes', 'resolution_time_minutes'
            ),
            'classes': ('collapse',)
        }),
        (_('Technical Information'), {
            'fields': (
                'ip_address', 'user_agent', 'referrer'
            ),
            'classes': ('collapse',)
        }),
    )

    inlines = [TicketReplyInline]

    actions = [
        'mark_as_open', 'mark_as_pending', 'mark_as_resolved',
        'mark_as_closed', 'assign_to_staff'
    ]

    def subject_preview(self, obj):
        return obj.subject[:60] + '...' if len(obj.subject) > 60 else obj.subject

    subject_preview.short_description = _('Subject')

    def customer_info(self, obj):
        return format_html(
            '{}<br><small class="text-muted">{}</small>',
            obj.name,
            obj.email
        )

    customer_info.short_description = _('Customer')

    def category_badge(self, obj):
        colors = {
            'SALES': 'primary',
            'DEMO': 'info',
            'PRICING': 'warning',
            'TECHNICAL': 'danger',
            'FEATURE': 'success',
            'OTHER': 'secondary'
        }
        color = colors.get(obj.category, 'secondary')
        return format_html(
            '<span class="badge bg-{}">{}</span>',
            color,
            obj.get_category_display()
        )

    category_badge.short_description = _('Category')
    category_badge.admin_order_field = 'category'

    def priority_badge(self, obj):
        colors = {
            'LOW': 'secondary',
            'MEDIUM': 'info',
            'HIGH': 'warning',
            'URGENT': 'danger'
        }
        color = colors.get(obj.priority, 'secondary')
        return format_html(
            '<span class="badge bg-{}">{}</span>',
            color,
            obj.get_priority_display()
        )

    priority_badge.short_description = _('Priority')
    priority_badge.admin_order_field = 'priority'

    def status_badge(self, obj):
        colors = {
            'NEW': 'primary',
            'OPEN': 'info',
            'PENDING': 'warning',
            'RESOLVED': 'success',
            'CLOSED': 'secondary'
        }
        color = colors.get(obj.status, 'secondary')
        return format_html(
            '<span class="badge bg-{}">{}</span>',
            color,
            obj.get_status_display()
        )

    status_badge.short_description = _('Status')
    status_badge.admin_order_field = 'status'

    def assigned_to(self, obj):
        if obj.assigned_to_email:
            return obj.assigned_to_email
        return format_html('<span class="text-muted">{}</span>', _('Unassigned'))

    assigned_to.short_description = _('Assigned To')
    assigned_to.admin_order_field = 'assigned_to_email'

    def actions_column(self, obj):
        buttons = []
        if obj.status in ['NEW', 'OPEN', 'PENDING']:
            buttons.append(
                '<button class="button" onclick="alert(\'Resolve ticket: {}\')">{}</button>'.format(
                    obj.ticket_number, _('Resolve')
                )
            )
        if obj.status != 'CLOSED':
            buttons.append(
                '<button class="button" onclick="alert(\'Close ticket: {}\')">{}</button>'.format(
                    obj.ticket_number, _('Close')
                )
            )
        return format_html(' '.join(buttons)) if buttons else '-'

    actions_column.short_description = _('Actions')

    def mark_as_open(self, request, queryset):
        updated = queryset.update(status='OPEN')
        self.message_user(
            request,
            _('{} ticket(s) marked as open.').format(updated),
            messages.SUCCESS
        )

    mark_as_open.short_description = _("Mark selected as open")

    def mark_as_pending(self, request, queryset):
        updated = queryset.update(status='PENDING')
        self.message_user(
            request,
            _('{} ticket(s) marked as pending.').format(updated),
            messages.INFO
        )

    mark_as_pending.short_description = _("Mark selected as pending")

    def mark_as_resolved(self, request, queryset):
        for ticket in queryset:
            ticket.mark_resolved()
        self.message_user(
            request,
            _('{} ticket(s) marked as resolved.').format(queryset.count()),
            messages.SUCCESS
        )

    mark_as_resolved.short_description = _("Mark selected as resolved")

    def mark_as_closed(self, request, queryset):
        for ticket in queryset:
            ticket.mark_closed()
        self.message_user(
            request,
            _('{} ticket(s) marked as closed.').format(queryset.count()),
            messages.SUCCESS
        )

    mark_as_closed.short_description = _("Mark selected as closed")

    def assign_to_staff(self, request, queryset):
        # This would typically open a form to select staff member
        self.message_user(
            request,
            _('Assign functionality would be implemented here.'),
            messages.INFO
        )

    assign_to_staff.short_description = _("Assign to staff")


class TicketReplyAdmin(PublicModelAdmin):
    """Admin interface for TicketReply"""

    list_display = [
        'ticket_link', 'sender_info', 'message_preview',
        'staff_badge', 'internal_badge', 'created_at'
    ]

    list_filter = [
        'is_staff', 'is_internal_note', 'created_at'
    ]

    search_fields = [
        'ticket__ticket_number', 'sender_name', 'sender_email', 'message'
    ]

    readonly_fields = ['created_at']

    ordering = ['-created_at']

    def ticket_link(self, obj):
        return format_html(
            '<a href="{}">{}</a>',
            f"/admin/public_support/supportticket/{obj.ticket.ticket_id}/change/",
            obj.ticket.ticket_number
        )

    ticket_link.short_description = _('Ticket')
    ticket_link.admin_order_field = 'ticket__ticket_number'

    def sender_info(self, obj):
        return format_html(
            '{}<br><small class="text-muted">{}</small>',
            obj.sender_name,
            obj.sender_email
        )

    sender_info.short_description = _('Sender')

    def message_preview(self, obj):
        return obj.message[:80] + '...' if len(obj.message) > 80 else obj.message

    message_preview.short_description = _('Message')

    def staff_badge(self, obj):
        if obj.is_staff:
            return format_html('<span class="badge bg-success">{}</span>', _('Staff'))
        return format_html('<span class="badge bg-secondary">{}</span>', _('Customer'))

    staff_badge.short_description = _('Sender Type')

    def internal_badge(self, obj):
        if obj.is_internal_note:
            return format_html('<span class="badge bg-warning">{}</span>', _('Internal'))
        return format_html('<span class="badge bg-info">{}</span>', _('External'))

    internal_badge.short_description = _('Visibility')


class FAQAdmin(PublicModelAdmin):
    """Admin interface for FAQ"""

    list_display = [
        'question_preview', 'category_badge', 'order',
        'featured_badge', 'status_badge', 'view_count', 'created_at'
    ]

    list_filter = [
        'category', 'is_featured', 'is_active', 'created_at'
    ]

    search_fields = [
        'question', 'answer', 'meta_description'
    ]

    readonly_fields = [
        'view_count', 'helpful_count', 'not_helpful_count',
        'created_at', 'updated_at'
    ]

    ordering = ['order', '-is_featured', 'question']

    fieldsets = (
        (_('FAQ Content'), {
            'fields': (
                'category', 'question', 'answer'
            )
        }),
        (_('SEO & Display'), {
            'fields': (
                'slug', 'meta_description', 'order', 'is_featured', 'is_active'
            )
        }),
        (_('Statistics'), {
            'fields': (
                'view_count', 'helpful_count', 'not_helpful_count'
            ),
            'classes': ('collapse',)
        }),
        (_('Metadata'), {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    actions = [
        'mark_as_featured', 'unmark_as_featured',
        'activate_faqs', 'deactivate_faqs'
    ]

    def question_preview(self, obj):
        return obj.question[:70] + '...' if len(obj.question) > 70 else obj.question

    question_preview.short_description = _('Question')

    def category_badge(self, obj):
        colors = {
            'GENERAL': 'primary',
            'PRICING': 'warning',
            'FEATURES': 'info',
            'TECHNICAL': 'danger',
            'BILLING': 'success',
            'SECURITY': 'dark'
        }
        color = colors.get(obj.category, 'secondary')
        return format_html(
            '<span class="badge bg-{}">{}</span>',
            color,
            obj.get_category_display()
        )

    category_badge.short_description = _('Category')
    category_badge.admin_order_field = 'category'

    def featured_badge(self, obj):
        if obj.is_featured:
            return format_html('<span class="badge bg-warning">{}</span>', _('Featured'))
        return '-'

    featured_badge.short_description = _('Featured')

    def status_badge(self, obj):
        if obj.is_active:
            return format_html('<span class="badge bg-success">{}</span>', _('Active'))
        return format_html('<span class="badge bg-secondary">{}</span>', _('Inactive'))

    status_badge.short_description = _('Status')
    status_badge.admin_order_field = 'is_active'

    def mark_as_featured(self, request, queryset):
        updated = queryset.update(is_featured=True)
        self.message_user(
            request,
            _('{} FAQ(s) marked as featured.').format(updated),
            messages.SUCCESS
        )

    mark_as_featured.short_description = _("Mark selected as featured")

    def unmark_as_featured(self, request, queryset):
        updated = queryset.update(is_featured=False)
        self.message_user(
            request,
            _('{} FAQ(s) unmarked as featured.').format(updated),
            messages.INFO
        )

    unmark_as_featured.short_description = _("Unmark selected as featured")

    def activate_faqs(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(
            request,
            _('{} FAQ(s) activated.').format(updated),
            messages.SUCCESS
        )

    activate_faqs.short_description = _("Activate selected FAQs")

    def deactivate_faqs(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(
            request,
            _('{} FAQ(s) deactivated.').format(updated),
            messages.WARNING
        )

    deactivate_faqs.short_description = _("Deactivate selected FAQs")


class ContactRequestAdmin(PublicModelAdmin):
    """Admin interface for ContactRequest"""

    list_display = [
        'name', 'email', 'request_type_badge', 'company_preview',
        'processed_badge', 'created_at', 'actions_column'
    ]

    list_filter = [
        'request_type', 'is_processed', 'company_size', 'created_at'
    ]

    search_fields = [
        'name', 'email', 'company', 'job_title', 'message'
    ]

    readonly_fields = [
        'created_at', 'processed_at', 'ip_address'
    ]

    ordering = ['-created_at']

    fieldsets = (
        (_('Contact Information'), {
            'fields': (
                'name', 'email', 'phone', 'company', 'job_title'
            )
        }),
        (_('Request Details'), {
            'fields': (
                'request_type', 'message'
            )
        }),
        (_('Additional Information'), {
            'fields': (
                'company_size',
            )
        }),
        (_('Processing'), {
            'fields': (
                'is_processed', 'processed_at', 'notes'
            )
        }),
        (_('Technical Information'), {
            'fields': (
                'ip_address',
            ),
            'classes': ('collapse',)
        }),
        (_('Metadata'), {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )

    actions = ['mark_as_processed', 'mark_as_unprocessed']

    def company_preview(self, obj):
        if obj.company:
            return obj.company[:40] + '...' if len(obj.company) > 40 else obj.company
        return '-'

    company_preview.short_description = _('Company')

    def request_type_badge(self, obj):
        colors = {
            'GENERAL': 'primary',
            'DEMO': 'info',
            'SALES': 'success',
            'PARTNERSHIP': 'warning',
            'PRESS': 'dark'
        }
        color = colors.get(obj.request_type, 'secondary')
        return format_html(
            '<span class="badge bg-{}">{}</span>',
            color,
            obj.get_request_type_display()
        )

    request_type_badge.short_description = _('Request Type')
    request_type_badge.admin_order_field = 'request_type'

    def processed_badge(self, obj):
        if obj.is_processed:
            return format_html('<span class="badge bg-success">{}</span>', _('Processed'))
        return format_html('<span class="badge bg-warning">{}</span>', _('New'))

    processed_badge.short_description = _('Status')
    processed_badge.admin_order_field = 'is_processed'

    def actions_column(self, obj):
        if not obj.is_processed:
            return format_html(
                '<button class="button" onclick="alert(\'Process request: {}\')">{}</button>',
                obj.email,
                _('Process')
            )
        return '-'

    actions_column.short_description = _('Actions')

    def mark_as_processed(self, request, queryset):
        for contact in queryset:
            contact.mark_processed()
        self.message_user(
            request,
            _('{} contact request(s) marked as processed.').format(queryset.count()),
            messages.SUCCESS
        )

    mark_as_processed.short_description = _("Mark selected as processed")

    def mark_as_unprocessed(self, request, queryset):
        updated = queryset.update(is_processed=False, processed_at=None)
        self.message_user(
            request,
            _('{} contact request(s) marked as unprocessed.').format(updated),
            messages.WARNING
        )

    mark_as_unprocessed.short_description = _("Mark selected as unprocessed")


# Register models with public admin
public_admin.register(SupportTicket, SupportTicketAdmin, app_label='public_support')
public_admin.register(TicketReply, TicketReplyAdmin, app_label='public_support')
public_admin.register(FAQ, FAQAdmin, app_label='public_support')
public_admin.register(ContactRequest, ContactRequestAdmin, app_label='public_support')