from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.db.models import Sum, Count
from django.urls import reverse
from django.utils import timezone
from .models import (
    ExpenseCategory, Vendor, Budget, Expense, ExpenseSplit,
    ExpenseAttachment, RecurringExpense, PettyCash, PettyCashTransaction,
    ExpenseApprovalFlow, ExpenseApproval, EmployeeReimbursement,
    ReimbursementItem, ExpenseAuditLog
)


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = [
        'code', 'name', 'parent', 'category_type',
        'is_taxable', 'requires_approval', 'is_active',
        'total_expenses_display'
    ]
    list_filter = ['category_type', 'is_active', 'is_taxable', 'requires_approval']
    search_fields = ['name', 'code', 'description']
    ordering = ['sort_order', 'name']
    fieldsets = (
        (_('Basic Information'), {
            'fields': ('name', 'code', 'parent', 'category_type', 'description')
        }),
        (_('Settings'), {
            'fields': (
                'is_active', 'requires_approval', 'approval_limit',
                'is_taxable', 'default_tax_rate', 'budget_allocation'
            )
        }),
        (_('Display'), {
            'fields': ('color_code', 'icon', 'sort_order')
        }),
    )

    def total_expenses_display(self, obj):
        total = obj.total_expenses()
        return format_html(
            '<span style="color: {};">{:,.2f}</span>',
            '#28a745' if total > 0 else '#6c757d',
            total
        )

    total_expenses_display.short_description = _('Total Expenses')


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'vendor_type', 'contact_person', 'phone',
        'email', 'payment_terms', 'is_registered_for_vat',
        'rating_display', 'total_spent_display', 'is_active'
    ]
    list_filter = [
        'vendor_type', 'is_active', 'is_approved',
        'is_registered_for_vat', 'payment_terms'
    ]
    search_fields = ['name', 'contact_person', 'email', 'phone', 'tin']
    readonly_fields = ['vendor_id', 'created_at', 'updated_at', 'total_spent', 'outstanding_balance']

    fieldsets = (
        (_('Basic Information'), {
            'fields': (
                'vendor_id', 'name', 'vendor_type', 'contact_person',
                'email', 'phone', 'address'
            )
        }),
        (_('Tax Information'), {
            'fields': ('tin', 'is_registered_for_vat')
        }),
        (_('Payment Terms'), {
            'fields': (
                'payment_terms', 'custom_payment_days', 'credit_limit'
            )
        }),
        (_('Banking Details'), {
            'fields': (
                'bank_name', 'account_number', 'account_name',
                'mobile_money_number'
            ),
            'classes': ('collapse',)
        }),
        (_('Status & Performance'), {
            'fields': (
                'is_active', 'is_approved', 'rating',
                'total_spent', 'outstanding_balance'
            )
        }),
        (_('Notes'), {
            'fields': ('notes',)
        }),
        (_('Metadata'), {
            'fields': ('created_at', 'updated_at', 'created_by'),
            'classes': ('collapse',)
        }),
    )

    def rating_display(self, obj):
        if obj.rating:
            stars = '⭐' * int(obj.rating)
            return format_html('<span title="{}">{}</span>', obj.rating, stars)
        return '-'

    rating_display.short_description = _('Rating')

    def total_spent_display(self, obj):
        total = obj.total_spent
        if isinstance(total, (int, float)):
            return format_html("{:,.2f} UGX", total)
        return total  # already formatted string

    total_spent_display.short_description = _('Total Spent')


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'category', 'store', 'budget_period',
        'start_date', 'end_date', 'allocated_amount',
        'spent_amount_display', 'utilization_display',
        'status_badge', 'is_active'
    ]
    list_filter = [
        'budget_period', 'is_active', 'category',
        'store', 'start_date'
    ]
    search_fields = ['name', 'category__name', 'store__name']
    readonly_fields = [
        'spent_amount', 'remaining_amount',
        'utilization_percentage', 'status'
    ]
    date_hierarchy = 'start_date'

    fieldsets = (
        (_('Budget Information'), {
            'fields': (
                'name', 'category', 'store', 'budget_period',
                'start_date', 'end_date', 'allocated_amount'
            )
        }),
        (_('Alert Thresholds'), {
            'fields': ('warning_threshold', 'critical_threshold')
        }),
        (_('Current Status'), {
            'fields': (
                'spent_amount', 'remaining_amount',
                'utilization_percentage', 'status'
            ),
            'classes': ('wide',)
        }),
        (_('Additional'), {
            'fields': ('is_active', 'notes')
        }),
    )

    def spent_amount_display(self, obj):
        return format_html('{:,.2f}', obj.spent_amount)

    spent_amount_display.short_description = _('Spent')

    def utilization_display(self, obj):
        percentage = obj.utilization_percentage
        return format_html('{}%', percentage)

    utilization_display.short_description = _('Utilization')

    def status_badge(self, obj):
        status = obj.status
        colors = {
            'NORMAL': '#28a745',
            'WARNING': '#ffc107',
            'CRITICAL': '#dc3545',
            'EXCEEDED': '#6c757d'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(status, '#6c757d'),
            status
        )

    status_badge.short_description = _('Status')


