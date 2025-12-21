from django import forms
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.db.models import Q
from datetime import datetime, timedelta, date

from .models import SavedReport, ReportSchedule, ReportComparison, EFRISReportTemplate
from stores.models import Store
from inventory.models import Category, Product
from accounts.models import CustomUser


class DateRangeWidget(forms.MultiWidget):
    """Custom widget for date range selection."""
    def __init__(self, attrs=None):
        widgets = [
            forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
        ]
        super().__init__(widgets, attrs)

    def decompress(self, value):
        if value:
            return [value.start, value.end]
        return [None, None]


from django import forms
from django.utils.translation import gettext_lazy as _
from datetime import date, timedelta
from django.utils import timezone
from stores.models import Store


class ReportFilterForm(forms.Form):
    """Base form for common report filters."""
    PERIOD_CHOICES = [
        ('today', _('Today')),
        ('yesterday', _('Yesterday')),
        ('this_week', _('This Week')),
        ('last_week', _('Last Week')),
        ('this_month', _('This Month')),
        ('last_month', _('Last Month')),
        ('this_quarter', _('This Quarter')),
        ('last_quarter', _('Last Quarter')),
        ('this_year', _('This Year')),
        ('last_year', _('Last Year')),
        ('custom', _('Custom Range')),
    ]

    period = forms.ChoiceField(
        choices=PERIOD_CHOICES,
        required=False,
        initial='this_month',
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'period-select'})
    )

    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control',
            'id': 'start-date'
        }),
        label=_('Start Date')
    )

    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'type': 'date',
            'class': 'form-control',
            'id': 'end-date'
        }),
        label=_('End Date')
    )

    store = forms.ModelChoiceField(
        queryset=Store.objects.none(),
        required=False,
        empty_label=_('All Stores'),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('Store')
    )

    branch = forms.ModelChoiceField(
        queryset=Store.objects.none(),
        required=False,
        empty_label=_('All Branches'),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('Branch')
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if user:
            if user.is_superuser or (
                    hasattr(user, 'primary_role') and user.primary_role and user.primary_role.priority >= 90):
                # Superusers and high-priority roles see all stores
                self.fields['store'].queryset = Store.objects.filter(is_active=True)
                self.fields['branch'].queryset = Store.objects.filter(is_active=True)
            else:
                # Regular users see stores they can access
                accessible_stores = self.get_user_accessible_stores(user)
                self.fields['store'].queryset = accessible_stores
                self.fields['branch'].queryset = accessible_stores

        if not self.data.get('start_date') or not self.data.get('end_date'):
            self._set_default_dates()

    def get_user_accessible_stores(self, user):
        """
        Get stores accessible by a user.
        Users can access stores where they're staff OR stores from their company.
        """
        if user.is_superuser:
            return Store.objects.filter(is_active=True)

        # Get user's company if exists
        user_company = getattr(user, 'company', None)

        if user_company:
            # User can access stores where they're staff OR stores from their company
            stores = Store.objects.filter(
                Q(is_active=True) & (
                        Q(staff=user) |
                        Q(company=user_company)
                )
            ).distinct()
        else:
            # Users without company can only access stores where they're staff
            stores = Store.objects.filter(
                staff=user,
                is_active=True
            ).distinct()

        return stores

    def _set_default_dates(self):
        """Set default start and end dates based on selected period."""
        today = timezone.now().date()
        period = self.data.get('period', 'this_month')

        if period == 'today':
            self.fields['start_date'].initial = today
            self.fields['end_date'].initial = today
        elif period == 'yesterday':
            yesterday = today - timedelta(days=1)
            self.fields['start_date'].initial = yesterday
            self.fields['end_date'].initial = yesterday
        elif period == 'this_week':
            start_of_week = today - timedelta(days=today.weekday())
            self.fields['start_date'].initial = start_of_week
            self.fields['end_date'].initial = today
        elif period == 'last_week':
            start_of_last_week = today - timedelta(days=today.weekday() + 7)
            end_of_last_week = start_of_last_week + timedelta(days=6)
            self.fields['start_date'].initial = start_of_last_week
            self.fields['end_date'].initial = end_of_last_week
        elif period == 'this_month':
            self.fields['start_date'].initial = today.replace(day=1)
            self.fields['end_date'].initial = today
        elif period == 'last_month':
            first_of_this_month = today.replace(day=1)
            last_month_end = first_of_this_month - timedelta(days=1)
            last_month_start = last_month_end.replace(day=1)
            self.fields['start_date'].initial = last_month_start
            self.fields['end_date'].initial = last_month_end
        elif period == 'this_quarter':
            quarter_start_month = ((today.month - 1) // 3) * 3 + 1
            quarter_start = today.replace(month=quarter_start_month, day=1)
            self.fields['start_date'].initial = quarter_start
            self.fields['end_date'].initial = today
        elif period == 'this_year':
            self.fields['start_date'].initial = today.replace(month=1, day=1)
            self.fields['end_date'].initial = today
        elif period == 'last_year':
            last_year = today.year - 1
            self.fields['start_date'].initial = today.replace(year=last_year, month=1, day=1)
            self.fields['end_date'].initial = today.replace(year=last_year, month=12, day=31)

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')

        if start_date and end_date:
            if start_date > end_date:
                raise forms.ValidationError(_('Start date must be before end date.'))
            if (end_date - start_date).days > 730:
                raise forms.ValidationError(_('Date range cannot exceed 2 years.'))

        return cleaned_data

    def get_serialized_data(self):
        """Return cleaned data with dates and model fields serialized to strings."""
        cleaned_data = self.cleaned_data.copy()
        if cleaned_data.get('start_date') and isinstance(cleaned_data['start_date'], date):
            cleaned_data['start_date'] = cleaned_data['start_date'].isoformat()
        if cleaned_data.get('end_date') and isinstance(cleaned_data['end_date'], date):
            cleaned_data['end_date'] = cleaned_data['end_date'].isoformat()
        if cleaned_data.get('store') and isinstance(cleaned_data['store'], Store):
            cleaned_data['store'] = cleaned_data['store'].id
        if cleaned_data.get('branch') and isinstance(cleaned_data['branch'], Store):
            cleaned_data['branch'] = cleaned_data['branch'].id
        return cleaned_data


class CombinedReportForm(forms.Form):
    """Form for combined business reports"""

    REPORT_TYPE_CHOICES = [
        ('SALES_SUMMARY', _('Sales Summary')),
        ('PRODUCT_PERFORMANCE', _('Product Performance')),
        ('INVENTORY_STATUS', _('Inventory Status')),
        ('PROFIT_LOSS', _('Profit & Loss Statement')),
        ('EXPENSE_REPORT', _('Expense Report')),
        ('EXPENSE_ANALYTICS', _('Expense Analytics')),
        ('Z_REPORT', _('Z-Report (Daily Summary)')),
        ('EFRIS_COMPLIANCE', _('EFRIS Compliance')),
        ('CASHIER_PERFORMANCE', _('Cashier Performance')),
        ('STOCK_MOVEMENT', _('Stock Movement')),
        ('PRICE_LOOKUP', _('Price Lookup')),
        ('CUSTOMER_ANALYTICS', _('Customer Analytics')),
    ]

    start_date = forms.DateField(
        label=_("Start Date"),
        widget=forms.DateInput(attrs={'type': 'date'}),
        required=False
    )

    end_date = forms.DateField(
        label=_("End Date"),
        widget=forms.DateInput(attrs={'type': 'date'}),
        required=False
    )

    store = forms.ModelChoiceField(
        queryset=Store.objects.none(),
        label=_("Store"),
        required=False,
        empty_label=_("All Stores")
    )

    report_types = forms.MultipleChoiceField(
        choices=REPORT_TYPE_CHOICES,
        label=_("Select Reports to Include"),
        widget=forms.CheckboxSelectMultiple,
        required=True,
        initial=['SALES_SUMMARY', 'PROFIT_LOSS', 'INVENTORY_STATUS', 'EXPENSE_REPORT']
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if user:
            from stores.utils import get_user_accessible_stores
            stores = get_user_accessible_stores(user)
            self.fields['store'].queryset = stores

class SalesReportForm(ReportFilterForm):
    """Extended form for sales reports with additional filters."""
    GROUP_BY_CHOICES = [
        ('date', _('By Date')),
        ('store', _('By Store')),
        ('branch', _('By Branch')),
        ('payment_method', _('By Payment Method')),
        ('product', _('By Product')),
    ]

    TRANSACTION_TYPE_CHOICES = [
        ('', _('All Types')),
        ('SALE', _('Sales Only')),
        ('REFUND', _('Refunds Only')),
    ]

    group_by = forms.ChoiceField(
        choices=GROUP_BY_CHOICES,
        initial='date',
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('Group By')
    )

    transaction_type = forms.ChoiceField(
        choices=TRANSACTION_TYPE_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('Transaction Type')
    )

    payment_method = forms.ChoiceField(
        choices=[('', _('All Payment Methods'))] + [
            ('CASH', _('Cash')),
            ('CARD', _('Credit Card')),
            ('MOBILE_MONEY', _('Mobile Money')),
            ('BANK_TRANSFER', _('Bank Transfer')),
            ('VOUCHER', _('Voucher')),
            ('CREDIT', _('Customer Credit')),
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('Payment Method')
    )

    min_amount = forms.DecimalField(
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'step': '0.01',
            'placeholder': _('Minimum Amount')
        }),
        label=_('Minimum Amount')
    )

    max_amount = forms.DecimalField(
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'step': '0.01',
            'placeholder': _('Maximum Amount')
        }),
        label=_('Maximum Amount')
    )

    cashier = forms.ModelChoiceField(
        queryset=CustomUser.objects.none(),
        required=False,
        empty_label=_('All Cashiers'),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('Cashier')
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.get('user')
        super().__init__(*args, **kwargs)

        if user:
            if user.is_superuser or (user.primary_role and user.primary_role.priority >= 90):
                self.fields['cashier'].queryset = CustomUser.objects.filter(
                    primary_role__priority__gte=30,  # Cashier-level roles and above
                    primary_role__priority__lte=80,  # But below admin level
                    is_active=True
                )
            else:
                store_ids = user.stores.values_list('id', flat=True)
                self.fields['cashier'].queryset = CustomUser.objects.filter(
                    stores__id__in=store_ids,
                    is_active=True
                ).distinct()


class InventoryReportForm(ReportFilterForm):
    """Form for inventory status reports."""
    STATUS_CHOICES = [
        ('', _('All Status')),
        ('in_stock', _('In Stock')),
        ('low_stock', _('Low Stock')),
        ('out_of_stock', _('Out of Stock')),
    ]

    status = forms.ChoiceField(
        choices=STATUS_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('Stock Status')
    )

    category = forms.ModelChoiceField(
        queryset=Category.objects.all(),
        required=False,
        empty_label=_('All Categories'),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('Category')
    )

    product = forms.ModelChoiceField(
        queryset=Product.objects.filter(is_active=True),
        required=False,
        empty_label=_('All Products'),
        widget=forms.Select(attrs={'class': 'form-select select2'}),
        label=_('Specific Product')
    )

    show_inactive = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label=_('Include Inactive Products')
    )

    sort_by = forms.ChoiceField(
        choices=[
            ('product_name', _('Product Name')),
            ('quantity_asc', _('Quantity (Low to High)')),
            ('quantity_desc', _('Quantity (High to Low)')),
            ('stock_value', _('Stock Value')),
            ('last_updated', _('Last Updated')),
        ],
        initial='product_name',
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('Sort By')
    )


