from django.contrib import admin
from django.utils.html import format_html
from .models import (
    Currency, ExchangeRate, Dimension, DimensionValue,
    ChartOfAccounts, FiscalYear, FiscalPeriod, Journal,
    JournalEntry, JournalEntryLine, RecurringJournalEntry,
    BankAccount, Transaction, BankReconciliation,
    Budget, BudgetLine, TaxCode, AssetCategory, FixedAsset,
    DepreciationRecord, FinancialReport, AuditLog
)


@admin.register(Currency)
class CurrencyAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'symbol', 'is_base', 'is_active']
    list_filter = ['is_base', 'is_active']
    search_fields = ['code', 'name']
    ordering = ['code']


@admin.register(ExchangeRate)
class ExchangeRateAdmin(admin.ModelAdmin):
    list_display = ['from_currency', 'to_currency', 'rate', 'rate_date', 'rate_type', 'source']
    list_filter = ['rate_type', 'source', 'rate_date']
    search_fields = ['from_currency__code', 'to_currency__code']
    date_hierarchy = 'rate_date'
    ordering = ['-rate_date']


class DimensionValueInline(admin.TabularInline):
    model = DimensionValue
    extra = 1
    fields = ['code', 'name', 'parent', 'manager', 'is_active']


@admin.register(Dimension)
class DimensionAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'dimension_type', 'require_for_posting', 'is_active']
    list_filter = ['dimension_type', 'require_for_posting', 'is_active']
    search_fields = ['code', 'name']
    inlines = [DimensionValueInline]


@admin.register(ChartOfAccounts)
class ChartOfAccountsAdmin(admin.ModelAdmin):
    list_display = [
        'code', 'name', 'account_type', 'currency', 'current_balance',
        'is_active', 'is_header'
    ]
    list_filter = ['account_type', 'currency', 'is_active', 'is_header']
    search_fields = ['code', 'name', 'description']
    readonly_fields = ['current_balance', 'current_balance_base', 'level']
    fieldsets = (
        ('Basic Information', {
            'fields': ('code', 'name', 'description', 'account_type')
        }),
        ('Hierarchy', {
            'fields': ('parent', 'level', 'is_header')
        }),
        ('Currency', {
            'fields': ('currency', 'allow_multi_currency', 'revaluation_account')
        }),
        ('Balances', {
            'fields': ('current_balance', 'current_balance_base'),
            'classes': ('collapse',)
        }),
        ('Settings', {
            'fields': (
                'allow_direct_posting', 'is_reconcilable',
                'is_control_account', 'tax_code', 'require_dimensions'
            )
        }),
        ('Status', {
            'fields': ('is_active', 'is_system')
        }),
    )
    filter_horizontal = ['require_dimensions']


class FiscalPeriodInline(admin.TabularInline):
    model = FiscalPeriod
    extra = 0
    fields = ['period_number', 'name', 'start_date', 'end_date', 'status']
    readonly_fields = ['period_number']


@admin.register(FiscalYear)
class FiscalYearAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'start_date', 'end_date', 'status', 'is_current']
    list_filter = ['status', 'is_current']
    search_fields = ['name', 'code']
    inlines = [FiscalPeriodInline]
    actions = ['generate_periods']

    def generate_periods(self, request, queryset):
        for fiscal_year in queryset:
            try:
                fiscal_year.generate_periods()
                self.message_user(request, f'Periods generated for {fiscal_year.name}')
            except Exception as e:
                self.message_user(request, f'Error: {str(e)}', level='error')

    generate_periods.short_description = "Generate periods for selected fiscal years"


@admin.register(Journal)
class JournalAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'journal_type', 'require_approval', 'is_active']
    list_filter = ['journal_type', 'require_approval', 'is_active']
    search_fields = ['code', 'name']
    filter_horizontal = ['allowed_dimensions']


class JournalEntryLineInline(admin.TabularInline):
    model = JournalEntryLine
    extra = 0
    fields = [
        'line_number', 'account', 'description', 'debit_amount',
        'credit_amount', 'currency'
    ]
    readonly_fields = ['line_number']


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = [
        'entry_number', 'journal', 'entry_date', 'description',
        'total_debit', 'total_credit', 'status', 'is_balanced_display'
    ]
    list_filter = ['status', 'journal', 'fiscal_year', 'entry_date']
    search_fields = ['entry_number', 'description', 'reference']
    date_hierarchy = 'entry_date'
    readonly_fields = [
        'entry_number', 'total_debit', 'total_credit',
        'total_debit_base', 'total_credit_base', 'posted_by',
        'posted_at', 'approved_by', 'approved_at'
    ]
    inlines = [JournalEntryLineInline]
    actions = ['post_entries', 'approve_entries']

    def is_balanced_display(self, obj):
        if obj.is_balanced():
            return format_html('<span style="color: green;">✓ Balanced</span>')
        return format_html('<span style="color: red;">✗ Not Balanced</span>')

    is_balanced_display.short_description = 'Balance Status'

    def post_entries(self, request, queryset):
        for entry in queryset:
            if entry.status in ['DRAFT', 'APPROVED']:
                try:
                    entry.post(request.user)
                    self.message_user(request, f'Entry {entry.entry_number} posted')
                except Exception as e:
                    self.message_user(request, f'Error posting {entry.entry_number}: {str(e)}', level='error')

    post_entries.short_description = "Post selected entries"

    def approve_entries(self, request, queryset):
        for entry in queryset:
            if entry.status == 'PENDING':
                try:
                    entry.approve(request.user)
                    self.message_user(request, f'Entry {entry.entry_number} approved')
                except Exception as e:
                    self.message_user(request, f'Error: {str(e)}', level='error')

    approve_entries.short_description = "Approve selected entries"


