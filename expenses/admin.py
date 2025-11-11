from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from .models import Expense, ExpenseCategory, ExpenseAttachment, ExpenseComment


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'colored_badge', 'monthly_budget', 'budget_status', 'is_active', 'sort_order']
    list_filter = ['is_active', 'requires_approval']
    search_fields = ['name', 'code', 'description']
    ordering = ['sort_order', 'name']
    list_editable = ['sort_order', 'is_active']

    fieldsets = (
        (_('Basic Information'), {
            'fields': ('name', 'code', 'description', 'is_active')
        }),
        (_('Budget & Approval'), {
            'fields': ('monthly_budget', 'requires_approval', 'approval_threshold')
        }),
        (_('Display Settings'), {
            'fields': ('color_code', 'icon', 'sort_order')
        }),
        (_('Accounting'), {
            'fields': ('gl_account',),
            'classes': ('collapse',)
        })
    )

    def colored_badge(self, obj):
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 3px;">{}</span>',
            obj.color_code,
            obj.name
        )

    colored_badge.short_description = _('Category')

    def budget_status(self, obj):
        if not obj.monthly_budget:
            return '-'
        utilization = obj.get_budget_utilization()
        if utilization:
            color = 'red' if utilization >= 100 else 'orange' if utilization >= 80 else 'green'
            return format_html(
                '<span style="color: {};">{:.1f}%</span>',
                color,
                utilization
            )
        return '0%'

    budget_status.short_description = _('Budget Utilization')


class ExpenseAttachmentInline(admin.TabularInline):
    model = ExpenseAttachment
    extra = 0
    readonly_fields = ['filename', 'file_size', 'uploaded_by', 'uploaded_at']
    fields = ['file', 'filename', 'file_size', 'description', 'uploaded_by', 'uploaded_at']


class ExpenseCommentInline(admin.TabularInline):
    model = ExpenseComment
    extra = 0
    readonly_fields = ['user', 'created_at', 'updated_at']
    fields = ['user', 'comment', 'is_internal', 'created_at']


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = [
        'expense_number', 'title', 'category', 'created_by',
        'amount_display', 'status_badge', 'expense_date', 'days_pending_display'
    ]
    list_filter = [
        'status', 'category', 'is_reimbursable', 'is_recurring',
        'is_billable', 'expense_date', 'created_at'
    ]
    search_fields = [
        'expense_number', 'title', 'description',
        'vendor_name', 'reference_number', 'created_by__username'
    ]
    date_hierarchy = 'expense_date'
    readonly_fields = [
        'expense_number', 'total_amount', 'created_at', 'updated_at',
        'submitted_at', 'approved_at', 'approved_by', 'rejected_at',
        'paid_at', 'paid_by'
    ]
    inlines = [ExpenseAttachmentInline, ExpenseCommentInline]

    fieldsets = (
        (_('Identification'), {
            'fields': ('expense_number', 'reference_number', 'status')
        }),
        (_('Basic Information'), {
            'fields': ('title', 'description', 'category', 'expense_date', 'due_date')
        }),
        (_('Amount'), {
            'fields': ('amount', 'currency', 'tax_rate', 'tax_amount', 'total_amount')
        }),
        (_('Vendor Information'), {
            'fields': ('vendor_name', 'vendor_phone', 'vendor_email', 'vendor_tin'),
            'classes': ('collapse',)
        }),
        (_('User & Location'), {
            'fields': ('created_by', 'store')
        }),
        (_('Approval Information'), {
            'fields': ('submitted_at', 'approved_by', 'approved_at', 'rejection_reason', 'rejected_at')
        }),
        (_('Payment Information'), {
            'fields': ('payment_method', 'paid_by', 'paid_at', 'payment_reference')
        }),
        (_('Flags'), {
            'fields': ('is_reimbursable', 'is_recurring', 'is_billable')
        }),
        (_('Notes'), {
            'fields': ('notes', 'admin_notes')
        }),
        (_('Timestamps'), {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )

    actions = ['approve_expenses', 'mark_as_paid', 'export_to_excel']

    def amount_display(self, obj):
        return f'{obj.amount:,.0f} {obj.currency}'

    amount_display.short_description = _('Amount')
    amount_display.admin_order_field = 'amount'

    def status_badge(self, obj):
        colors = {
            'DRAFT': 'gray',
            'SUBMITTED': 'orange',
            'APPROVED': 'blue',
            'REJECTED': 'red',
            'PAID': 'green',
            'CANCELLED': 'darkgray'
        }
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 3px;">{}</span>',
            colors.get(obj.status, 'gray'),
            obj.get_status_display()
        )

    status_badge.short_description = _('Status')

    def days_pending_display(self, obj):
        if obj.status == 'SUBMITTED':
            days = obj.days_pending
            color = 'red' if days > 5 else 'orange' if days > 3 else 'green'
            return format_html(
                '<span style="color: {};">{} days</span>',
                color,
                days
            )
        return '-'

    days_pending_display.short_description = _('Days Pending')

    def approve_expenses(self, request, queryset):
        count = 0
        for expense in queryset.filter(status='SUBMITTED'):
            try:
                expense.approve(request.user)
                count += 1
            except ValueError:
                pass
        self.message_user(request, f'{count} expenses approved successfully.')

    approve_expenses.short_description = _('Approve selected expenses')

    def mark_as_paid(self, request, queryset):
        count = 0
        for expense in queryset.filter(status='APPROVED'):
            try:
                expense.mark_as_paid(request.user, 'BANK_TRANSFER')
                count += 1
            except ValueError:
                pass
        self.message_user(request, f'{count} expenses marked as paid.')

    mark_as_paid.short_description = _('Mark selected as paid')

    def export_to_excel(self, request, queryset):
        from .utils import export_expenses_to_excel
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp:
            export_expenses_to_excel(queryset, tmp.name)
            # You'd typically return a file response here
            self.message_user(request, f'{queryset.count()} expenses exported.')

    export_to_excel.short_description = _('Export to Excel')


@admin.register(ExpenseAttachment)
class ExpenseAttachmentAdmin(admin.ModelAdmin):
    list_display = ['filename', 'expense', 'file_type', 'file_size_display', 'uploaded_by', 'uploaded_at']
    list_filter = ['file_type', 'uploaded_at']
    search_fields = ['filename', 'expense__expense_number', 'description']
    readonly_fields = ['filename', 'file_size', 'uploaded_by', 'uploaded_at']

    def file_size_display(self, obj):
        size = obj.file_size
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"

    file_size_display.short_description = _('File Size')


@admin.register(ExpenseComment)
class ExpenseCommentAdmin(admin.ModelAdmin):
    list_display = ['expense', 'user', 'comment_preview', 'is_internal', 'created_at']
    list_filter = ['is_internal', 'created_at']
    search_fields = ['comment', 'expense__expense_number', 'user__username']
    readonly_fields = ['created_at', 'updated_at']

    def comment_preview(self, obj):
        return obj.comment[:50] + '...' if len(obj.comment) > 50 else obj.comment

    comment_preview.short_description = _('Comment')