class ExpenseSplitInline(admin.TabularInline):
    model = ExpenseSplit
    extra = 1
    readonly_fields = ['allocated_amount']
    fields = ['store', 'allocation_percentage', 'allocated_amount', 'notes']


class ExpenseAttachmentInline(admin.TabularInline):
    model = ExpenseAttachment
    extra = 1
    readonly_fields = ['file_name', 'file_size', 'uploaded_by', 'uploaded_at']
    fields = ['attachment_type', 'file', 'description']


class ExpenseApprovalInline(admin.TabularInline):
    model = ExpenseApproval
    extra = 0
    readonly_fields = ['approval_level', 'approver', 'status', 'approved_at']
    can_delete = False
    max_num = 0


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = [
        'expense_number', 'store', 'category', 'vendor',
        'expense_date', 'total_amount_display', 'status_badge',
        'payment_method', 'is_overdue_display', 'created_by'
    ]
    list_filter = [
        'status', 'expense_type', 'payment_method',
        'category', 'store', 'is_recurring',
        'requires_approval', 'is_split', 'expense_date'
    ]
    search_fields = [
        'expense_number', 'description', 'invoice_number',
        'vendor__name', 'payment_reference'
    ]
    readonly_fields = [
        'expense_id', 'expense_number', 'total_amount',
        'amount_due', 'is_overdue', 'days_overdue',
        'approved_by', 'approved_at', 'paid_by',
        'created_at', 'updated_at'
    ]
    date_hierarchy = 'expense_date'
    inlines = [ExpenseSplitInline, ExpenseAttachmentInline, ExpenseApprovalInline]

    fieldsets = (
        (_('Basic Information'), {
            'fields': (
                'expense_id', 'expense_number', 'store', 'category',
                'expense_type', 'vendor', 'description'
            )
        }),
        (_('Financial Details'), {
            'fields': (
                'expense_date', 'amount', 'tax_rate', 'tax_amount',
                'total_amount', 'currency'
            )
        }),
        (_('Payment Information'), {
            'fields': (
                'status', 'payment_method', 'payment_date',
                'payment_reference', 'amount_paid', 'amount_due'
            )
        }),
        (_('Due Date & Recurring'), {
            'fields': (
                'due_date', 'is_overdue', 'days_overdue',
                'is_recurring', 'recurring_schedule'
            )
        }),
        (_('Approval'), {
            'fields': (
                'requires_approval', 'approved_by', 'approved_at',
                'rejection_reason'
            )
        }),
        (_('References'), {
            'fields': (
                'invoice_number', 'purchase_order', 'is_split'
            ),
            'classes': ('collapse',)
        }),
        (_('EFRIS Compliance'), {
            'fields': (
                'is_efris_compliant', 'efris_invoice_number',
                'efris_verification_code', 'can_claim_input_tax'
            ),
            'classes': ('collapse',)
        }),
        (_('Additional Information'), {
            'fields': ('notes',)
        }),
        (_('Tracking'), {
            'fields': (
                'created_by', 'created_at', 'updated_at', 'paid_by'
            ),
            'classes': ('collapse',)
        }),
    )

    actions = ['approve_expenses', 'reject_expenses', 'mark_as_paid']

    def total_amount_display(self, obj):
        return format_html('{:,.2f} {}', obj.total_amount, obj.currency)

    total_amount_display.short_description = _('Total Amount')

    def status_badge(self, obj):
        colors = {
            'DRAFT': '#6c757d',
            'PENDING': '#ffc107',
            'APPROVED': '#17a2b8',
            'REJECTED': '#dc3545',
            'PAID': '#28a745',
            'PARTIALLY_PAID': '#fd7e14',
            'CANCELLED': '#6c757d'
        }
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px;">{}</span>',
            colors.get(obj.status, '#6c757d'),
            obj.get_status_display()
        )

    status_badge.short_description = _('Status')

    def is_overdue_display(self, obj):
        if obj.is_overdue:
            return format_html(
                '<span style="color: #dc3545; font-weight: bold;">⚠ {} days</span>',
                obj.days_overdue
            )
        return format_html('<span style="color: #28a745;">✓</span>')

    is_overdue_display.short_description = _('Overdue')

    def approve_expenses(self, request, queryset):
        count = 0
        for expense in queryset.filter(status='PENDING'):
            try:
                expense.approve(request.user)
                count += 1
            except Exception as e:
                self.message_user(
                    request,
                    f'Error approving {expense.expense_number}: {str(e)}',
                    level='error'
                )

        self.message_user(request, f'{count} expense(s) approved successfully.')

    approve_expenses.short_description = _('Approve selected expenses')

    def reject_expenses(self, request, queryset):
        count = 0
        for expense in queryset.filter(status='PENDING'):
            try:
                expense.reject(request.user, 'Bulk rejection from admin')
                count += 1
            except Exception as e:
                self.message_user(
                    request,
                    f'Error rejecting {expense.expense_number}: {str(e)}',
                    level='error'
                )

        self.message_user(request, f'{count} expense(s) rejected.')

    reject_expenses.short_description = _('Reject selected expenses')

    def mark_as_paid(self, request, queryset):
        count = 0
        for expense in queryset.filter(status__in=['APPROVED', 'PARTIALLY_PAID']):
            try:
                expense.mark_as_paid(
                    paid_by=request.user,
                    payment_method='BANK_TRANSFER',
                    payment_reference='Bulk payment from admin'
                )
                count += 1
            except Exception as e:
                self.message_user(
                    request,
                    f'Error marking {expense.expense_number} as paid: {str(e)}',
                    level='error'
                )

        self.message_user(request, f'{count} expense(s) marked as paid.')

    mark_as_paid.short_description = _('Mark selected expenses as paid')