@admin.register(RecurringJournalEntry)
class RecurringJournalEntryAdmin(admin.ModelAdmin):
    list_display = [
        'code', 'name', 'frequency', 'next_run_date',
        'last_run_date', 'auto_post', 'is_active'
    ]
    list_filter = ['frequency', 'auto_post', 'is_active']
    search_fields = ['code', 'name']
    date_hierarchy = 'next_run_date'


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = [
        'account_number', 'account_name', 'bank_name',
        'currency', 'current_balance', 'is_default', 'is_active'
    ]
    list_filter = ['currency', 'is_default', 'is_active']
    search_fields = ['account_number', 'account_name', 'bank_name']
    readonly_fields = ['current_balance', 'available_balance']


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = [
        'transaction_id', 'bank_account', 'transaction_date',
        'transaction_type', 'amount', 'status'
    ]
    list_filter = ['transaction_type', 'status', 'transaction_date']
    search_fields = ['transaction_id', 'description', 'payee']
    date_hierarchy = 'transaction_date'


@admin.register(BankReconciliation)
class BankReconciliationAdmin(admin.ModelAdmin):
    list_display = [
        'reconciliation_number', 'bank_account', 'reconciliation_date',
        'difference', 'is_balanced', 'status'
    ]
    list_filter = ['status', 'is_balanced', 'reconciliation_date']
    search_fields = ['reconciliation_number']
    date_hierarchy = 'reconciliation_date'


class BudgetLineInline(admin.TabularInline):
    model = BudgetLine
    extra = 1
    fields = ['account', 'amount', 'currency', 'description']


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = [
        'code', 'name', 'fiscal_year', 'budget_type',
        'total_budget', 'total_actual', 'status'
    ]
    list_filter = ['status', 'budget_type', 'fiscal_year']
    search_fields = ['code', 'name']
    readonly_fields = ['total_budget', 'total_actual', 'total_variance']
    inlines = [BudgetLineInline]
    actions = ['approve_budgets', 'activate_budgets']

    def approve_budgets(self, request, queryset):
        for budget in queryset:
            if budget.status == 'SUBMITTED':
                try:
                    budget.approve(request.user)
                    self.message_user(request, f'Budget {budget.name} approved')
                except Exception as e:
                    self.message_user(request, str(e), level='error')

    approve_budgets.short_description = "Approve selected budgets"


@admin.register(TaxCode)
class TaxCodeAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'tax_type', 'rate', 'is_active']
    list_filter = ['tax_type', 'is_active']
    search_fields = ['code', 'name']


@admin.register(AssetCategory)
class AssetCategoryAdmin(admin.ModelAdmin):
    list_display = [
        'code', 'name', 'default_depreciation_method',
        'default_useful_life_years', 'is_active'
    ]
    list_filter = ['default_depreciation_method', 'is_active']
    search_fields = ['code', 'name']


@admin.register(FixedAsset)
class FixedAssetAdmin(admin.ModelAdmin):
    list_display = [
        'asset_number', 'name', 'category', 'purchase_date',
        'purchase_cost', 'book_value', 'status'
    ]
    list_filter = ['status', 'category', 'depreciation_method']
    search_fields = ['asset_number', 'name', 'description']
    date_hierarchy = 'purchase_date'
    readonly_fields = [
        'depreciable_amount', 'accumulated_depreciation', 'book_value'
    ]
    filter_horizontal = ['dimension_values']


@admin.register(FinancialReport)
class FinancialReportAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'report_type', 'generated_at', 'generated_by', 'is_final'
    ]
    list_filter = ['report_type', 'is_final', 'generated_at']
    search_fields = ['name', 'description']
    date_hierarchy = 'generated_at'
    readonly_fields = ['report_data', 'generated_at']


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = [
        'timestamp', 'user', 'model_name', 'object_id', 'action'
    ]
    list_filter = ['action', 'model_name', 'timestamp']
    search_fields = ['model_name', 'object_id', 'user__username']
    date_hierarchy = 'timestamp'
    readonly_fields = ['timestamp', 'user', 'model_name', 'object_id', 'action', 'changes_json']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False