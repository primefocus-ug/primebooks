from django.db.models import Q
from datetime import datetime, timedelta


class PublicAdminFilter:
    """Base class for custom filters"""

    def __init__(self, field_name, title):
        self.field_name = field_name
        self.title = title

    def get_choices(self, request, queryset):
        """Return list of (value, label) tuples"""
        raise NotImplementedError

    def filter_queryset(self, request, queryset, value):
        """Apply filter to queryset"""
        raise NotImplementedError


class DateRangeFilter(PublicAdminFilter):
    """Filter for date ranges"""

    def get_choices(self, request, queryset):
        return [
            ('today', 'Today'),
            ('yesterday', 'Yesterday'),
            ('this_week', 'This Week'),
            ('this_month', 'This Month'),
            ('last_30_days', 'Last 30 Days'),
            ('this_year', 'This Year'),
        ]

    def filter_queryset(self, request, queryset, value):
        today = datetime.now().date()

        if value == 'today':
            return queryset.filter(**{f'{self.field_name}__date': today})
        elif value == 'yesterday':
            yesterday = today - timedelta(days=1)
            return queryset.filter(**{f'{self.field_name}__date': yesterday})
        elif value == 'this_week':
            start_week = today - timedelta(days=today.weekday())
            return queryset.filter(**{f'{self.field_name}__date__gte': start_week})
        elif value == 'this_month':
            return queryset.filter(
                **{f'{self.field_name}__year': today.year,
                   f'{self.field_name}__month': today.month}
            )
        elif value == 'last_30_days':
            start_date = today - timedelta(days=30)
            return queryset.filter(**{f'{self.field_name}__date__gte': start_date})
        elif value == 'this_year':
            return queryset.filter(**{f'{self.field_name}__year': today.year})

        return queryset


class BooleanFilter(PublicAdminFilter):
    """Filter for boolean fields"""

    def get_choices(self, request, queryset):
        return [
            ('1', 'Yes'),
            ('0', 'No'),
        ]

    def filter_queryset(self, request, queryset, value):
        if value == '1':
            return queryset.filter(**{self.field_name: True})
        elif value == '0':
            return queryset.filter(**{self.field_name: False})
        return queryset


class ChoiceFilter(PublicAdminFilter):
    """Filter for choice fields"""

    def __init__(self, field_name, title, choices):
        super().__init__(field_name, title)
        self.choices = choices

    def get_choices(self, request, queryset):
        return self.choices

    def filter_queryset(self, request, queryset, value):
        return queryset.filter(**{self.field_name: value})