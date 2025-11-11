from rest_framework import serializers
from rest_framework.validators import UniqueTogetherValidator
from django.db import transaction
from django.db.models import Sum, Q
from django.utils import timezone
from decimal import Decimal
import json

from .models import (
    ChartOfAccounts, JournalEntry, JournalEntryLine, BankAccount,
    Transaction, Budget, BudgetLine, TaxCode, FixedAsset,
    BankReconciliation, RecurringJournalEntry, Currency, ExchangeRate,
    Dimension, DimensionValue, FiscalYear, FiscalPeriod, Journal,
    AssetCategory, BankReconciliationItem, BankStatement, FinancialReport,
    DepreciationRecord
)


# ============================================
# UTILITY SERIALIZERS & FIELDS
# ============================================

class DynamicFieldsModelSerializer(serializers.ModelSerializer):
    """Serializer that can dynamically include/exclude fields"""

    def __init__(self, *args, **kwargs):
        fields = kwargs.pop('fields', None)
        exclude = kwargs.pop('exclude', None)
        super().__init__(*args, **kwargs)

        if fields is not None:
            allowed = set(fields)
            existing = set(self.fields)
            for field_name in existing - allowed:
                self.fields.pop(field_name)

        if exclude is not None:
            for field_name in exclude:
                self.fields.pop(field_name, None)


class CurrencyField(serializers.Field):
    """Custom field for currency amounts"""

    def to_representation(self, value):
        return float(value) if value else 0.0

    def to_internal_value(self, data):
        try:
            return Decimal(str(data))
        except (TypeError, ValueError):
            raise serializers.ValidationError('Invalid currency amount')


class JSONField(serializers.Field):
    """Custom field for JSON data"""

    def to_representation(self, value):
        return value

    def to_internal_value(self, data):
        if isinstance(data, str):
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                raise serializers.ValidationError('Invalid JSON format')
        return data


# ============================================
# CURRENCY & EXCHANGE RATE SERIALIZERS
# ============================================

class CurrencySerializer(DynamicFieldsModelSerializer):
    """Currency Serializer"""

    class Meta:
        model = Currency
        fields = [
            'id', 'code', 'name', 'symbol', 'decimal_places',
            'is_base', 'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']


