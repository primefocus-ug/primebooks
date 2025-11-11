from rest_framework import serializers
from .models import Expense, ExpenseCategory, ExpenseAttachment, ExpenseComment


class ExpenseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseCategory
        fields = [
            'id', 'name', 'code', 'description', 'color_code',
            'icon', 'monthly_budget', 'is_active'
        ]


class ExpenseAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseAttachment
        fields = ['id', 'file', 'filename', 'file_size', 'uploaded_at']


class ExpenseCommentSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)

    class Meta:
        model = ExpenseComment
        fields = ['id', 'comment', 'user_name', 'is_internal', 'created_at']


class ExpenseSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    attachments = ExpenseAttachmentSerializer(many=True, read_only=True)
    comments = ExpenseCommentSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    total_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Expense
        fields = [
            'id', 'expense_number', 'title', 'description', 'category',
            'category_name', 'amount', 'currency', 'tax_amount', 'tax_rate',
            'total_amount', 'expense_date', 'due_date', 'status', 'status_display',
            'vendor_name', 'vendor_phone', 'vendor_email', 'created_by',
            'created_by_name', 'created_at', 'is_reimbursable', 'is_recurring',
            'attachments', 'comments', 'notes'
        ]
        read_only_fields = ['expense_number', 'created_by', 'created_at']


class ExpenseListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views"""
    category_name = serializers.CharField(source='category.name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.get_full_name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Expense
        fields = [
            'id', 'expense_number', 'title', 'category_name', 'amount',
            'currency', 'expense_date', 'status', 'status_display',
            'created_by_name', 'created_at'
        ]