class ProductPerformanceForm(ReportFilterForm):
    """Form for product performance reports."""
    SORT_BY_CHOICES = [
        ('revenue_desc', _('Revenue (High to Low)')),
        ('revenue_asc', _('Revenue (Low to High)')),
        ('quantity_desc', _('Quantity Sold (High to Low)')),
        ('quantity_asc', _('Quantity Sold (Low to High)')),
        ('profit_desc', _('Profit (High to Low)')),
        ('transactions_desc', _('Transaction Count (High to Low)')),
    ]

    category = forms.ModelChoiceField(
        queryset=Category.objects.all(),
        required=False,
        empty_label=_('All Categories'),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('Category')
    )

    sort_by = forms.ChoiceField(
        choices=SORT_BY_CHOICES,
        initial='revenue_desc',
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('Sort By')
    )

    min_quantity = forms.IntegerField(
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': _('Minimum Quantity Sold')
        }),
        label=_('Minimum Quantity')
    )

    top_n = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=1000,
        initial=50,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': _('Number of Products to Show')
        }),
        label=_('Show Top N Products')
    )


class SavedReportForm(forms.ModelForm):
    """Form for creating and editing saved reports."""

    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Optional description for this report'
        }),
        label=_('Description')
    )

    class Meta:
        model = SavedReport
        fields = ['name', 'report_type', 'description', 'is_shared']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter report name'
            }),
            'report_type': forms.Select(attrs={
                'class': 'form-select'
            }),
            'is_shared': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set default empty values for JSON fields if creating new report
        if not self.instance.pk:
            self.instance.columns = []
            self.instance.filters = {}
            self.instance.parameters = {}

    def save(self, commit=True):
        instance = super().save(commit=False)

        # Ensure JSON fields have valid defaults
        if not instance.columns:
            instance.columns = []
        if not instance.filters:
            instance.filters = {}
        if not instance.parameters:
            instance.parameters = {}

        if commit:
            instance.save()
        return instance


