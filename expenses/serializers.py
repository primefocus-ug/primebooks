"""
serializers.py — DRF serializers for the expenses app.

Completely rewritten to match the actual model:
  • No ExpenseCategory / ExpenseAttachment / ExpenseComment FK references
  • ExpenseApprovalSerializer — full audit trail
  • currency, exchange_rate, amount_base, vendor, status (lowercase)
  • Recurring fields: recurrence_interval, next_recurrence_date
  • OCR fields exposed (read-only)
  • BudgetSerializer with computed spending fields
"""

from decimal import Decimal

from rest_framework import serializers

from .models import Budget, Expense, ExpenseApproval


# ---------------------------------------------------------------------------
# Approval history
# ---------------------------------------------------------------------------

class ExpenseApprovalSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()
    action_display = serializers.CharField(source='get_action_display', read_only=True)

    class Meta:
        model = ExpenseApproval
        fields = [
            'id', 'action', 'action_display',
            'actor', 'actor_name',
            'previous_status', 'new_status',
            'comment', 'created_at',
        ]
        read_only_fields = fields

    def get_actor_name(self, obj):
        if obj.actor:
            return obj.actor.get_full_name() or obj.actor.username
        return 'System'


# ---------------------------------------------------------------------------
# Expense — full
# ---------------------------------------------------------------------------

class ExpenseSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField(read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    payment_method_display = serializers.CharField(
        source='get_payment_method_display', read_only=True
    )
    currency_display = serializers.CharField(source='get_currency_display', read_only=True)
    tags = serializers.SerializerMethodField(read_only=True)
    tag_names = serializers.ListField(
        child=serializers.CharField(), write_only=True, required=False
    )
    approvals = ExpenseApprovalSerializer(many=True, read_only=True)

    class Meta:
        model = Expense
        fields = [
            # Identity
            'id', 'sync_id',
            # Owner
            'user', 'user_name',
            # Financial
            'amount', 'currency', 'currency_display',
            'exchange_rate', 'amount_base',
            # Core
            'description', 'vendor', 'date',
            'payment_method', 'payment_method_display',
            'notes', 'receipt',
            # Organisation
            'tags', 'tag_names',
            # Status / workflow
            'status', 'status_display',
            # Recurring
            'is_recurring', 'recurrence_interval', 'next_recurrence_date',
            # Flags
            'is_important',
            # OCR (read-only)
            'ocr_processed', 'ocr_vendor', 'ocr_amount',
            # Approval history
            'approvals',
            # Timestamps
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'sync_id', 'amount_base', 'user', 'user_name',
            'status_display', 'payment_method_display', 'currency_display',
            'ocr_processed', 'ocr_vendor', 'ocr_amount',
            'approvals', 'created_at', 'updated_at',
        ]

    def get_user_name(self, obj):
        if obj.user:
            return obj.user.get_full_name() or obj.user.username
        return ''

    def get_tags(self, obj):
        return list(obj.tags.names())

    def create(self, validated_data):
        tag_names = validated_data.pop('tag_names', [])
        expense = super().create(validated_data)
        if tag_names:
            expense.tags.set(*tag_names)
        return expense

    def update(self, instance, validated_data):
        tag_names = validated_data.pop('tag_names', None)
        expense = super().update(instance, validated_data)
        if tag_names is not None:
            expense.tags.set(*tag_names)
        return expense


# ---------------------------------------------------------------------------
# Expense — lightweight list view
# ---------------------------------------------------------------------------

class ExpenseListSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField(read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    tags = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Expense
        fields = [
            'id', 'description', 'vendor',
            'amount', 'currency', 'amount_base',
            'date', 'status', 'status_display',
            'user_name', 'tags',
            'is_recurring', 'is_important',
            'created_at',
        ]

    def get_user_name(self, obj):
        if obj.user:
            return obj.user.get_full_name() or obj.user.username
        return ''

    def get_tags(self, obj):
        return list(obj.tags.names())


# ---------------------------------------------------------------------------
# ExpenseApproval — write (used when posting a new approval action)
# ---------------------------------------------------------------------------

class ExpenseApprovalWriteSerializer(serializers.Serializer):
    """
    POST body for submitting, approving, or rejecting an expense via the API.
    The view is responsible for calling ExpenseApproval.record().
    """
    action = serializers.ChoiceField(choices=[c[0] for c in ExpenseApproval.ACTION_CHOICES])
    comment = serializers.CharField(required=False, allow_blank=True, max_length=500)

    def validate(self, data):
        if data.get('action') in ('rejected', 'resubmit') and not data.get('comment', '').strip():
            raise serializers.ValidationError(
                {'comment': 'A comment is required when rejecting or requesting resubmission.'}
            )
        return data


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------

class BudgetSerializer(serializers.ModelSerializer):
    period_display = serializers.CharField(source='get_period_display', read_only=True)
    tags = serializers.SerializerMethodField(read_only=True)
    tag_names = serializers.ListField(
        child=serializers.CharField(), write_only=True, required=False
    )
    # Computed / read-only spending fields
    current_spending = serializers.SerializerMethodField(read_only=True)
    percentage_used = serializers.SerializerMethodField(read_only=True)
    remaining = serializers.SerializerMethodField(read_only=True)
    status_color = serializers.SerializerMethodField(read_only=True)
    over_threshold = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Budget
        fields = [
            'id', 'sync_id',
            'name', 'amount', 'currency', 'period', 'period_display',
            'tags', 'tag_names',
            'alert_threshold', 'is_active',
            # Computed
            'current_spending', 'percentage_used', 'remaining',
            'status_color', 'over_threshold',
            # Timestamps
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'sync_id', 'period_display',
            'current_spending', 'percentage_used', 'remaining',
            'status_color', 'over_threshold',
            'created_at', 'updated_at',
        ]

    def get_tags(self, obj):
        return list(obj.tags.names())

    def get_current_spending(self, obj):
        return float(obj.get_current_spending())

    def get_percentage_used(self, obj):
        return round(float(obj.get_percentage_used()), 2)

    def get_remaining(self, obj):
        return float(obj.get_remaining())

    def get_status_color(self, obj):
        return obj.get_status_color()

    def get_over_threshold(self, obj):
        return obj.is_over_threshold()

    def create(self, validated_data):
        tag_names = validated_data.pop('tag_names', [])
        budget = super().create(validated_data)
        if tag_names:
            budget.tags.set(*tag_names)
        return budget

    def update(self, instance, validated_data):
        tag_names = validated_data.pop('tag_names', None)
        budget = super().update(instance, validated_data)
        if tag_names is not None:
            budget.tags.set(*tag_names)
        return budget