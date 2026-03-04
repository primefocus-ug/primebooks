from django.contrib import admin
from django.utils.html import format_html
from .models import Expense, Budget, ExpenseApproval


# ---------------------------------------------------------------------------
# Inline: approval history inside Expense admin
# ---------------------------------------------------------------------------

class ExpenseApprovalInline(admin.TabularInline):
    model = ExpenseApproval
    extra = 0
    readonly_fields = ['actor', 'action', 'previous_status', 'new_status', 'comment', 'created_at']
    fields = ['created_at', 'actor', 'action', 'previous_status', 'new_status', 'comment']
    can_delete = False
    ordering = ['created_at']
    verbose_name = 'Approval Event'
    verbose_name_plural = 'Approval History'


# ---------------------------------------------------------------------------
# Expense admin
# ---------------------------------------------------------------------------

@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = [
        'description', 'vendor', 'amount_display', 'currency',
        'amount_base', 'user', 'date', 'payment_method',
        'status_badge', 'is_recurring', 'ocr_processed', 'created_at',
    ]
    list_filter = [
        'status', 'currency', 'date', 'payment_method',
        'is_recurring', 'is_important', 'ocr_processed', 'tags',
    ]
    search_fields = ['description', 'vendor', 'notes', 'user__username', 'user__email']
    date_hierarchy = 'date'
    readonly_fields = [
        'id', 'sync_id', 'amount_base', 'ocr_raw', 'ocr_vendor', 'ocr_amount',
        'ocr_processed', 'created_at', 'updated_at',
    ]
    inlines = [ExpenseApprovalInline]

    fieldsets = (
        ('Basic Information', {
            'fields': ('id', 'sync_id', 'user', 'description', 'vendor', 'date', 'status')
        }),
        ('Financial', {
            'fields': ('amount', 'currency', 'exchange_rate', 'amount_base', 'payment_method')
        }),
        ('Organisation', {
            'fields': ('tags',)
        }),
        ('Attachments', {
            'fields': ('receipt',)
        }),
        ('OCR Results', {
            'fields': ('ocr_processed', 'ocr_vendor', 'ocr_amount', 'ocr_raw'),
            'classes': ('collapse',),
        }),
        ('Recurring', {
            'fields': ('is_recurring', 'recurrence_interval', 'next_recurrence_date'),
            'classes': ('collapse',),
        }),
        ('Additional Details', {
            'fields': ('notes', 'is_important')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    # ------------------------------------------------------------------
    # Custom display helpers
    # ------------------------------------------------------------------

    @admin.display(description='Amount', ordering='amount')
    def amount_display(self, obj):
        return f'{obj.currency} {obj.amount:,.2f}'

    @admin.display(description='Status')
    def status_badge(self, obj):
        colour_map = {
            'draft': '#6c757d',
            'submitted': '#ffc107',
            'under_review': '#17a2b8',
            'approved': '#28a745',
            'rejected': '#dc3545',
            'resubmit': '#fd7e14',
        }
        colour = colour_map.get(obj.status, '#6c757d')
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:4px;">{}</span>',
            colour,
            obj.get_status_display(),
        )

    # ------------------------------------------------------------------
    # Quick-action: approve selected expenses
    # ------------------------------------------------------------------

    @admin.action(description='✅ Approve selected expenses')
    def approve_expenses(self, request, queryset):
        count = 0
        for expense in queryset.filter(status__in=('submitted', 'under_review')):
            ExpenseApproval.record(expense, request.user, 'approved', 'Bulk approved via admin')
            count += 1
        self.message_user(request, f'{count} expense(s) approved.')

    @admin.action(description='📤 Submit selected draft expenses')
    def submit_expenses(self, request, queryset):
        count = 0
        for expense in queryset.filter(status__in=('draft', 'resubmit')):
            ExpenseApproval.record(expense, request.user, 'submitted', 'Bulk submitted via admin')
            count += 1
        self.message_user(request, f'{count} expense(s) submitted.')

    actions = [approve_expenses, submit_expenses]


# ---------------------------------------------------------------------------
# ExpenseApproval standalone admin
# ---------------------------------------------------------------------------

@admin.register(ExpenseApproval)
class ExpenseApprovalAdmin(admin.ModelAdmin):
    list_display = ['expense', 'actor', 'action', 'previous_status', 'new_status', 'created_at']
    list_filter = ['action', 'new_status', 'created_at']
    search_fields = ['expense__description', 'actor__username', 'comment']
    readonly_fields = ['expense', 'actor', 'action', 'previous_status', 'new_status', 'comment', 'created_at']
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        # Approval records should only be created via ExpenseApproval.record()
        return False

    def has_change_permission(self, request, obj=None):
        return False


# ---------------------------------------------------------------------------
# Budget admin
# ---------------------------------------------------------------------------

@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'user', 'amount', 'currency', 'period',
        'alert_threshold', 'spending_display', 'status_badge', 'is_active', 'created_at',
    ]
    list_filter = ['period', 'currency', 'is_active', 'tags']
    search_fields = ['name', 'user__username']
    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        ('Basic Information', {
            'fields': ('user', 'name', 'amount', 'period', 'currency')
        }),
        ('Filters', {
            'fields': ('tags',)
        }),
        ('Alert Settings', {
            'fields': ('alert_threshold', 'is_active')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    @admin.display(description='Current Spending')
    def spending_display(self, obj):
        try:
            spent = obj.get_current_spending()
            pct = float(obj.get_percentage_used())
            return f'{spent:,.2f} ({pct:.0f}%)'
        except Exception:
            return '—'

    @admin.display(description='Status')
    def status_badge(self, obj):
        colour_map = {'success': '#28a745', 'warning': '#ffc107', 'danger': '#dc3545'}
        colour = colour_map.get(obj.get_status_color(), '#6c757d')
        label = obj.get_status_color().upper()
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:4px;">{}</span>',
            colour, label,
        )