class ReportScheduleForm(forms.ModelForm):
    """Form for scheduling reports."""

    class Meta:
        model = ReportSchedule
        fields = [
            'report', 'frequency', 'day_of_week', 'day_of_month', 'time_of_day',
            'recipients', 'cc_recipients', 'format', 'is_active', 'include_efris',
            'efris_report_format'
        ]
        widgets = {
            'report': forms.Select(attrs={'class': 'form-select'}),
            'frequency': forms.Select(attrs={'class': 'form-select'}),
            'day_of_week': forms.Select(attrs={'class': 'form-select'}),
            'day_of_month': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 31}),
            'time_of_day': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
            'format': forms.Select(attrs={'class': 'form-select'}),
            'recipients': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'email1@example.com, email2@example.com'
            }),
            'cc_recipients': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'cc1@example.com, cc2@example.com'
            }),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'include_efris': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'efris_report_format': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if user:
            # Filter reports based on user permissions
            if user.is_superuser or (user.primary_role and user.primary_role.priority >= 90):
                self.fields['report'].queryset = SavedReport.objects.all()
            else:
                self.fields['report'].queryset = SavedReport.objects.filter(
                    Q(created_by=user) | Q(is_shared=True)
                )

        # Set default time if not set
        if not self.instance.pk:
            import datetime
            self.fields['time_of_day'].initial = datetime.time(9, 0)  # 9:00 AM default

        # Make certain fields optional
        self.fields['day_of_week'].required = False
        self.fields['day_of_month'].required = False
        self.fields['cc_recipients'].required = False
        self.fields['efris_report_format'].required = False

    def clean_recipients(self):
        recipients = self.cleaned_data.get('recipients', '')
        if recipients:
            emails = [email.strip() for email in recipients.split(',') if email.strip()]
            for email in emails:
                try:
                    forms.EmailField().clean(email)
                except forms.ValidationError:
                    raise forms.ValidationError(f'Invalid email address: {email}')
            return ', '.join(emails)
        return recipients

    def clean_cc_recipients(self):
        cc_recipients = self.cleaned_data.get('cc_recipients', '')
        if cc_recipients:
            emails = [email.strip() for email in cc_recipients.split(',') if email.strip()]
            for email in emails:
                try:
                    forms.EmailField().clean(email)
                except forms.ValidationError:
                    raise forms.ValidationError(f'Invalid email address: {email}')
            return ', '.join(emails)
        return cc_recipients

    def clean(self):
        cleaned_data = super().clean()
        frequency = cleaned_data.get('frequency')
        day_of_week = cleaned_data.get('day_of_week')
        day_of_month = cleaned_data.get('day_of_month')

        if frequency == 'WEEKLY' and day_of_week is None:
            raise forms.ValidationError(_('Day of week is required for weekly frequency.'))

        if frequency == 'MONTHLY' and day_of_month is None:
            raise forms.ValidationError(_('Day of month is required for monthly frequency.'))

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)

        # Calculate next scheduled run
        if commit:
            instance.save()
            instance.calculate_next_run()

        return instance


