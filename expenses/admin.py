from django.contrib import admin
from django.db.models import Sum
from django.utils.html import format_html

from .models import Expense, Budget


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = (
        "description",
        "amount",
        "user",
        "date",
        "tag_list",
        "receipt_link",
        "created_at",
    )

    list_filter = (
        "date",
        "user",
        "tags",
    )

    search_fields = (
        "description",
        "notes",
        "tags__name",
    )

    date_hierarchy = "date"
    ordering = ("-date", "-created_at")
    autocomplete_fields = ("user",)
    readonly_fields = ("created_at", "updated_at")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.prefetch_related("tags")

    @admin.display(description="Tags")
    def tag_list(self, obj):
        return ", ".join(obj.tags.names())

    @admin.display(description="Receipt")
    def receipt_link(self, obj):
        if obj.receipt:
            return format_html(
                '<a href="{}" target="_blank">Download</a>',
                obj.receipt.url
            )
        return "-"


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "user",
        "amount",
        "period",
        "tag_list",
        "current_spending",
        "percentage_used",
        "alert_threshold",
        "over_threshold",
        "is_active",
    )

    list_filter = (
        "period",
        "is_active",
        "user",
        "tags",
    )

    search_fields = (
        "name",
        "tags__name",
    )

    autocomplete_fields = ("user",)
    readonly_fields = ("created_at",)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.prefetch_related("tags")

    @admin.display(description="Tags")
    def tag_list(self, obj):
        return ", ".join(obj.tags.names()) or "—"

    @admin.display(description="Spending")
    def current_spending(self, obj):
        return f"${obj.get_current_spending():,.2f}"

    @admin.display(description="% Used")
    def percentage_used(self, obj):
        pct = obj.get_percentage_used()
        color = "red" if pct >= obj.alert_threshold else "green"
        return format_html(
            '<b style="color:{}">{:.1f}%</b>',
            color,
            pct
        )

    @admin.display(
        description="Over Alert",
        boolean=True,
    )
    def over_threshold(self, obj):
        return obj.is_over_threshold()