class ExchangeRateSerializer(DynamicFieldsModelSerializer):
    """Exchange Rate Serializer"""
    from_currency_code = serializers.CharField(source='from_currency.code', read_only=True)
    to_currency_code = serializers.CharField(source='to_currency.code', read_only=True)
    from_currency_name = serializers.CharField(source='from_currency.name', read_only=True)
    to_currency_name = serializers.CharField(source='to_currency.name', read_only=True)

    class Meta:
        model = ExchangeRate
        fields = [
            'id', 'from_currency', 'to_currency', 'from_currency_code', 'to_currency_code',
            'from_currency_name', 'to_currency_name', 'rate', 'rate_date', 'rate_type',
            'source', 'is_active', 'created_by', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_by', 'created_at', 'updated_at']

    def validate(self, attrs):
        from_currency = attrs.get('from_currency')
        to_currency = attrs.get('to_currency')
        rate_date = attrs.get('rate_date')
        rate_type = attrs.get('rate_type')

        if from_currency and to_currency and from_currency == to_currency:
            raise serializers.ValidationError({
                'to_currency': 'From and To currencies cannot be the same'
            })

        # Check for duplicate
        if self.instance:
            existing = ExchangeRate.objects.filter(
                from_currency=from_currency,
                to_currency=to_currency,
                rate_date=rate_date,
                rate_type=rate_type
            ).exclude(pk=self.instance.pk)
        else:
            existing = ExchangeRate.objects.filter(
                from_currency=from_currency,
                to_currency=to_currency,
                rate_date=rate_date,
                rate_type=rate_type
            )

        if existing.exists():
            raise serializers.ValidationError({
                'rate_date': 'Exchange rate for this currency pair and date already exists'
            })

        return attrs


# ============================================
# DIMENSION SERIALIZERS
# ============================================

class DimensionValueNestedSerializer(DynamicFieldsModelSerializer):
    """Nested Dimension Value Serializer"""

    class Meta:
        model = DimensionValue
        fields = ['id', 'code', 'name', 'is_active']


class DimensionSerializer(DynamicFieldsModelSerializer):
    """Dimension Serializer"""
    values = DimensionValueNestedSerializer(many=True, read_only=True)
    parent_name = serializers.CharField(source='parent.name', read_only=True)
    value_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Dimension
        fields = [
            'id', 'code', 'name', 'description', 'dimension_type', 'parent',
            'parent_name', 'level', 'is_active', 'require_for_posting',
            'values', 'value_count', 'created_by', 'created_at', 'updated_at'
        ]
        read_only_fields = ['level', 'created_by', 'created_at', 'updated_at']


class DimensionValueSerializer(DynamicFieldsModelSerializer):
    """Dimension Value Serializer"""
    dimension_code = serializers.CharField(source='dimension.code', read_only=True)
    dimension_name = serializers.CharField(source='dimension.name', read_only=True)
    parent_name = serializers.CharField(source='parent.name', read_only=True)
    manager_name = serializers.CharField(source='manager.get_full_name', read_only=True)

    class Meta:
        model = DimensionValue
        fields = [
            'id', 'dimension', 'dimension_code', 'dimension_name', 'code', 'name',
            'description', 'parent', 'parent_name', 'manager', 'manager_name',
            'is_active', 'budget_allocation_percentage', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']


# ============================================
# CHART OF ACCOUNTS SERIALIZERS
# ============================================

class ChartOfAccountsNestedSerializer(DynamicFieldsModelSerializer):
    """Nested Chart of Accounts Serializer"""

    class Meta:
        model = ChartOfAccounts
        fields = ['id', 'code', 'name', 'account_type', 'is_header']


class ChartOfAccountsSerializer(DynamicFieldsModelSerializer):
    """Chart of Accounts Serializer"""
    parent_name = serializers.CharField(source='parent.name', read_only=True)
    currency_code = serializers.CharField(source='currency.code', read_only=True)
    currency_name = serializers.CharField(source='currency.name', read_only=True)
    tax_code_name = serializers.CharField(source='tax_code.name', read_only=True)
    revaluation_account_name = serializers.CharField(source='revaluation_account.name', read_only=True)
    current_balance = CurrencyField()
    current_balance_base = CurrencyField()
    child_count = serializers.IntegerField(read_only=True)
    transaction_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = ChartOfAccounts
        fields = [
            'id', 'code', 'name', 'description', 'account_type', 'parent', 'parent_name',
            'level', 'is_header', 'currency', 'currency_code', 'currency_name',
            'allow_multi_currency', 'revaluation_account', 'revaluation_account_name',
            'current_balance', 'current_balance_base', 'require_dimensions',
            'allow_direct_posting', 'is_reconcilable', 'is_control_account',
            'is_active', 'is_system', 'tax_code', 'tax_code_name',
            'child_count', 'transaction_count', 'created_by', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'level', 'current_balance', 'current_balance_base', 'created_by',
            'created_at', 'updated_at', 'child_count', 'transaction_count'
        ]

    def validate_code(self, value):
        return value.upper().strip()

    def validate(self, attrs):
        is_header = attrs.get('is_header', self.instance.is_header if self.instance else False)
        parent = attrs.get('parent', self.instance.parent if self.instance else None)

        if is_header and parent and not parent.is_header:
            raise serializers.ValidationError({
                'parent': 'Header accounts can only have other header accounts as parents'
            })

        return attrs


# ============================================
# JOURNAL ENTRY SERIALIZERS
# ============================================

class JournalEntryLineSerializer(DynamicFieldsModelSerializer):
    """Journal Entry Line Serializer"""
    account_code = serializers.CharField(source='account.code', read_only=True)
    account_name = serializers.CharField(source='account.name', read_only=True)
    currency_code = serializers.CharField(source='currency.code', read_only=True)
    debit_amount = CurrencyField()
    credit_amount = CurrencyField()
    debit_amount_base = CurrencyField()
    credit_amount_base = CurrencyField()
    dimension_values_list = serializers.SerializerMethodField()

    class Meta:
        model = JournalEntryLine
        fields = [
            'id', 'journal_entry', 'line_number', 'account', 'account_code', 'account_name',
            'description', 'currency', 'currency_code', 'debit_amount', 'credit_amount',
            'exchange_rate', 'debit_amount_base', 'credit_amount_base',
            'dimension_values', 'dimension_values_list', 'tax_code', 'tax_amount',
            'quantity', 'unit_price', 'created_at', 'updated_at'
        ]
        read_only_fields = ['line_number', 'exchange_rate', 'debit_amount_base',
                            'credit_amount_base', 'created_at', 'updated_at']

    def get_dimension_values_list(self, obj):
        return list(obj.dimension_values.values('id', 'code', 'name'))

    def validate(self, attrs):
        debit_amount = attrs.get('debit_amount', 0)
        credit_amount = attrs.get('credit_amount', 0)
        account = attrs.get('account')

        if debit_amount and credit_amount:
            raise serializers.ValidationError({
                'debit_amount': 'Cannot have both debit and credit amounts',
                'credit_amount': 'Cannot have both debit and credit amounts'
            })

        if not debit_amount and not credit_amount:
            raise serializers.ValidationError({
                'debit_amount': 'Must have either debit or credit amount',
                'credit_amount': 'Must have either debit or credit amount'
            })

        # Validate account requirements
        if account and not account.allow_direct_posting:
            raise serializers.ValidationError({
                'account': f'Account {account.code} does not allow direct posting'
            })

        if account and account.is_header:
            raise serializers.ValidationError({
                'account': f'Cannot post to header account {account.code}'
            })

        return attrs


class JournalEntrySerializer(DynamicFieldsModelSerializer):
    """Journal Entry Serializer"""
    lines = JournalEntryLineSerializer(many=True, required=False)
    journal_code = serializers.CharField(source='journal.code', read_only=True)
    journal_name = serializers.CharField(source='journal.name', read_only=True)
    currency_code = serializers.CharField(source='currency.code', read_only=True)
    fiscal_year_name = serializers.CharField(source='fiscal_year.name', read_only=True)
    fiscal_period_name = serializers.CharField(source='fiscal_period.name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    posted_by_name = serializers.CharField(source='posted_by.get_full_name', read_only=True)
    total_debit = CurrencyField(read_only=True)
    total_credit = CurrencyField(read_only=True)
    total_debit_base = CurrencyField(read_only=True)
    total_credit_base = CurrencyField(read_only=True)
    is_balanced = serializers.BooleanField(read_only=True)

    class Meta:
        model = JournalEntry
        fields = [
            'id', 'entry_number', 'journal', 'journal_code', 'journal_name',
            'entry_date', 'posting_date', 'fiscal_year', 'fiscal_year_name',
            'fiscal_period', 'fiscal_period_name', 'reference', 'description',
            'notes', 'status', 'currency', 'currency_code', 'exchange_rate',
            'total_debit', 'total_credit', 'total_debit_base', 'total_credit_base',
            'is_balanced', 'is_reversal', 'reverses_entry', 'reversal_date',
            'source_model', 'source_id', 'requires_approval', 'approved_by',
            'approved_at', 'created_by', 'created_by_name', 'created_at',
            'updated_at', 'posted_by', 'posted_by_name', 'posted_at', 'lines'
        ]
        read_only_fields = [
            'entry_number', 'total_debit', 'total_credit', 'total_debit_base',
            'total_credit_base', 'is_balanced', 'posted_by', 'posted_at',
            'approved_by', 'approved_at', 'created_by', 'created_at', 'updated_at'
        ]

    @transaction.atomic
    def create(self, validated_data):
        lines_data = validated_data.pop('lines', [])
        journal = validated_data.get('journal')

        # Generate entry number
        if not validated_data.get('entry_number'):
            validated_data['entry_number'] = journal.get_next_entry_number()

        journal_entry = JournalEntry.objects.create(**validated_data)

        # Create lines
        for i, line_data in enumerate(lines_data, 1):
            line_data['line_number'] = i
            JournalEntryLine.objects.create(journal_entry=journal_entry, **line_data)

        # Calculate totals
        journal_entry.calculate_totals()

        return journal_entry

    @transaction.atomic
    def update(self, instance, validated_data):
        lines_data = validated_data.pop('lines', None)

        # Update journal entry
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # Update lines if provided
        if lines_data is not None:
            # Delete existing lines
            instance.lines.all().delete()

            # Create new lines
            for i, line_data in enumerate(lines_data, 1):
                line_data['line_number'] = i
                JournalEntryLine.objects.create(journal_entry=instance, **line_data)

            # Recalculate totals
            instance.calculate_totals()

        return instance


class JournalEntryPostSerializer(serializers.Serializer):
    """Serializer for posting journal entries"""
    posting_date = serializers.DateField(required=False)
    user_id = serializers.IntegerField(required=False)

    def validate_posting_date(self, value):
        if value and value > timezone.now().date():
            raise serializers.ValidationError('Posting date cannot be in the future')
        return value


# ============================================
# BUDGET SERIALIZERS
# ============================================

class BudgetLineSerializer(DynamicFieldsModelSerializer):
    """Budget Line Serializer"""
    account_code = serializers.CharField(source='account.code', read_only=True)
    account_name = serializers.CharField(source='account.name', read_only=True)
    currency_code = serializers.CharField(source='currency.code', read_only=True)
    amount = CurrencyField()
    actual_amount = CurrencyField(read_only=True)
    variance = CurrencyField(read_only=True)
    utilization_percentage = serializers.DecimalField(
        max_digits=5, decimal_places=2, read_only=True
    )
    dimension_values_list = serializers.SerializerMethodField()
    period_distribution = JSONField()

    class Meta:
        model = BudgetLine
        fields = [
            'id', 'budget', 'account', 'account_code', 'account_name',
            'amount', 'currency', 'currency_code', 'description', 'notes',
            'dimension_values', 'dimension_values_list', 'period_distribution',
            'actual_amount', 'variance', 'utilization_percentage',
            'last_actual_update', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'actual_amount', 'variance', 'utilization_percentage',
            'last_actual_update', 'created_at', 'updated_at'
        ]

    def get_dimension_values_list(self, obj):
        return list(obj.dimension_values.values('id', 'code', 'name'))


class BudgetSerializer(DynamicFieldsModelSerializer):
    """Budget Serializer"""
    lines = BudgetLineSerializer(many=True, required=False)
    fiscal_year_name = serializers.CharField(source='fiscal_year.name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.get_full_name', read_only=True)
    total_budget = CurrencyField(read_only=True)
    total_actual = CurrencyField(read_only=True)
    total_variance = CurrencyField(read_only=True)
    utilization_percentage = serializers.DecimalField(
        max_digits=5, decimal_places=2, read_only=True
    )
    line_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Budget
        fields = [
            'id', 'name', 'code', 'description', 'budget_type', 'fiscal_year',
            'fiscal_year_name', 'start_date', 'end_date', 'status', 'version',
            'parent_budget', 'is_baseline', 'scenario', 'allow_overrun',
            'alert_threshold', 'total_budget', 'total_actual', 'total_variance',
            'utilization_percentage', 'line_count', 'created_by', 'created_by_name',
            'created_at', 'updated_at', 'approved_by', 'approved_by_name',
            'approved_at', 'lines'
        ]
        read_only_fields = [
            'total_budget', 'total_actual', 'total_variance', 'utilization_percentage',
            'line_count', 'created_by', 'created_at', 'updated_at', 'approved_by',
            'approved_at'
        ]

    @transaction.atomic
    def create(self, validated_data):
        lines_data = validated_data.pop('lines', [])
        budget = Budget.objects.create(**validated_data)

        for line_data in lines_data:
            BudgetLine.objects.create(budget=budget, **line_data)

        budget.calculate_totals()
        return budget

    @transaction.atomic
    def update(self, instance, validated_data):
        lines_data = validated_data.pop('lines', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if lines_data is not None:
            instance.lines.all().delete()
            for line_data in lines_data:
                BudgetLine.objects.create(budget=instance, **line_data)

            instance.calculate_totals()

        return instance


# ============================================
# BANKING SERIALIZERS
# ============================================

class BankAccountSerializer(DynamicFieldsModelSerializer):
    """Bank Account Serializer"""
    gl_account_code = serializers.CharField(source='gl_account.code', read_only=True)
    gl_account_name = serializers.CharField(source='gl_account.name', read_only=True)
    currency_code = serializers.CharField(source='currency.code', read_only=True)
    opening_balance = CurrencyField()
    current_balance = CurrencyField(read_only=True)
    available_balance = CurrencyField(read_only=True)
    overdraft_limit = CurrencyField()
    transaction_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = BankAccount
        fields = [
            'id', 'account_number', 'account_name', 'bank_name', 'bank_branch',
            'swift_code', 'iban', 'gl_account', 'gl_account_code', 'gl_account_name',
            'currency', 'currency_code', 'opening_balance', 'current_balance',
            'available_balance', 'is_default', 'is_active', 'overdraft_limit',
            'enable_bank_feed', 'bank_feed_config', 'last_sync_date',
            'transaction_count', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'current_balance', 'available_balance', 'last_sync_date',
            'transaction_count', 'created_at', 'updated_at'
        ]


class TransactionSerializer(DynamicFieldsModelSerializer):
    """Bank Transaction Serializer"""
    bank_account_number = serializers.CharField(source='bank_account.account_number', read_only=True)
    currency_code = serializers.CharField(source='currency.code', read_only=True)
    amount = CurrencyField()
    journal_entry_number = serializers.CharField(source='journal_entry.entry_number', read_only=True)

    class Meta:
        model = Transaction
        fields = [
            'id', 'transaction_id', 'bank_account', 'bank_account_number',
            'transaction_date', 'value_date', 'transaction_type', 'amount',
            'currency', 'currency_code', 'description', 'reference', 'payee',
            'status', 'is_cleared', 'cleared_date', 'journal_entry',
            'journal_entry_number', 'transfer_to', 'created_by', 'created_at',
            'updated_at'
        ]
        read_only_fields = ['created_by', 'created_at', 'updated_at']


# ============================================
# FIXED ASSET SERIALIZERS
# ============================================

class AssetCategorySerializer(DynamicFieldsModelSerializer):
    """Asset Category Serializer"""
    asset_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = AssetCategory
        fields = [
            'id', 'code', 'name', 'description', 'asset_account',
            'accumulated_depreciation_account', 'depreciation_expense_account',
            'gain_loss_account', 'default_depreciation_method',
            'default_useful_life_years', 'default_salvage_percentage',
            'is_active', 'asset_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['asset_count', 'created_at', 'updated_at']


class FixedAssetSerializer(DynamicFieldsModelSerializer):
    """Fixed Asset Serializer"""
    category_name = serializers.CharField(source='category.name', read_only=True)
    currency_code = serializers.CharField(source='currency.code', read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.get_full_name', read_only=True)
    purchase_cost = CurrencyField()
    salvage_value = CurrencyField()
    depreciable_amount = CurrencyField(read_only=True)
    accumulated_depreciation = CurrencyField(read_only=True)
    book_value = CurrencyField(read_only=True)
    disposal_proceeds = CurrencyField()
    disposal_gain_loss = CurrencyField()
    depreciation_records_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = FixedAsset
        fields = [
            'id', 'asset_number', 'name', 'description', 'category', 'category_name',
            'purchase_date', 'purchase_cost', 'currency', 'currency_code', 'vendor',
            'invoice_number', 'location', 'dimension_values', 'assigned_to',
            'assigned_to_name', 'depreciation_method', 'useful_life_years',
            'useful_life_months', 'salvage_value', 'depreciable_amount',
            'accumulated_depreciation', 'book_value', 'depreciation_start_date',
            'total_units', 'units_produced_to_date', 'disposal_date',
            'disposal_proceeds', 'disposal_gain_loss', 'status',
            'depreciation_records_count', 'created_by', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'depreciable_amount', 'accumulated_depreciation', 'book_value',
            'depreciation_records_count', 'created_by', 'created_at', 'updated_at'
        ]


class DepreciationRecordSerializer(DynamicFieldsModelSerializer):
    """Depreciation Record Serializer"""
    asset_number = serializers.CharField(source='asset.asset_number', read_only=True)
    asset_name = serializers.CharField(source='asset.name', read_only=True)
    fiscal_period_name = serializers.CharField(source='fiscal_period.name', read_only=True)
    depreciation_amount = CurrencyField()
    accumulated_depreciation = CurrencyField()
    book_value = CurrencyField()
    journal_entry_number = serializers.CharField(source='journal_entry.entry_number', read_only=True)

    class Meta:
        model = DepreciationRecord
        fields = [
            'id', 'asset', 'asset_number', 'asset_name', 'fiscal_period',
            'fiscal_period_name', 'depreciation_amount', 'accumulated_depreciation',
            'book_value', 'journal_entry', 'journal_entry_number', 'created_by',
            'created_at'
        ]
        read_only_fields = ['created_by', 'created_at']


# ============================================
# TAX SERIALIZERS
# ============================================

class TaxCodeSerializer(DynamicFieldsModelSerializer):
    """Tax Code Serializer"""
    tax_collected_account_code = serializers.CharField(
        source='tax_collected_account.code', read_only=True
    )
    tax_paid_account_code = serializers.CharField(
        source='tax_paid_account.code', read_only=True
    )
    account_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = TaxCode
        fields = [
            'id', 'code', 'name', 'description', 'tax_type', 'rate',
            'tax_collected_account', 'tax_collected_account_code',
            'tax_paid_account', 'tax_paid_account_code', 'is_compound',
            'effective_date', 'expiry_date', 'tax_authority', 'filing_frequency',
            'is_active', 'account_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['account_count', 'created_at', 'updated_at']


# ============================================
# RECURRING JOURNAL & AUTOMATION SERIALIZERS
# ============================================

class RecurringJournalEntrySerializer(DynamicFieldsModelSerializer):
    """Recurring Journal Entry Serializer"""
    journal_code = serializers.CharField(source='journal.code', read_only=True)
    journal_name = serializers.CharField(source='journal.name', read_only=True)
    currency_code = serializers.CharField(source='currency.code', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    template_data = JSONField()
    next_run_date = serializers.DateField(read_only=True)
    last_run_date = serializers.DateField(read_only=True)
    generated_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = RecurringJournalEntry
        fields = [
            'id', 'name', 'code', 'description', 'journal', 'journal_code', 'journal_name',
            'frequency', 'start_date', 'end_date', 'next_run_date', 'last_run_date',
            'currency', 'currency_code', 'template_data', 'auto_post', 'is_active',
            'generated_count', 'created_by', 'created_by_name', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'next_run_date', 'last_run_date', 'generated_count', 'created_by',
            'created_at', 'updated_at'
        ]


# ============================================
# FINANCIAL REPORTING SERIALIZERS
# ============================================

class FinancialReportSerializer(DynamicFieldsModelSerializer):
    """Financial Report Serializer"""
    generated_by_name = serializers.CharField(source='generated_by.get_full_name', read_only=True)
    report_data = JSONField()
    filters_applied = JSONField()

    class Meta:
        model = FinancialReport
        fields = [
            'id', 'name', 'report_type', 'description', 'start_date', 'end_date',
            'as_of_date', 'fiscal_period', 'report_data', 'filters_applied',
            'is_final', 'generated_by', 'generated_by_name', 'generated_at'
        ]
        read_only_fields = ['generated_by', 'generated_at']


# ============================================
# DASHBOARD & ANALYTICS SERIALIZERS
# ============================================

class DashboardSummarySerializer(serializers.Serializer):
    """Dashboard Summary Serializer"""
    total_accounts = serializers.IntegerField()
    active_accounts = serializers.IntegerField()
    total_journal_entries = serializers.IntegerField()
    pending_approval_entries = serializers.IntegerField()
    total_bank_accounts = serializers.IntegerField()
    total_bank_balance = CurrencyField()
    total_budgets = serializers.IntegerField()
    active_budgets = serializers.IntegerField()
    total_assets = serializers.IntegerField()
    total_asset_value = CurrencyField()


class FinancialStatementSerializer(serializers.Serializer):
    """Financial Statement Serializer"""
    period = serializers.CharField()
    accounts = serializers.ListField(child=serializers.DictField())
    totals = serializers.DictField()
    metadata = serializers.DictField()


class BudgetVarianceSerializer(serializers.Serializer):
    """Budget Variance Analysis Serializer"""
    account_code = serializers.CharField()
    account_name = serializers.CharField()
    budget_amount = CurrencyField()
    actual_amount = CurrencyField()
    variance_amount = CurrencyField()
    variance_percentage = serializers.DecimalField(max_digits=5, decimal_places=2)


# ============================================
# BULK OPERATION SERIALIZERS
# ============================================

class BulkJournalEntryCreateSerializer(serializers.Serializer):
    """Bulk Journal Entry Creation Serializer"""
    journal_id = serializers.IntegerField()
    entry_date = serializers.DateField()
    description = serializers.CharField()
    lines = JournalEntryLineSerializer(many=True)
    auto_post = serializers.BooleanField(default=False)


class BulkAccountUpdateSerializer(serializers.Serializer):
    """Bulk Account Update Serializer"""
    account_ids = serializers.ListField(child=serializers.IntegerField())
    updates = serializers.DictField()


# ============================================
# SEARCH & FILTER SERIALIZERS
# ============================================

class JournalEntrySearchSerializer(serializers.Serializer):
    """Journal Entry Search Serializer"""
    journal = serializers.IntegerField(required=False)
    status = serializers.ListField(child=serializers.CharField(), required=False)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    account = serializers.IntegerField(required=False)
    amount_min = CurrencyField(required=False)
    amount_max = CurrencyField(required=False)
    reference = serializers.CharField(required=False)
    description = serializers.CharField(required=False)
    page = serializers.IntegerField(default=1)
    page_size = serializers.IntegerField(default=50)


class TransactionSearchSerializer(serializers.Serializer):
    """Transaction Search Serializer"""
    bank_account = serializers.IntegerField(required=False)
    transaction_type = serializers.ListField(child=serializers.CharField(), required=False)
    status = serializers.ListField(child=serializers.CharField(), required=False)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    amount_min = CurrencyField(required=False)
    amount_max = CurrencyField(required=False)
    description = serializers.CharField(required=False)


# ============================================
# IMPORT/EXPORT SERIALIZERS
# ============================================

class DataExportRequestSerializer(serializers.Serializer):
    """Data Export Request Serializer"""
    model_type = serializers.CharField()
    format = serializers.ChoiceField(choices=['csv', 'json', 'xlsx'])
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)
    include_inactive = serializers.BooleanField(default=False)
    filters = serializers.DictField(required=False)


class ImportResultSerializer(serializers.Serializer):
    """Import Result Serializer"""
    total_records = serializers.IntegerField()
    successful = serializers.IntegerField()
    failed = serializers.IntegerField()
    errors = serializers.ListField(child=serializers.DictField())