@admin.register(RecurringExpense)
class RecurringExpenseAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'frequency', 'store', 'category',
        'amount', 'next_occurrence', 'is_active',
        'auto_approve', 'auto_pay'
    ]
    list_filter = [
        'frequency', 'is_active', 'auto_approve',
        'auto_pay', 'store', 'category'
    ]
    search_fields = ['name', 'description']
    readonly_fields = ['created_at', 'updated_at']
    date_hierarchy = 'next_occurrence'

    fieldsets = (
        (_('Basic Information'), {
            'fields': (
                'name', 'description', 'store', 'category',
                'expense_type', 'vendor'
            )
        }),
        (_('Recurring Details'), {
            'fields': (
                'frequency', 'amount', 'tax_rate',
                'start_date', 'end_date', 'next_occurrence'
            )
        }),
        (_('Auto-processing'), {
            'fields': (
                'auto_approve', 'auto_pay', 'payment_method'
            )
        }),
        (_('Status'), {
            'fields': ('is_active',)
        }),
    )

    actions = ['generate_expenses_now']

    def generate_expenses_now(self, request, queryset):
        count = 0
        for recurring in queryset.filter(is_active=True):
            try:
                expense = recurring.generate_expense()
                if expense:
                    count += 1
            except Exception as e:
                self.message_user(
                    request,
                    f'Error generating expense for {recurring.name}: {str(e)}',
                    level='error'
                )

        self.message_user(request, f'{count} expense(s) generated successfully.')

    generate_expenses_now.short_description = _('Generate expenses now')


class PettyCashTransactionInline(admin.TabularInline):
    model = PettyCashTransaction
    extra = 0
    readonly_fields = [
        'reference_number', 'transaction_type', 'amount',
        'balance_after', 'processed_by', 'created_at'
    ]
    can_delete = False
    max_num = 0
    fields = ['reference_number', 'transaction_type', 'amount', 'balance_after', 'created_at']


@admin.register(PettyCash)
class PettyCashAdmin(admin.ModelAdmin):
    list_display = [
        'store', 'custodian', 'current_balance_display',
        'maximum_limit', 'needs_replenishment_display',
        'last_reconciled', 'is_active'
    ]
    list_filter = ['is_active', 'store']
    search_fields = ['store__name', 'custodian__username']
    readonly_fields = [
        'current_balance', 'total_disbursed', 'total_replenished',
        'needs_replenishment', 'created_at', 'updated_at'
    ]
    inlines = [PettyCashTransactionInline]

    fieldsets = (
        (_('Store & Custodian'), {
            'fields': ('store', 'custodian', 'is_active')
        }),
        (_('Balance Information'), {
            'fields': (
                'opening_balance', 'current_balance',
                'maximum_limit', 'minimum_balance'
            )
        }),
        (_('Statistics'), {
            'fields': (
                'total_disbursed', 'total_replenished',
                'needs_replenishment'
            ),
            'classes': ('wide',)
        }),
        (_('Reconciliation'), {
            'fields': ('last_reconciled',)
        }),
    )

    def current_balance_display(self, obj):
        color = '#dc3545' if obj.needs_replenishment else '#28a745'
        return format_html(
            '<span style="color: {}; font-weight: bold;">{:,.2f}</span>',
            color,
            obj.current_balance
        )

    current_balance_display.short_description = _('Current Balance')

    def needs_replenishment_display(self, obj):
        if obj.needs_replenishment:
            return format_html(
                '<span style="color: #dc3545; font-weight: bold;">⚠ YES</span>'
            )
        return format_html('<span style="color: #28a745;">✓ NO</span>')

    needs_replenishment_display.short_description = _('Needs Replenishment')