class ReportExportForm(forms.Form):
    """Form for configuring report exports."""
    format = forms.ChoiceField(
        choices=ReportSchedule.FORMAT_CHOICES,
        initial='PDF',
        widget=forms.Select(attrs={'class': 'form-select'}),
        label=_('Export Format')
    )

    include_charts = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label=_('Include Charts')
    )

    include_summary = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label=_('Include Summary Statistics')
    )

    email_report = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label=_('Email Report')
    )

    email_recipients = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('Enter email addresses separated by commas')
        }),
        label=_('Email Recipients')
    )

    def clean_email_recipients(self):
        email_report = self.cleaned_data.get('email_report')
        email_recipients = self.cleaned_data.get('email_recipients', '')

        if email_report and not email_recipients:
            raise forms.ValidationError(_('Email recipients are required when emailing report.'))

        if email_recipients:
            emails = [email.strip() for email in email_recipients.split(',') if email.strip()]
            for email in emails:
                try:
                    forms.EmailField().clean(email)
                except forms.ValidationError:
                    raise forms.ValidationError(f'Invalid email address: {email}')
            return ', '.join(emails)
        return email_recipients


class ReportComparisonForm(forms.ModelForm):
    """Form for creating and editing report comparisons."""
    class Meta:
        model = ReportComparison
        fields = ['name', 'report', 'base_period', 'compare_period', 'metrics']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'report': forms.Select(attrs={'class': 'form-select'}),
            'base_period': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': _('JSON format: {"start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"}')
            }),
            'compare_period': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': _('JSON format: {"start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"}')
            }),
            'metrics': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': _('JSON format: ["metric1", "metric2"]')
            }),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if user:
            if user.is_superuser or (user.primary_role and user.primary_role.priority >= 90):
                self.fields['report'].queryset = SavedReport.objects.all()
            else:
                self.fields['report'].queryset = SavedReport.objects.filter(
                    Q(created_by=user) | Q(is_shared=True)
                )

    def clean_base_period(self):
        base_period = self.cleaned_data.get('base_period')
        if base_period:
            try:
                import json
                parsed = json.loads(base_period)
                if not isinstance(parsed, dict):
                    raise forms.ValidationError(_('Base period must be a JSON object.'))
                required_keys = ['start_date', 'end_date']
                if not all(key in parsed for key in required_keys):
                    raise forms.ValidationError(_('Base period must include start_date and end_date.'))
                # Validate date format
                for date_field in ['start_date', 'end_date']:
                    try:
                        datetime.strptime(parsed[date_field], '%Y-%m-%d')
                    except ValueError:
                        raise forms.ValidationError(_(f'Invalid date format for {date_field}. Use YYYY-MM-DD.'))
                if parsed['start_date'] > parsed['end_date']:
                    raise forms.ValidationError(_('Base period start date must be before end date.'))
                return parsed
            except json.JSONDecodeError:
                raise forms.ValidationError(_('Invalid JSON format for base period.'))
        return {}

    def clean_compare_period(self):
        compare_period = self.cleaned_data.get('compare_period')
        if compare_period:
            try:
                import json
                parsed = json.loads(compare_period)
                if not isinstance(parsed, dict):
                    raise forms.ValidationError(_('Compare period must be a JSON object.'))
                required_keys = ['start_date', 'end_date']
                if not all(key in parsed for key in required_keys):
                    raise forms.ValidationError(_('Compare period must include start_date and end_date.'))
                for date_field in ['start_date', 'end_date']:
                    try:
                        datetime.strptime(parsed[date_field], '%Y-%m-%d')
                    except ValueError:
                        raise forms.ValidationError(_(f'Invalid date format for {date_field}. Use YYYY-MM-DD.'))
                if parsed['start_date'] > parsed['end_date']:
                    raise forms.ValidationError(_('Compare period start date must be before end date.'))
                return parsed
            except json.JSONDecodeError:
                raise forms.ValidationError(_('Invalid JSON format for compare period.'))
        return {}

    def clean_metrics(self):
        metrics = self.cleaned_data.get('metrics')
        if metrics:
            try:
                import json
                parsed = json.loads(metrics)
                if not isinstance(parsed, list):
                    raise forms.ValidationError(_('Metrics must be a JSON array.'))
                return parsed
            except json.JSONDecodeError:
                raise forms.ValidationError(_('Invalid JSON format for metrics.'))
        return []


class EFRISReportTemplateForm(forms.ModelForm):
    """Form for managing EFRIS report templates."""
    class Meta:
        model = EFRISReportTemplate
        fields = [
            'name', 'report_type', 'template_file', 'is_default',
            'version', 'valid_from', 'valid_to', 'description',
            'is_active', 'ura_approved'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'report_type': forms.Select(attrs={'class': 'form-select'}),
            'template_file': forms.FileInput(attrs={'class': 'form-control'}),
            'is_default': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'version': forms.TextInput(attrs={'class': 'form-control'}),
            'valid_from': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'valid_to': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'ura_approved': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        valid_from = cleaned_data.get('valid_from')
        valid_to = cleaned_data.get('valid_to')

        if valid_from and valid_to and valid_from > valid_to:
            raise forms.ValidationError(_('Valid from date must be before valid to date.'))

        return cleaned_data