@admin.register(PettyCashTransaction)
class PettyCashTransactionAdmin(admin.ModelAdmin):
    list_display = [
        'reference_number', 'petty_cash', 'transaction_type',
        'amount', 'balance_after', 'processed_by', 'created_at'
    ]
    list_filter = ['transaction_type', 'petty_cash__store', 'created_at']
    search_fields = ['reference_number', 'notes', 'expense__expense_number']
    readonly_fields = [
        'reference_number', 'balance_after', 'created_at'
    ]
    date_hierarchy = 'created_at'

    fieldsets = (
        (_('Transaction Details'), {
            'fields': (
                'reference_number', 'petty_cash', 'transaction_type',
                'amount', 'balance_after'
            )
        }),
        (_('Related Information'), {
            'fields': ('expense', 'processed_by', 'notes')
        }),
        (_('Timestamp'), {
            'fields': ('created_at',)
        }),
    )


class ReimbursementItemInline(admin.TabularInline):
    model = ReimbursementItem
    extra = 1
    fields = ['category', 'description', 'expense_date', 'amount', 'receipt_number']


@admin.register(EmployeeReimbursement)
class EmployeeReimbursementAdmin(admin.ModelAdmin):
    list_display = [
        'reimbursement_number', 'employee', 'store',
        'claim_date', 'total_amount', 'status_badge',
        'approved_by', 'paid_date'
    ]
    list_filter = ['status', 'store', 'claim_date', 'paid_date']
    search_fields = [
        'reimbursement_number', 'employee__username',
        'employee__first_name', 'employee__last_name', 'description'
    ]
    readonly_fields = [
        'reimbursement_number', 'created_at', 'updated_at'
    ]
    date_hierarchy = 'claim_date'
    inlines = [ReimbursementItemInline]

    fieldsets = (
        (_('Reimbursement Information'), {
            'fields': (
                'reimbursement_number', 'employee', 'store',
                'claim_date', 'description', 'total_amount'
            )
        }),
        (_('Status'), {
            'fields': ('status',)
        }),
        (_('Approval'), {
            'fields': ('approved_by', 'approved_at')
        }),
        (_('Payment'), {
            'fields': (
                'paid_date', 'payment_method', 'payment_reference'
            )
        }),
        (_('Notes'), {
            'fields': ('notes',)
        }),
    )

    def status_badge(self, obj):
        colors = {
            'DRAFT': '#6c757d',
            'SUBMITTED': '#ffc107',
            'APPROVED': '#17a2b8',
            'REJECTED': '#dc3545',
            'PAID': '#28a745'
        }
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px;">{}</span>',
            colors.get(obj.status, '#6c757d'),
            obj.get_status_display()
        )

    status_badge.short_description = _('Status')


@admin.register(ExpenseApprovalFlow)
class ExpenseApprovalFlowAdmin(admin.ModelAdmin):
    list_display = [
        'category', 'store', 'approval_level',
        'approver_role', 'minimum_amount', 'maximum_amount',
        'is_active'
    ]
    list_filter = ['is_active', 'approval_level', 'category']
    search_fields = ['category__name', 'store__name', 'approver_role__name']

    fieldsets = (
        (_('Flow Configuration'), {
            'fields': (
                'category', 'store', 'approval_level', 'approver_role'
            )
        }),
        (_('Amount Thresholds'), {
            'fields': ('minimum_amount', 'maximum_amount')
        }),
        (_('Status'), {
            'fields': ('is_active',)
        }),
    )


@admin.register(ExpenseAuditLog)
class ExpenseAuditLogAdmin(admin.ModelAdmin):
    list_display = [
        'expense', 'action', 'user', 'timestamp',
        'ip_address', 'session'
    ]
    list_filter = ['action', 'timestamp']
    search_fields = ['expense__expense_number', 'user__username', 'notes']
    readonly_fields = [
        'expense', 'action', 'user', 'timestamp',
        'ip_address', 'session', 'old_values', 'new_values'
    ]
    date_hierarchy = 'timestamp'

    fieldsets = (
        (_('Log Information'), {
            'fields': (
                'expense', 'action', 'user', 'timestamp'
            )
        }),
        (_('Session Details'), {
            'fields': ('ip_address', 'session')
        }),
        (_('Changes'), {
            'fields': ('old_values', 'new_values', 'notes'),
            'classes': ('wide',)
        }),
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False