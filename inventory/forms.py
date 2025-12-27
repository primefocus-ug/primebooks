from django.contrib.auth import get_user_model
from django.core.validators import FileExtensionValidator
from django import forms
from django.core.exceptions import ValidationError
from decimal import Decimal
from django.utils import timezone
from .models import Category, Supplier, Product, Stock, StockMovement,Service
from stores.models import Store
from company.models import EFRISCommodityCategory
from django.utils.translation import gettext_lazy as _
import logging
from django.forms import inlineformset_factory
from stores.models import StockStore
from .models import (
     StockTransferRequest, StockTransferItem,
    StockStoreInventory
)
from stores.models import Store

User = get_user_model()
logger = logging.getLogger(__name__)

class VATAwareFormMixin:
    """
    Form mixin to handle VAT-aware tax rate selection and validation
    """

    def __init__(self, *args, **kwargs):
        # Extract company context
        self.company = kwargs.pop('company', None)
        self.is_vat_enabled = getattr(self.company, 'is_vat_enabled', True) if self.company else True

        super().__init__(*args, **kwargs)

        # Apply VAT restrictions to tax_rate field if it exists
        if 'tax_rate' in self.fields and not self.is_vat_enabled:
            # Force tax rate to 'B' and make field read-only (not disabled)
            self.fields['tax_rate'].choices = [('B', 'Zero rate (0%)')]
            self.fields['tax_rate'].initial = 'B'
            self.fields['tax_rate'].required = False  # Make it not required since we're setting it
            self.fields['tax_rate'].widget.attrs.update({
                'readonly': True,  # Use readonly instead of disabled
                'class': 'form-control dre'
            })
            self.fields['tax_rate'].help_text = "VAT is disabled for your company. Only zero rate is available."

        # Also handle excise_duty_rate field
        if 'excise_duty_rate' in self.fields and not self.is_vat_enabled:
            self.fields['excise_duty_rate'].initial = 0
            self.fields['excise_duty_rate'].required = False  # Make it not required
            self.fields['excise_duty_rate'].widget.attrs.update({
                'readonly': True,  # Use readonly instead of disabled
                'class': 'form-control dre'
            })
            self.fields['excise_duty_rate'].help_text = "Excise duty not applicable when VAT is disabled."

    def clean_tax_rate(self):
        """Ensure tax rate is 'B' when VAT is disabled"""
        tax_rate = self.cleaned_data.get('tax_rate')

        if not self.is_vat_enabled:
            # Force tax rate to 'B' when VAT is disabled
            return 'B'

        return tax_rate

    def clean_excise_duty_rate(self):
        """Ensure excise duty is 0 when VAT is disabled"""
        excise_rate = self.cleaned_data.get('excise_duty_rate')

        if not self.is_vat_enabled:
            # Force excise duty to 0 when VAT is disabled
            return 0

        return excise_rate or 0

class ServiceForm(VATAwareFormMixin,forms.ModelForm):
    """
    Form for creating and updating services with EFRIS integration.
    Includes real-time validation and autocomplete for EFRIS categories.
    """

    # Override category field with custom widget
    category = forms.ModelChoiceField(
        queryset=Category.objects.filter(category_type='service', is_active=True),
        required=True,
        empty_label="-- Select Service Category --",
        widget=forms.Select(attrs={
            'class': 'form-select',
            'data-live-search': 'true',
            'id': 'id_category',
        }),
        label=_("Service Category"),
        help_text=_("Select a service category. Only leaf node EFRIS categories are allowed.")
    )

    class Meta:
        model = Service
        fields = [
            'name', 'code', 'category', 'description',
            'unit_price',
            'tax_rate', 'excise_duty_rate',
            'unit_of_measure', 'image',
            'efris_auto_sync_enabled', 'is_active'
        ]

        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., Software Development, Consulting',
                'required': True,
            }),
            'code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., SRV001, DEV-001',
                'required': True,
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Detailed description of the service...',
            }),
            'unit_price': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'placeholder': '0.00',
                'required': True,
            }),
            'tax_rate': forms.Select(attrs={
                'class': 'form-select',
            }),
            'excise_duty_rate': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'value': '0',
            }),
            'unit_of_measure': forms.Select(attrs={
                'class': 'form-select',
                'data-live-search': 'true',
            }),
            'image': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*',
            }),
            'efris_auto_sync_enabled': forms.CheckboxInput(attrs={
                'class': 'form-check-input efris-only',  # Added efris-only class
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
            }),
        }

        labels = {
            'name': _('Service Name'),
            'code': _('Service Code'),
            'category': _('Service Category'),
            'description': _('Description'),
            'unit_price': _('Unit Price (UGX)'),
            'tax_rate': _('Tax Rate'),
            'excise_duty_rate': _('Excise Duty Rate %'),
            'unit_of_measure': _('Unit of Measure'),
            'image': _('Service Image'),
            'efris_auto_sync_enabled': _('Enable EFRIS Auto-Sync'),
            'is_active': _('Active'),
        }

        help_texts = {
            'code': _('Unique identifier for this service'),
            'unit_price': _('Price per unit of service'),
            'excise_duty_rate': _('Only applicable if tax rate is E'),
            'unit_of_measure': _('Unit for measuring this service (e.g., Hours, Sessions)'),
            'efris_auto_sync_enabled': _('Automatically sync changes to EFRIS'),
        }

    def __init__(self, *args, **kwargs):
        # Extract EFRIS status from kwargs
        self.efris_enabled = kwargs.pop('efris_enabled', False)

        # Call VATAwareFormMixin first, then ServiceForm
        super().__init__(*args, **kwargs)

        # Set default values for new instances only
        if not self.instance.pk:
            self.fields['is_active'].initial = True
            self.fields['efris_auto_sync_enabled'].initial = False
            self.fields['excise_duty_rate'].initial = 0
            self.fields['unit_of_measure'].initial = '207'  # Hours

            # Set default tax rate based on VAT status
            if not self.is_vat_enabled:
                self.fields['tax_rate'].initial = 'B'

        # ===== EFRIS CONDITIONAL LOGIC =====
        if not self.efris_enabled:
            # Hide EFRIS-specific fields
            efris_fields = ['efris_auto_sync_enabled']

            for field_name in efris_fields:
                if field_name in self.fields:
                    self.fields[field_name].widget = forms.HiddenInput()
                    self.fields[field_name].required = False
                    self.fields[field_name].initial = False

            # Update category help text for non-EFRIS mode
            self.fields['category'].help_text = _("Select a service category")
            self.fields['category'].required = False  # Category optional without EFRIS
        else:
            # EFRIS is enabled - make category REQUIRED
            self.fields['category'].required = True
            self.fields['category'].help_text = _(
                "Service category is required for EFRIS compliance. "
                "Select a category with an assigned EFRIS commodity category (leaf nodes only)."
            )

        # Add CSS classes to all fields
        for field_name, field in self.fields.items():
            if field_name not in ['efris_auto_sync_enabled', 'is_active']:
                if 'class' not in field.widget.attrs:
                    field.widget.attrs['class'] = 'form-control'

    def clean(self):
        """Additional cross-field validation with VAT awareness"""
        cleaned_data = super().clean()
        efris_auto_sync = cleaned_data.get('efris_auto_sync_enabled')
        category = cleaned_data.get('category')
        tax_rate = cleaned_data.get('tax_rate')

        # VAT ENFORCEMENT: Ensure tax rate is B when VAT disabled
        if not self.is_vat_enabled and tax_rate != 'B':
            self.add_error('tax_rate', "Only zero rate (B) is allowed when VAT is disabled.")

        # ===== EFRIS VALIDATION (only if EFRIS enabled) =====
        if self.efris_enabled and efris_auto_sync:
            if not category:
                raise ValidationError({
                    'efris_auto_sync_enabled': 'Please select a category before enabling EFRIS auto-sync.'
                })

            if not hasattr(category, 'efris_commodity_category_code') or not category.efris_commodity_category_code:
                raise ValidationError({
                    'efris_auto_sync_enabled': (
                        f"Category '{category.name}' must have an EFRIS commodity category assigned "
                        f"before enabling EFRIS sync. Please update the category first or disable auto-sync."
                    )
                })

        # If EFRIS is disabled, force efris_auto_sync to False
        if not self.efris_enabled:
            cleaned_data['efris_auto_sync_enabled'] = False

        # Ensure required fields are present
        required_fields = ['name', 'code', 'unit_price', 'tax_rate', 'unit_of_measure']

        # Add category to required fields if EFRIS is enabled
        if self.efris_enabled:
            required_fields.append('category')

        for field in required_fields:
            if not cleaned_data.get(field):
                self.add_error(field, _("This field is required"))

        return cleaned_data

    def clean_category(self):
        """Validate category is a service category with valid EFRIS settings (if EFRIS enabled)"""
        category = self.cleaned_data.get('category')

        # If EFRIS is disabled, category is optional - skip validation
        if not self.efris_enabled:
            return category

        # EFRIS is enabled - category is REQUIRED
        if not category:
            raise ValidationError(_("Service category is required when EFRIS is enabled."))

        # Validate it's a service category
        if category.category_type != 'service':
            raise ValidationError(
                _("Selected category is not a service category. "
                  "Please select a service category.")
            )

        # Validate EFRIS commodity category exists
        if not category.efris_commodity_category_code:
            raise ValidationError(
                _("Selected category does not have an EFRIS commodity category assigned. "
                  "Please update the category settings first or select a different category.")
            )

        # Validate it's a leaf node
        if not category.efris_is_leaf_node:
            raise ValidationError(
                _("Selected category's EFRIS commodity category is not a leaf node. "
                  "Only leaf nodes (terminal categories) can be used for services.")
            )

        return category

    def clean_unit_price(self):
        """Validate unit price is positive"""
        unit_price = self.cleaned_data.get('unit_price')

        if unit_price is not None and unit_price < 0:
            raise ValidationError(_("Unit price cannot be negative"))

        return unit_price

    def clean_excise_duty_rate(self):
        """Validate excise duty rate"""
        excise_rate = self.cleaned_data.get('excise_duty_rate')
        tax_rate = self.cleaned_data.get('tax_rate')

        if excise_rate and excise_rate > 0:
            if tax_rate != 'E':
                raise ValidationError(
                    _("Excise duty rate can only be set when tax rate is 'E' (Excise Duty rate)")
                )

        return excise_rate


    def save(self, commit=True):
        """Override save to handle EFRIS logic and VAT enforcement"""
        service = super().save(commit=False)

        # Set EFRIS enabled flag for validation
        service._efris_enabled = self.efris_enabled

        # Force VAT compliance
        if not self.is_vat_enabled:
            service.tax_rate = 'B'
            service.excise_duty_rate = 0

        # If EFRIS is disabled, ensure EFRIS fields are cleared
        if not self.efris_enabled:
            service.efris_auto_sync_enabled = False

        if commit:
            service.save()
            self.save_m2m()

        return service


class ServiceQuickCreateForm(VATAwareFormMixin, forms.ModelForm):
    """
    Simplified form for quick service creation via AJAX with VAT enforcement.
    """

    class Meta:
        model = Service
        fields = ['name', 'code', 'category', 'unit_price', 'tax_rate', 'unit_of_measure']

        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Service Name',
                'required': True,
            }),
            'code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Service Code',
                'required': True,
            }),
            'category': forms.Select(attrs={
                'class': 'form-select',
                'required': True,
            }),
            'unit_price': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': '0.00',
                'step': '0.01',
                'min': '0',
                'required': True,
            }),
            'tax_rate': forms.Select(attrs={
                'class': 'form-select',
            }),
            'unit_of_measure': forms.Select(attrs={
                'class': 'form-select',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only show service categories
        self.fields['category'].queryset = Category.objects.filter(
            category_type='service',
            is_active=True
        )

        # Set default tax rate based on VAT status for new instances
        if not self.instance.pk and not self.is_vat_enabled:
            self.fields['tax_rate'].initial = 'B'

    def clean_code(self):
        """Validate service code is unique"""
        code = self.cleaned_data.get('code')
        if Service.objects.filter(code=code).exists():
            raise ValidationError(_("Service with this code already exists"))
        return code


class ServiceFilterForm(forms.Form):
    """
    Form for filtering services in list view.
    """

    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search services...',
        })
    )

    category = forms.ModelChoiceField(
        queryset=Category.objects.filter(category_type='service', is_active=True),
        required=False,
        empty_label="All Categories",
        widget=forms.Select(attrs={
            'class': 'form-select',
        })
    )

    tax_rate = forms.ChoiceField(
        required=False,
        choices=[('', 'All Tax Rates')] + Service.TAX_RATE_CHOICES,
        widget=forms.Select(attrs={
            'class': 'form-select',
        })
    )

    efris_status = forms.ChoiceField(
        required=False,
        choices=[
            ('', 'All EFRIS Status'),
            ('uploaded', 'Uploaded to EFRIS'),
            ('pending', 'Pending Upload'),
            ('disabled', 'Sync Disabled'),
        ],
        widget=forms.Select(attrs={
            'class': 'form-select',
        })
    )

    is_active = forms.ChoiceField(
        required=False,
        choices=[
            ('', 'All Status'),
            ('true', 'Active'),
            ('false', 'Inactive'),
        ],
        widget=forms.Select(attrs={
            'class': 'form-select',
        })
    )


class ServiceBulkActionForm(forms.Form):
    """
    Form for bulk actions on services.
    """

    ACTION_CHOICES = [
        ('', '-- Select Action --'),
        ('activate', 'Activate Selected'),
        ('deactivate', 'Deactivate Selected'),
        ('enable_efris', 'Enable EFRIS Sync'),
        ('disable_efris', 'Disable EFRIS Sync'),
        ('mark_for_upload', 'Mark for EFRIS Upload'),
        ('delete', 'Delete Selected'),
    ]

    action = forms.ChoiceField(
        choices=ACTION_CHOICES,
        required=True,
        widget=forms.Select(attrs={
            'class': 'form-select',
        })
    )

    service_ids = forms.CharField(
        widget=forms.HiddenInput(),
        required=True,
    )

    def clean_service_ids(self):
        """Convert comma-separated IDs to list"""
        ids_str = self.cleaned_data.get('service_ids', '')
        try:
            ids = [int(id.strip()) for id in ids_str.split(',') if id.strip()]
            if not ids:
                raise ValidationError(_("No services selected"))
            return ids
        except ValueError:
            raise ValidationError(_("Invalid service IDs"))


class CategoryForm(forms.ModelForm):
    efris_commodity_category = forms.ModelChoiceField(
        queryset=EFRISCommodityCategory.objects.all(),
        required=False,
        widget=forms.HiddenInput(),  # Hidden since we're using custom JS selector
        label='EFRIS Commodity Category',
        help_text='Search and select the official EFRIS commodity category'
    )
    
    # ADD THIS: Hidden field to receive the code from JavaScript
    efris_commodity_category_code = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
        label='EFRIS Commodity Category Code'
    )

    class Meta:
        model = Category
        fields = [
            'category_type', 'name', 'code', 'description',
            'efris_commodity_category_code',  # Add this
            'efris_auto_sync', 'is_active'
        ]
        widgets = {
            'category_type': forms.Select(attrs={
                'class': 'form-control',
                'id': 'category-type-select'
            }),
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Category name'
            }),
            'code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Short code (optional)'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Category description'
            }),
            'efris_auto_sync': forms.CheckboxInput(attrs={
                'class': 'form-check-input efris-only'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }

    def __init__(self, *args, **kwargs):
        self.efris_enabled = kwargs.pop('efris_enabled', False)
        request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)

        # Set category type choices
        self.fields['category_type'].choices = Category.CATEGORY_TYPE_CHOICES

        # Initialize with current EFRIS code if editing
        if self.instance and self.instance.pk and self.instance.efris_commodity_category_code:
            self.fields['efris_commodity_category_code'].initial = self.instance.efris_commodity_category_code
            
            # Also set the ModelChoiceField initial value
            try:
                efris_cat = EFRISCommodityCategory.objects.get(
                    commodity_category_code=self.instance.efris_commodity_category_code
                )
                self.fields['efris_commodity_category'].initial = efris_cat
            except EFRISCommodityCategory.DoesNotExist:
                pass

        # Handle EFRIS disabled state
        if not self.efris_enabled:
            efris_fields = ['efris_commodity_category', 'efris_commodity_category_code', 'efris_auto_sync']
            for field_name in efris_fields:
                if field_name in self.fields:
                    self.fields[field_name].required = False
                    if field_name == 'efris_auto_sync':
                        self.fields[field_name].initial = False

    def _filter_efris_categories_by_type(self, category_type):
        """Filter EFRIS categories based on category type (product/service)"""
        if category_type and self.efris_enabled:
            from company.models import EFRISCommodityCategory

            # Determine service_mark value based on category_type
            service_mark_value = '101' if category_type == 'service' else '102'

            # Filter EFRIS categories by service_mark and leaf nodes only
            self.fields['efris_commodity_category'].queryset = (
                EFRISCommodityCategory.objects.filter(
                    service_mark=service_mark_value,
                    is_leaf_node='101'  # Only leaf nodes
                ).order_by('commodity_category_name')
            )

    def clean(self):
        cleaned_data = super().clean()
        efris_auto_sync = cleaned_data.get('efris_auto_sync')
        efris_code = cleaned_data.get('efris_commodity_category_code')
        category_type = cleaned_data.get('category_type')

        # Validate EFRIS fields if enabled
        if self.efris_enabled and efris_auto_sync:
            if not efris_code:
                raise ValidationError({
                    'efris_commodity_category_code': 'Please select an EFRIS commodity category before enabling auto-sync.'
                })

            # Validate the EFRIS category exists and matches type
            try:
                efris_cat = EFRISCommodityCategory.objects.get(
                    commodity_category_code=efris_code
                )
                
                # Validate category type matches
                efris_type = 'service' if efris_cat.service_mark == '101' else 'product'
                if category_type != efris_type:
                    raise ValidationError({
                        'efris_commodity_category_code':
                            f'Selected EFRIS category is for {efris_type}s, but you selected {category_type} category type. '
                            f'They must match.'
                    })

                # Validate it's a leaf node
                if efris_cat.is_leaf_node != '101':
                    raise ValidationError({
                        'efris_commodity_category_code':
                            'Selected EFRIS category is not a leaf node. Only terminal categories can be used.'
                    })
                    
            except EFRISCommodityCategory.DoesNotExist:
                raise ValidationError({
                    'efris_commodity_category_code': 'Invalid EFRIS commodity category code.'
                })

        # If EFRIS disabled, clear values
        if not self.efris_enabled:
            cleaned_data['efris_auto_sync'] = False
            cleaned_data['efris_commodity_category_code'] = None

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)

        # Set the efris_commodity_category_code from cleaned data
        efris_code = self.cleaned_data.get('efris_commodity_category_code')
        if efris_code:
            instance.efris_commodity_category_code = efris_code
        else:
            instance.efris_commodity_category_code = None

        # Disable EFRIS sync if not enabled
        if not self.efris_enabled:
            instance.efris_auto_sync = False

        if commit:
            instance.save()

        return instance



class QuickCategoryForm(forms.ModelForm):
    """
    Simplified form for quick category creation (e.g., in modals)
    """

    class Meta:
        model = Category
        fields = ['name', 'category_type']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Category name',
                'required': True,
            }),
            'category_type': forms.Select(attrs={
                'class': 'form-select',
                'required': True,
            }),
        }

class CattegoryForm(forms.ModelForm):
    efris_commodity_category = forms.ModelChoiceField(
        queryset=EFRISCommodityCategory.objects.all(),
        required=False,
        widget=forms.Select(attrs={
            'class': 'form-control efris-category-select',
            'data-ajax-url': '/inventory/api/efris-categories/search/'
        }),
        label='EFRIS Commodity Category',
        help_text='Search and select the official EFRIS commodity category'
    )

    class Meta:
        model = Category
        fields = [
            'name', 'code', 'description',
            'efris_commodity_category',
            'efris_auto_sync', 'is_active'
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Category name'
            }),
            'code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Short code (optional)'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Category description'
            }),
            'efris_auto_sync': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter by company if available
        request = kwargs.get('request')
        if request and hasattr(request, 'user') and hasattr(request.user, 'company'):
            self.fields['efris_commodity_category'].queryset = (
                EFRISCommodityCategory.objects.filter(company=request.user.company)
            )


class StockManagementForm(forms.ModelForm):
    """Enhanced form for comprehensive stock management"""

    class Meta:
        model = Stock
        fields = [
            'product', 'store', 'quantity', 'low_stock_threshold',
            'reorder_quantity', 'last_physical_count_quantity'
        ]
        widgets = {
            'product': forms.Select(attrs={
                'class': 'form-control',
                'data-live-search': 'true'
            }),
            'store': forms.Select(attrs={
                'class': 'form-control'
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.001',
                'min': '0'
            }),
            'low_stock_threshold': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.001',
                'min': '0',
                'help_text': 'Alert when stock falls below this level'
            }),
            'reorder_quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.001',
                'min': '0',
                'help_text': 'Recommended quantity to order when restocking'
            }),
            'last_physical_count_quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.001',
                'min': '0',
                'readonly': True,
                'help_text': 'Last recorded physical count'
            })
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['product'].queryset = Product.objects.filter(is_active=True).select_related('category')
        self.fields['store'].queryset = Store.objects.filter(is_active=True)

        # Add labels and help text
        self.fields['low_stock_threshold'].help_text = 'System will alert when stock falls below this level'
        self.fields['reorder_quantity'].help_text = 'Suggested quantity to reorder when restocking'

    def clean(self):
        cleaned_data = super().clean()
        quantity = cleaned_data.get('quantity')
        low_stock_threshold = cleaned_data.get('low_stock_threshold')
        reorder_quantity = cleaned_data.get('reorder_quantity')

        # Validation logic
        if low_stock_threshold and reorder_quantity:
            if low_stock_threshold > reorder_quantity:
                raise ValidationError(
                    "Low stock threshold should not be higher than reorder quantity"
                )

        return cleaned_data


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = [
            'name', 'tin', 'contact_person', 'phone', 'email',
            'address', 'country', 'is_active'
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Supplier name'
            }),
            'tin': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Tax Identification Number'
            }),
            'contact_person': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Contact person name'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Phone number'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'Email address'
            }),
            'address': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Physical address'
            }),
            'country': forms.TextInput(attrs={
                'class': 'form-control',
                'value': 'Uganda'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if phone and not phone.replace('+', '').replace('-', '').replace(' ', '').isdigit():
            raise ValidationError("Please enter a valid phone number.")
        return phone


class ProductForm(VATAwareFormMixin, forms.ModelForm):  # ADD VATAwareFormMixin here
    class Meta:
        model = Product
        fields = [
            'name', 'sku', 'barcode', 'description', 'category', 'supplier',
            'selling_price', 'cost_price', 'discount_percentage', 'tax_rate',
            'excise_duty_rate', 'unit_of_measure', 'min_stock_level',
            'is_active', 'image', 'efris_auto_sync_enabled', 'efris_excise_duty_code'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter product name'}),
            'sku': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter or generate SKU'}),
            'barcode': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Enter or generate barcode'}),
            'description': forms.Textarea(
                attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Enter product description'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'supplier': forms.Select(attrs={'class': 'form-select'}),
            'selling_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'cost_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'discount_percentage': forms.NumberInput(
                attrs={'class': 'form-control', 'step': '0.01', 'min': '0', 'max': '100', 'value': '0'}),
            'tax_rate': forms.Select(attrs={'class': 'form-select'}),
            'excise_duty_rate': forms.NumberInput(
                attrs={'class': 'form-control', 'step': '0.01', 'min': '0', 'value': '0'}),
            'unit_of_measure': forms.Select(attrs={'class': 'form-select'}),
            'min_stock_level': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'value': '5'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'image': forms.FileInput(attrs={'class': 'form-control'}),
            'efris_auto_sync_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input efris-only'}),
            'efris_excise_duty_code': forms.TextInput(
                attrs={'class': 'form-control efris-only', 'placeholder': 'Enter EFRIS excise duty code'}),
        }

    def __init__(self, *args, **kwargs):
        # Extract EFRIS status and company from kwargs
        self.efris_enabled = kwargs.pop('efris_enabled', False)

        # Call VATAwareFormMixin first, then ProductForm
        super().__init__(*args, **kwargs)

        # Set default values for new instances only
        if not self.instance.pk:  # New product
            self.fields['is_active'].initial = True
            self.fields['efris_auto_sync_enabled'].initial = False
            self.fields['discount_percentage'].initial = 0
            self.fields['excise_duty_rate'].initial = 0
            self.fields['min_stock_level'].initial = 5

        # ===== EFRIS CONDITIONAL LOGIC =====
        if not self.efris_enabled:
            # Hide EFRIS-specific fields
            efris_fields = [
                'efris_auto_sync_enabled',
                'efris_excise_duty_code',
            ]

            for field_name in efris_fields:
                if field_name in self.fields:
                    # Make field hidden and not required
                    self.fields[field_name].widget = forms.HiddenInput()
                    self.fields[field_name].required = False
                    # Set default value to False/empty
                    if field_name == 'efris_auto_sync_enabled':
                        self.fields[field_name].initial = False
        else:
            # Update help text for EFRIS fields when enabled
            if 'efris_auto_sync_enabled' in self.fields:
                self.fields['efris_auto_sync_enabled'].help_text = (
                    'Enable automatic synchronization with EFRIS system for tax compliance'
                )

            if 'efris_excise_duty_code' in self.fields:
                self.fields['efris_excise_duty_code'].help_text = (
                    'Enter the EFRIS excise duty code if applicable (required for excise duty products)'
                )

    def clean(self):
        cleaned_data = super().clean()
        category = cleaned_data.get('category')
        efris_auto_sync = cleaned_data.get('efris_auto_sync_enabled')
        cost_price = cleaned_data.get('cost_price')
        selling_price = cleaned_data.get('selling_price')
        tax_rate = cleaned_data.get('tax_rate')
        excise_duty_rate = cleaned_data.get('excise_duty_rate')


        # ===== EFRIS VALIDATION (only if EFRIS is enabled) =====
        if self.efris_enabled and efris_auto_sync:
            if not category:
                self.add_error('efris_auto_sync_enabled', 'Please select a category before enabling EFRIS auto-sync.')

            if category and (not hasattr(category,
                                         'efris_commodity_category_code') or not category.efris_commodity_category_code):
                self.add_error('efris_auto_sync_enabled',
                               f"Category '{category.name}' must have an EFRIS commodity category assigned before enabling EFRIS sync. Please update the category first or disable auto-sync.")

        # If EFRIS is disabled, force efris_auto_sync to False
        if not self.efris_enabled:
            cleaned_data['efris_auto_sync_enabled'] = False
            if 'efris_excise_duty_code' in cleaned_data:
                cleaned_data['efris_excise_duty_code'] = ''

        # Validate pricing
        if cost_price is not None and selling_price is not None:
            if cost_price > selling_price:
                self.add_error('selling_price', 'Selling price cannot be less than cost price.')

            if cost_price < 0:
                self.add_error('cost_price', 'Cost price must be a positive number.')

            if selling_price < 0:
                self.add_error('selling_price', 'Selling price must be a positive number.')

        return cleaned_data

    def clean_sku(self):
        """Ensure SKU is unique"""
        sku = self.cleaned_data.get('sku')
        if sku:
            sku = sku.strip().upper()
            queryset = Product.objects.filter(sku=sku)
            if self.instance.pk:
                queryset = queryset.exclude(pk=self.instance.pk)

            if queryset.exists():
                raise ValidationError(f'Product with SKU "{sku}" already exists.')

        return sku

    def clean_barcode(self):
        """Ensure barcode is unique if provided"""
        barcode = self.cleaned_data.get('barcode')
        if barcode:
            barcode = barcode.strip()
            queryset = Product.objects.filter(barcode=barcode)
            if self.instance.pk:
                queryset = queryset.exclude(pk=self.instance.pk)

            if queryset.exists():
                raise ValidationError(f'Product with barcode "{barcode}" already exists.')

        return barcode

    def clean_discount_percentage(self):
        """Validate discount percentage is within valid range"""
        discount = self.cleaned_data.get('discount_percentage')
        if discount is not None:
            if discount < 0 or discount > 100:
                raise ValidationError('Discount percentage must be between 0 and 100.')
        return discount or 0

    def save(self, commit=True):
        """Override save to handle EFRIS category inheritance and VAT enforcement"""
        product = super().save(commit=False)

        # Force VAT compliance - ensure tax rate is B when VAT disabled
        # This is now handled by the form validation, but we keep it here for safety
        if not self.is_vat_enabled:
            product.tax_rate = 'B'
            product.excise_duty_rate = 0

        # ===== EFRIS CATEGORY INHERITANCE (only if EFRIS enabled) =====
        if self.efris_enabled:
            if product.category and hasattr(product.category, 'efris_commodity_category_code'):
                pass
        else:
            # Clear EFRIS fields if disabled
            product.efris_auto_sync_enabled = False
            product.efris_excise_duty_code = ''

        if commit:
            product.save()
            self.save_m2m()

        return product
    
class StockForm(forms.ModelForm):
    """Form for creating and updating stock records"""
    
    class Meta:
        model = Stock
        fields = [
            'product',
            'store',
            'quantity',
            'low_stock_threshold',
            'reorder_quantity',
            'last_physical_count_quantity',
        ]
        widgets = {
            'product': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_product'
            }),
            'store': forms.Select(attrs={
                'class': 'form-select',
                'id': 'id_store'
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'id': 'id_quantity',
                'step': '0.001',
                'min': '0'
            }),
            'low_stock_threshold': forms.NumberInput(attrs={
                'class': 'form-control',
                'id': 'id_low_stock_threshold',
                'step': '0.001',
                'min': '0'
            }),
            'reorder_quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'id': 'id_reorder_quantity',
                'step': '0.001',
                'min': '0'
            }),
            'last_physical_count_quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'id': 'id_last_physical_count_quantity',
                'step': '0.001',
                'min': '0',
                'readonly': 'readonly'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Set queryset for product field
        self.fields['product'].queryset = Product.objects.filter(
            is_active=True
        ).select_related('category', 'supplier').order_by('name')
        
        # Set queryset for store field
        self.fields['store'].queryset = Store.objects.filter(
            is_active=True
        ).order_by('name')
        
        # Make last_physical_count_quantity read-only for display
        self.fields['last_physical_count_quantity'].required = False
        self.fields['last_physical_count_quantity'].disabled = True
        
        # Set help texts
        self.fields['quantity'].help_text = 'Current stock quantity'
        self.fields['low_stock_threshold'].help_text = 'Alert when stock falls below this level'
        self.fields['reorder_quantity'].help_text = 'Suggested reorder quantity'
        
        # If updating, make product and store read-only but NOT disabled
        if self.instance.pk:
            # Use readonly instead of disabled to ensure values are submitted
            self.fields['product'].widget.attrs['readonly'] = 'readonly'
            self.fields['product'].widget.attrs['onclick'] = 'return false;'
            self.fields['product'].widget.attrs['onkeydown'] = 'return false;'
            self.fields['product'].widget.attrs['style'] = 'pointer-events: none; background-color: #e9ecef;'
            
            self.fields['store'].widget.attrs['readonly'] = 'readonly'
            self.fields['store'].widget.attrs['onclick'] = 'return false;'
            self.fields['store'].widget.attrs['onkeydown'] = 'return false;'
            self.fields['store'].widget.attrs['style'] = 'pointer-events: none; background-color: #e9ecef;'
            
            self.fields['product'].help_text = '⚠️ Cannot change product for existing stock record'
            self.fields['store'].help_text = '⚠️ Cannot change store for existing stock record'

    def clean_product(self):
        """Ensure product field isn't changed on update"""
        if self.instance.pk:
            # Return the original product, not the submitted one
            return self.instance.product
        return self.cleaned_data.get('product')

    def clean_store(self):
        """Ensure store field isn't changed on update"""
        if self.instance.pk:
            # Return the original store, not the submitted one
            return self.instance.store
        return self.cleaned_data.get('store')

    def clean(self):
        cleaned_data = super().clean()
        product = cleaned_data.get('product')
        store = cleaned_data.get('store')
        quantity = cleaned_data.get('quantity')
        low_stock_threshold = cleaned_data.get('low_stock_threshold')
        reorder_quantity = cleaned_data.get('reorder_quantity')

        # Validate quantity
        if quantity is not None and quantity < 0:
            self.add_error('quantity', 'Quantity cannot be negative')

        # Validate thresholds
        if low_stock_threshold is not None and low_stock_threshold < 0:
            self.add_error('low_stock_threshold', 'Threshold cannot be negative')

        if reorder_quantity is not None and reorder_quantity < 0:
            self.add_error('reorder_quantity', 'Reorder quantity cannot be negative')

        # Check for duplicate (only on create, not on update)
        if not self.instance.pk and product and store:
            if Stock.objects.filter(product=product, store=store).exists():
                raise forms.ValidationError(
                    f'Stock record already exists for {product.name} at {store.name}. '
                    f'Please edit the existing record instead.'
                )

        return cleaned_data

class ProductCreateForm(ProductForm):
    """Simplified form for creating products - focuses on essential fields"""

    class Meta(ProductForm.Meta):
        fields = [
            'name', 'sku', 'barcode', 'description', 'category', 'supplier',
            'selling_price', 'cost_price', 'tax_rate', 'unit_of_measure',
            'min_stock_level', 'is_active'
            # REMOVED EFRIS fields - they're inherited from category
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Mark required fields
        self.fields['name'].required = True
        self.fields['sku'].required = True
        self.fields['category'].required = True  # Required for EFRIS
        self.fields['selling_price'].required = True
        self.fields['cost_price'].required = True

        # Set helpful defaults
        self.fields['tax_rate'].initial = 'A'  # Standard rate
        self.fields['unit_of_measure'].initial = 'each'
        self.fields['min_stock_level'].initial = 5


class ProductUpdateForm(ProductForm):
    """Full form for updating products - includes all fields including EFRIS"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Add readonly computed EFRIS fields as display
        if self.instance and self.instance.pk:
            # Show computed EFRIS values (read-only)
            efris_info = forms.CharField(
                required=False,
                widget=forms.TextInput(attrs={
                    'readonly': True,
                    'class': 'form-control-plaintext',
                }),
                help_text="Computed from category"
            )

            # Add display fields for computed EFRIS values
            self.fields['efris_commodity_category_display'] = forms.CharField(
                required=False,
                label='EFRIS Commodity Category',
                widget=forms.TextInput(attrs={
                    'readonly': True,
                    'class': 'form-control-plaintext',
                }),
                initial=f"{self.instance.efris_commodity_category_id} - {self.instance.efris_commodity_category_name}",
                help_text="Inherited from category"
            )

            self.fields['efris_tax_category_display'] = forms.CharField(
                required=False,
                label='EFRIS Tax Category',
                widget=forms.TextInput(attrs={
                    'readonly': True,
                    'class': 'form-control-plaintext',
                }),
                initial=f"{self.instance.efris_tax_category_id} ({self.instance.efris_tax_rate}%)",
                help_text="Auto-mapped from tax rate"
            )

            self.fields['efris_unit_measure_display'] = forms.CharField(
                required=False,
                label='EFRIS Unit of Measure',
                widget=forms.TextInput(attrs={
                    'readonly': True,
                    'class': 'form-control-plaintext',
                }),
                initial=self.instance.efris_unit_of_measure_code,
                help_text="Auto-mapped from unit of measure"
            )


class ProductBulkUpdateForm(forms.Form):
    """Form for bulk updating multiple products"""

    products = forms.ModelMultipleChoiceField(
        queryset=Product.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        required=True
    )

    # Fields that can be bulk updated
    category = forms.ModelChoiceField(
        queryset=Category.objects.filter(is_active=True),
        required=False,
        empty_label="Keep existing"
    )

    supplier = forms.ModelChoiceField(
        queryset=Supplier.objects.filter(is_active=True),
        required=False,
        empty_label="Keep existing"
    )

    tax_rate = forms.ChoiceField(
        choices=[('', 'Keep existing')] + Product.TAX_RATE_CHOICES,
        required=False
    )

    discount_percentage = forms.DecimalField(
        max_digits=5,
        decimal_places=2,
        required=False,
        min_value=0,
        max_value=100,
        help_text="Leave blank to keep existing"
    )

    is_active = forms.ChoiceField(
        choices=[
            ('', 'Keep existing'),
            (True, 'Active'),
            (False, 'Inactive')
        ],
        required=False
    )

    # EFRIS bulk actions
    efris_auto_sync_enabled = forms.ChoiceField(
        choices=[
            ('', 'Keep existing'),
            (True, 'Enable EFRIS sync'),
            (False, 'Disable EFRIS sync')
        ],
        required=False
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field_name, field in self.fields.items():
            if hasattr(field.widget, 'attrs'):
                field.widget.attrs.update({'class': 'form-control'})


class ProductImportForm(forms.Form):
    """Form for importing products from CSV/Excel"""

    file = forms.FileField(
        help_text="Upload CSV or Excel file with product data",
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': '.csv,.xlsx,.xls'
        })
    )

    update_existing = forms.BooleanField(
        required=False,
        initial=False,
        help_text="Update existing products if SKU matches",
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        })
    )

    create_categories = forms.BooleanField(
        required=False,
        initial=True,
        help_text="Create categories that don't exist",
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        })
    )

    create_suppliers = forms.BooleanField(
        required=False,
        initial=True,
        help_text="Create suppliers that don't exist",
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        })
    )

    def clean_file(self):
        file = self.cleaned_data.get('file')
        if file:
            # Check file size (max 5MB)
            if file.size > 5 * 1024 * 1024:
                raise ValidationError("File size cannot exceed 5MB")

            # Check file extension
            valid_extensions = ['.csv', '.xlsx', '.xls']
            if not any(file.name.lower().endswith(ext) for ext in valid_extensions):
                raise ValidationError("Only CSV and Excel files are allowed")

        return file

class StockMovementForm(forms.ModelForm):
    class Meta:
        model = StockMovement
        fields = [
            'product', 'store', 'movement_type', 'quantity',
            'reference', 'notes', 'unit_price'
        ]
        widgets = {
            'product': forms.Select(attrs={
                'class': 'form-control',
                'required': True
            }),
            'store': forms.Select(attrs={
                'class': 'form-control',
                'required': True
            }),
            'movement_type': forms.Select(attrs={
                'class': 'form-control',
                'required': True
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.001',
                'min': '0.001',
                'required': True
            }),
            'reference': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Reference number (optional)'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Additional notes (optional)'
            }),
            'unit_price': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0',
                'placeholder': 'Unit price (optional)'
            }),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        self.fields['product'].queryset = Product.objects.filter(is_active=True)
        self.fields['store'].queryset = Store.objects.filter(is_active=True)
        self.fields['product'].empty_label = "Select Product"
        self.fields['store'].empty_label = "Select Store"

    def clean(self):
        cleaned_data = super().clean()
        product = cleaned_data.get('product')
        store = cleaned_data.get('store')
        movement_type = cleaned_data.get('movement_type')
        quantity = cleaned_data.get('quantity')

        if product and store and movement_type and quantity:
            # Check stock availability for outbound movements
            if movement_type in ['SALE', 'TRANSFER_OUT']:
                try:
                    stock = Stock.objects.get(product=product, store=store)
                    if stock.quantity < quantity:
                        raise ValidationError(
                            f"Insufficient stock. Only {stock.quantity} {product.unit_of_measure} available."
                        )
                except Stock.DoesNotExist:
                    raise ValidationError(
                        "No stock record exists for this product in the selected store."
                    )

        return cleaned_data


class ProductFilterForm(forms.Form):
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search products by name, SKU, or barcode...'
        })
    )
    category = forms.ModelChoiceField(
        queryset=Category.objects.filter(is_active=True),
        required=False,
        empty_label="All Categories",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    supplier = forms.ModelChoiceField(
        queryset=Supplier.objects.filter(is_active=True),
        required=False,
        empty_label="All Suppliers",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    tax_rate = forms.ChoiceField(
        choices=[('', 'All Tax Rates')] + Product.TAX_RATE_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    is_active = forms.ChoiceField(
        choices=[('', 'All'), ('True', 'Active'), ('False', 'Inactive')],
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    min_price = forms.DecimalField(
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Min price',
            'step': '0.01'
        })
    )
    max_price = forms.DecimalField(
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Max price',
            'step': '0.01'
        })
    )

    # Stock level filters
    stock_status = forms.ChoiceField(
        choices=[
            ('', 'All Stock Levels'),
            ('in_stock', 'In Stock'),
            ('low_stock', 'Low Stock'),
            ('out_of_stock', 'Out of Stock'),
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    has_physical_count = forms.ChoiceField(
        choices=[
            ('', 'All Products'),
            ('yes', 'Has Physical Count'),
            ('no', 'No Physical Count')
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
        help_text='Filter by physical count status'
    )
    efris_sync_required = forms.ChoiceField(
        choices=[
            ('', 'All Products'),
            ('yes', 'Needs EFRIS Sync'),
            ('no', 'EFRIS Sync Up to Date')
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
        help_text='Filter by EFRIS sync status'
    )

    # EFRIS filters
    efris_sync_enabled = forms.ChoiceField(
        choices=[
            ('', 'All Products'),
            ('True', 'EFRIS Sync Enabled'),
            ('False', 'EFRIS Sync Disabled')
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    efris_upload_status = forms.ChoiceField(
        choices=[
            ('', 'All Upload Status'),
            ('uploaded', 'Uploaded to EFRIS'),
            ('pending', 'Pending Upload'),
            ('failed', 'Upload Failed')
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    def clean(self):
        cleaned_data = super().clean()
        min_price = cleaned_data.get('min_price')
        max_price = cleaned_data.get('max_price')

        if min_price and max_price and min_price > max_price:
            raise ValidationError("Minimum price cannot be greater than maximum price.")

        return cleaned_data


class PhysicalStockCountForm(forms.Form):
    """Form for recording physical stock counts"""

    product = forms.ModelChoiceField(
        queryset=Product.objects.filter(is_active=True),
        widget=forms.Select(attrs={
            'class': 'form-control',
            'required': True
        }),
        empty_label="Select Product"
    )

    store = forms.ModelChoiceField(
        queryset=Store.objects.filter(is_active=True),
        widget=forms.Select(attrs={
            'class': 'form-control',
            'required': True
        }),
        empty_label="Select Store"
    )

    counted_quantity = forms.DecimalField(
        max_digits=12,
        decimal_places=3,
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'step': '0.001',
            'min': '0',
            'required': True,
            'placeholder': 'Enter counted quantity'
        })
    )

    count_date = forms.DateTimeField(
        initial=timezone.now,
        widget=forms.DateTimeInput(attrs={
            'class': 'form-control',
            'type': 'datetime-local'
        })
    )

    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Notes about the physical count (optional)'
        })
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

    def save(self):
        """Process physical count and create adjustment if needed"""
        cleaned_data = self.cleaned_data
        product = cleaned_data['product']
        store = cleaned_data['store']
        counted_quantity = cleaned_data['counted_quantity']
        notes = cleaned_data.get('notes', '')

        # Get or create stock record
        stock, created = Stock.objects.get_or_create(
            product=product,
            store=store,
            defaults={'quantity': counted_quantity}
        )

        # Record physical count using the enhanced Stock model method
        stock.record_physical_count(counted_quantity, self.user)

        return stock


class StockAdjustmentForm(forms.Form):
    product = forms.ModelChoiceField(
        queryset=Product.objects.filter(is_active=True),
        widget=forms.Select(attrs={
            'class': 'form-control-enhanced',
            'required': True
        }),
        empty_label="Select Product"
    )
    store = forms.ModelChoiceField(
        queryset=Store.objects.filter(is_active=True),
        widget=forms.Select(attrs={
            'class': 'form-control-enhanced',
            'required': True
        }),
        empty_label="Select Store"
    )
    movement_type = forms.ChoiceField(
        choices=StockMovement.MOVEMENT_TYPES,
        widget=forms.Select(attrs={
            'class': 'form-control-enhanced',
            'required': True
        }),
        label="Movement Type"
    )
    quantity = forms.DecimalField(
        max_digits=15,
        decimal_places=3,
        widget=forms.NumberInput(attrs={
            'class': 'form-control-enhanced',
            'step': '0.001',
            'min': '0.001',
            'required': True,
            'placeholder': 'Enter quantity'
        }),
        label="Quantity *"
    )
    unit_price = forms.DecimalField(
        max_digits=15,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control-enhanced',
            'step': '0.01',
            'min': '0',
            'placeholder': 'Unit price (optional)'
        }),
        label="Unit Price"
    )
    reference = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control-enhanced',
            'placeholder': 'Reference number (optional)'
        }),
        label="Reference"
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control-enhanced',
            'rows': 3,
            'placeholder': 'Additional notes (optional)'
        }),
        label="Notes"
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Set initial reference if not provided
        if not self.initial.get('reference'):
            self.initial['reference'] = ''

    def clean_quantity(self):
        """Validate quantity based on movement type"""
        quantity = self.cleaned_data['quantity']
        movement_type = self.cleaned_data.get('movement_type')

        if quantity <= 0:
            raise forms.ValidationError("Quantity must be greater than zero.")

        # For sales/removals, check if sufficient stock exists
        if movement_type in ['SALE', 'ADJUSTMENT']:
            product = self.cleaned_data.get('product')
            store = self.cleaned_data.get('store')

            if product and store:
                try:
                    stock = Stock.objects.get(product=product, store=store)
                    if quantity > stock.quantity:
                        raise forms.ValidationError(
                            f"Insufficient stock. Available: {stock.quantity}"
                        )
                except Stock.DoesNotExist:
                    raise forms.ValidationError("No stock record found for this product and store.")

        return quantity

    def clean_unit_price(self):
        """Validate unit price"""
        unit_price = self.cleaned_data.get('unit_price')
        if unit_price and unit_price < 0:
            raise forms.ValidationError("Unit price cannot be negative.")
        return unit_price

    def save(self):
        """Create stock movement and update stock"""
        cleaned_data = self.cleaned_data
        product = cleaned_data['product']
        store = cleaned_data['store']
        movement_type = cleaned_data['movement_type']
        quantity = cleaned_data['quantity']
        unit_price = cleaned_data.get('unit_price')
        reference = cleaned_data.get('reference', '')
        notes = cleaned_data.get('notes', '')

        # Get or create stock record
        stock, created = Stock.objects.get_or_create(
            product=product,
            store=store,
            defaults={
                'quantity': Decimal('0'),
                'low_stock_threshold': Decimal('5'),
                'reorder_quantity': Decimal('10')
            }
        )

        old_quantity = stock.quantity

        # Calculate movement quantity and new stock level
        if movement_type in ['PURCHASE', 'RETURN', 'TRANSFER_IN']:
            # Positive movements (add to stock)
            movement_quantity = quantity
            new_quantity = old_quantity + quantity
        else:
            # Negative movements (remove from stock)
            movement_quantity = -quantity
            new_quantity = max(Decimal('0'), old_quantity - quantity)

        # Calculate total value if unit price is provided
        total_value = None
        if unit_price:
            total_value = unit_price * abs(movement_quantity)

        # Create stock movement
        movement = StockMovement.objects.create(
            product=product,
            store=store,
            movement_type=movement_type,
            quantity=movement_quantity,
            unit_price=unit_price,
            total_value=total_value,
            reference=reference or '',
            notes=notes,
            created_by=self.user
        )

        # Update stock quantity
        stock.quantity = new_quantity
        stock.last_updated = timezone.now()
        stock.save()

        # Log the adjustment
        logger.info(
            f"Stock adjustment by {self.user.username}: "
            f"{product.name} at {store.name} - "
            f"{movement_type}: {movement_quantity} (Old: {old_quantity}, New: {new_quantity})"
        )

        return movement

class BulkActionForm(forms.Form):
    action = forms.ChoiceField(
        choices=[
            ('', 'Select Action'),
            ('activate', 'Activate Selected'),
            ('deactivate', 'Deactivate Selected'),
            ('delete', 'Delete Selected'),
            ('export', 'Export Selected'),
        ],
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    selected_items = forms.CharField(
        widget=forms.HiddenInput()
    )

    def clean_selected_items(self):
        items = self.cleaned_data.get('selected_items', '')
        if not items:
            raise ValidationError("Please select items to perform the action.")

        try:
            item_ids = [int(x) for x in items.split(',') if x.strip()]
            if not item_ids:
                raise ValidationError("No valid items selected.")
            return item_ids
        except (ValueError, TypeError):
            raise ValidationError("Invalid item selection.")

    def clean(self):
        cleaned_data = super().clean()
        action = cleaned_data.get('action')
        items = cleaned_data.get('selected_items')

        if not action:
            raise ValidationError("Please select an action.")

        if not items:
            raise ValidationError("Please select items.")

        return cleaned_data


class BulkStockImportForm(forms.Form):
    """Enhanced form for bulk stock imports"""

    file = forms.FileField(
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': '.csv,.xlsx,.xls'
        }),
        help_text='Upload CSV or Excel file with stock data (max 10MB)'
    )

    update_existing = forms.BooleanField(
        required=False,
        initial=True,
        help_text='Update existing stock records',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    create_missing_products = forms.BooleanField(
        required=False,
        initial=False,
        help_text='Create products that don\'t exist',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    update_thresholds = forms.BooleanField(
        required=False,
        initial=True,
        help_text='Update low stock thresholds and reorder quantities',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    mark_efris_sync = forms.BooleanField(
        required=False,
        initial=False,
        help_text='Mark updated stock records for EFRIS sync',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    conflict_resolution = forms.ChoiceField(
        choices=[
            ('overwrite', 'Overwrite existing quantities'),
            ('add', 'Add to existing quantities'),
            ('skip', 'Skip existing records'),
        ],
        initial='overwrite',
        widget=forms.Select(attrs={'class': 'form-control'}),
        help_text='How to handle existing stock records'
    )

    def clean_file(self):
        file = self.cleaned_data.get('file')
        if file:
            # Check file size (max 10MB)
            if file.size > 10 * 1024 * 1024:
                raise ValidationError("File size cannot exceed 10MB")

            # Check file extension
            valid_extensions = ['.csv', '.xlsx', '.xls']
            if not any(file.name.lower().endswith(ext) for ext in valid_extensions):
                raise ValidationError("Only CSV and Excel files are allowed")

        return file


class StockReportFilterForm(forms.Form):
    """Form for filtering stock reports"""

    store = forms.ModelChoiceField(
        queryset=Store.objects.filter(is_active=True),
        required=False,
        empty_label="All Stores",
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    category = forms.ModelChoiceField(
        queryset=Category.objects.filter(is_active=True),
        required=False,
        empty_label="All Categories",
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    stock_status = forms.ChoiceField(
        choices=[
            ('', 'All Stock Levels'),
            ('out_of_stock', 'Out of Stock'),
            ('critical', 'Critical (Below 50% of threshold)'),
            ('low_stock', 'Low Stock (Below threshold)'),
            ('good_stock', 'Good Stock (Above threshold)'),
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    has_movements = forms.ChoiceField(
        choices=[
            ('', 'All Products'),
            ('recent', 'With Recent Movements (30 days)'),
            ('none', 'No Recent Movements'),
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    efris_sync_status = forms.ChoiceField(
        choices=[
            ('', 'All Records'),
            ('required', 'EFRIS Sync Required'),
            ('up_to_date', 'EFRIS Up to Date'),
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )

    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )

    def clean(self):
        cleaned_data = super().clean()
        date_from = cleaned_data.get('date_from')
        date_to = cleaned_data.get('date_to')

        if date_from and date_to and date_from > date_to:
            raise ValidationError("Start date must be before end date")

        return cleaned_data


class StockForm(forms.ModelForm):
    class Meta:
        model = Stock
        fields = ['product', 'store', 'quantity', 'low_stock_threshold', 'reorder_quantity']  # Updated field names
        widgets = {
            'product': forms.Select(attrs={
                'class': 'form-select',
                'data-placeholder': 'Select product'
            }),
            'store': forms.Select(attrs={
                'class': 'form-select',
                'data-placeholder': 'Select store'
            }),
            'quantity': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.001',
                'min': '0'
            }),
            'low_stock_threshold': forms.NumberInput(attrs={  # Updated field name
                'class': 'form-control',
                'step': '0.001',
                'min': '0'
            }),
            'reorder_quantity': forms.NumberInput(attrs={  # New field
                'class': 'form-control',
                'step': '0.001',
                'min': '0'
            })
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['product'].queryset = Product.objects.filter(is_active=True)


class BulkProductImportForm(forms.Form):
    csv_file = forms.FileField(
        validators=[FileExtensionValidator(allowed_extensions=['csv', 'xlsx', 'xls'])],
        help_text='Upload a CSV or Excel file containing product data (max 10MB)',
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': '.csv,.xlsx,.xls'
        })
    )

    update_existing = forms.BooleanField(
        required=False,
        initial=True,
        help_text='Update existing products when SKU matches',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    create_missing_categories = forms.BooleanField(
        required=False,
        initial=True,
        help_text='Automatically create categories that don\'t exist',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    create_missing_suppliers = forms.BooleanField(
        required=False,
        initial=True,
        help_text='Automatically create suppliers that don\'t exist',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    validate_prices = forms.BooleanField(
        required=False,
        initial=True,
        help_text='Validate that selling price >= cost price',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    enable_efris_sync = forms.BooleanField(
        required=False,
        initial=True,
        help_text='Enable EFRIS sync for imported products',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    def clean_csv_file(self):
        file = self.cleaned_data.get('csv_file')
        if file:
            # Check file size (max 10MB)
            if file.size > 10 * 1024 * 1024:
                raise ValidationError("File size cannot exceed 10MB")
        return file


class ImportMappingForm(forms.Form):
    """Form for handling column mapping during import"""
    IMPORT_MODE_CHOICES = [
        ('add', 'Add new products only'),
        ('update', 'Update existing products only'),
        ('both', 'Add new and update existing'),
    ]

    CONFLICT_RESOLUTION_CHOICES = [
        ('skip', 'Skip conflicting products'),
        ('overwrite', 'Overwrite with imported data'),
        ('merge', 'Merge stock quantities only'),
    ]

    import_mode = forms.ChoiceField(
        choices=IMPORT_MODE_CHOICES,
        initial='both',
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    conflict_resolution = forms.ChoiceField(
        choices=CONFLICT_RESOLUTION_CHOICES,
        initial='overwrite',
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    has_header = forms.BooleanField(
        required=False,
        initial=True,
        help_text='First row contains column headers',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    notify_on_completion = forms.BooleanField(
        required=False,
        initial=True,
        help_text='Send email notification when import completes',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    dry_run = forms.BooleanField(
        required=False,
        initial=False,
        help_text='Preview import without making changes',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    # Column mapping fields (dynamically added based on CSV headers)
    def __init__(self, *args, csv_headers=None, **kwargs):
        super().__init__(*args, **kwargs)

        if csv_headers:
            # Define available product fields for mapping
            PRODUCT_FIELDS = [
                ('', 'Skip this column'),
                ('name', 'Product Name'),
                ('sku', 'SKU Code'),
                ('barcode', 'Barcode'),
                ('description', 'Description'),
                ('selling_price', 'Selling Price'),
                ('cost_price', 'Cost Price'),
                ('discount_percentage', 'Discount Percentage'),
                ('tax_rate', 'Tax Rate'),
                ('excise_duty_rate', 'Excise Duty Rate'),
                ('unit_of_measure', 'Unit of Measure'),
                ('min_stock_level', 'Minimum Stock Level'),
                ('stock_level', 'Current Stock Level'),
                ('category_name', 'Category Name'),
                ('supplier_name', 'Supplier Name'),
                ('is_active', 'Active Status'),
            ]

            # Add mapping field for each CSV column
            for i, header in enumerate(csv_headers):
                field_name = f'column_{i}'
                self.fields[field_name] = forms.ChoiceField(
                    choices=PRODUCT_FIELDS,
                    required=False,
                    label=f'Map "{header}" to',
                    widget=forms.Select(attrs={'class': 'form-select'})
                )

                # Try to auto-match common column names
                header_lower = header.lower().replace(' ', '_')
                for field_value, field_label in PRODUCT_FIELDS[1:]:  # Skip empty option
                    if field_value in header_lower or header_lower in field_value:
                        self.fields[field_name].initial = field_value
                        break


class ProductExportForm(forms.Form):
    """Form for exporting products to CSV/Excel"""

    FORMAT_CHOICES = [
        ('csv', 'CSV File'),
        ('xlsx', 'Excel File'),
    ]

    export_format = forms.ChoiceField(
        choices=FORMAT_CHOICES,
        initial='xlsx',
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    # Fields to include in export
    include_basic_info = forms.BooleanField(
        required=False,
        initial=True,
        label='Basic Information',
        help_text='Name, SKU, barcode, description',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    include_pricing = forms.BooleanField(
        required=False,
        initial=True,
        label='Pricing Information',
        help_text='Selling price, cost price, discount',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    include_tax_info = forms.BooleanField(
        required=False,
        initial=True,
        label='Tax Information',
        help_text='Tax rate, excise duty rate',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    include_stock_info = forms.BooleanField(
        required=False,
        initial=True,
        label='Stock Information',
        help_text='Stock levels, minimum stock',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    include_efris_info = forms.BooleanField(
        required=False,
        initial=False,
        label='EFRIS Information',
        help_text='EFRIS sync status, upload dates, computed EFRIS values',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    include_relationships = forms.BooleanField(
        required=False,
        initial=True,
        label='Category & Supplier',
        help_text='Category and supplier information',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    # Filter options
    active_only = forms.BooleanField(
        required=False,
        initial=True,
        help_text='Export only active products',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    category = forms.ModelChoiceField(
        queryset=Category.objects.filter(is_active=True),
        required=False,
        empty_label="All Categories",
        help_text='Export products from specific category only',
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    def clean(self):
        cleaned_data = super().clean()

        # Ensure at least one field group is selected
        field_groups = [
            'include_basic_info', 'include_pricing', 'include_tax_info',
            'include_stock_info', 'include_efris_info', 'include_relationships'
        ]

        if not any(cleaned_data.get(field) for field in field_groups):
            raise ValidationError("Please select at least one information group to export.")

        return cleaned_data


class ProductSearchForm(forms.Form):
    """Quick search form for AJAX product lookups"""

    q = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search products...',
            'autocomplete': 'off'
        })
    )

    limit = forms.IntegerField(
        initial=10,
        min_value=1,
        max_value=50,
        widget=forms.HiddenInput()
    )

    include_inactive = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.HiddenInput()
    )


class ProductStockAdjustmentForm(forms.Form):
    """Form for adjusting product stock levels"""

    ADJUSTMENT_TYPES = [
        ('add', 'Add Stock'),
        ('subtract', 'Remove Stock'),
        ('set', 'Set Stock Level'),
    ]

    products = forms.ModelMultipleChoiceField(
        queryset=Product.objects.filter(is_active=True),
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'})
    )

    adjustment_type = forms.ChoiceField(
        choices=ADJUSTMENT_TYPES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    quantity = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'step': '0.01'
        })
    )

    reason = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Reason for adjustment (optional)'
        })
    )

    update_efris = forms.BooleanField(
        required=False,
        initial=False,
        help_text='Mark products for EFRIS re-upload after stock adjustment',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )


class StockImportMappingForm(forms.Form):
    """Form for mapping CSV columns to Stock model fields"""

    STOCK_FIELDS = [
        ('', 'Skip this column'),
        ('product_name', 'Product Name'),
        ('product_sku', 'Product SKU'),
        ('store_name', 'Store Name'),
        ('quantity', 'Current Quantity'),
        ('low_stock_threshold', 'Low Stock Threshold'),
        ('reorder_quantity', 'Reorder Quantity'),
        ('last_physical_count_quantity', 'Last Physical Count'),
        ('cost_price', 'Cost Price'),
        ('selling_price', 'Selling Price'),
        ('category_name', 'Category Name'),
        ('supplier_name', 'Supplier Name'),
    ]

    import_mode = forms.ChoiceField(
        choices=[
            ('create_only', 'Create new stock records only'),
            ('update_only', 'Update existing stock records only'),
            ('create_and_update', 'Create new and update existing'),
        ],
        initial='create_and_update',
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    has_header_row = forms.BooleanField(
        required=False,
        initial=True,
        help_text='First row contains column headers',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    def __init__(self, *args, csv_columns=None, **kwargs):
        super().__init__(*args, **kwargs)

        if csv_columns:
            for i, column_name in enumerate(csv_columns):
                field_name = f'column_{i}'
                self.fields[field_name] = forms.ChoiceField(
                    choices=self.STOCK_FIELDS,
                    required=False,
                    label=f'Map "{column_name}" to:',
                    widget=forms.Select(attrs={'class': 'form-control'})
                )

                # Auto-suggest mappings based on column names
                column_lower = column_name.lower().replace(' ', '_')
                for field_value, field_label in self.STOCK_FIELDS[1:]:
                    if field_value in column_lower or any(word in column_lower for word in field_value.split('_')):
                        self.fields[field_name].initial = field_value
                        break



class StockStoreForm(forms.ModelForm):
    class Meta:
        model = StockStore
        fields = [
            'name', 'code', 'description', 'physical_address', 'region',
            'latitude', 'longitude', 'phone', 'email',
            'manager_name', 'manager_phone',
            'is_main_stockstore', 'auto_approve_transfers',
            'requires_manager_approval', 'min_stock_alert_enabled',
            'staff', 'managers', 'notes'
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'physical_address': forms.Textarea(attrs={'rows': 3}),
            'notes': forms.Textarea(attrs={'rows': 3}),
            'staff': forms.CheckboxSelectMultiple(),
            'managers': forms.CheckboxSelectMultiple(),
        }


class StockTransferRequestForm(forms.ModelForm):
    class Meta:
        model = StockTransferRequest
        fields = [
            'transfer_type', 'source_stockstore', 'destination_stockstore',
            'source_store', 'destination_store', 'priority', 'reason',
            'expected_delivery_date', 'vehicle_number', 'driver_name',
            'driver_phone', 'notes'
        ]
        widgets = {
            'reason': forms.Textarea(attrs={'rows': 3}),
            'notes': forms.Textarea(attrs={'rows': 3}),
            'expected_delivery_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        self.company = kwargs.pop('company', None)
        super().__init__(*args, **kwargs)

        # Filter querysets by company
        if self.company:
            self.fields['source_stockstore'].queryset = StockStore.objects.filter(
                company=self.company, is_active=True
            )
            self.fields['destination_stockstore'].queryset = StockStore.objects.filter(
                company=self.company, is_active=True
            )
            self.fields['source_store'].queryset = Store.objects.filter(
                company=self.company, is_active=True
            )
            self.fields['destination_store'].queryset = Store.objects.filter(
                company=self.company, is_active=True
            )

        # Dynamic field visibility based on transfer type
        self.fields['source_stockstore'].required = False
        self.fields['destination_stockstore'].required = False
        self.fields['source_store'].required = False
        self.fields['destination_store'].required = False

    def clean(self):
        cleaned_data = super().clean()
        transfer_type = cleaned_data.get('transfer_type')

        if transfer_type == 'WAREHOUSE_TO_BRANCH':
            if not cleaned_data.get('source_stockstore'):
                self.add_error('source_stockstore', 'Source warehouse is required')
            if not cleaned_data.get('destination_store'):
                self.add_error('destination_store', 'Destination branch is required')

        elif transfer_type == 'BRANCH_TO_BRANCH':
            if not cleaned_data.get('source_store'):
                self.add_error('source_store', 'Source branch is required')
            if not cleaned_data.get('destination_store'):
                self.add_error('destination_store', 'Destination branch is required')

        elif transfer_type == 'BRANCH_TO_WAREHOUSE':
            if not cleaned_data.get('source_store'):
                self.add_error('source_store', 'Source branch is required')
            if not cleaned_data.get('destination_stockstore'):
                self.add_error('destination_stockstore', 'Destination warehouse is required')

        return cleaned_data


class StockTransferItemForm(forms.ModelForm):
    class Meta:
        model = StockTransferItem
        fields = ['product', 'quantity_requested', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 2}),
        }


StockTransferItemFormSet = inlineformset_factory(
    StockTransferRequest,
    StockTransferItem,
    form=StockTransferItemForm,
    extra=1,
    can_delete=True
)


class ReceiveTransferForm(forms.Form):
    receipt_notes = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3}),
        required=False,
        label='Receipt Notes'
    )

    def __init__(self, *args, **kwargs):
        self.transfer = kwargs.pop('transfer')
        super().__init__(*args, **kwargs)

        # Add a field for each item
        for item in self.transfer.items.all():
            field_name = f'quantity_{item.id}'
            self.fields[field_name] = forms.DecimalField(
                label=f'{item.product.name} (Sent: {item.quantity_sent})',
                initial=item.quantity_sent,
                max_digits=12,
                decimal_places=3,
                min_value=0
            )

    def clean(self):
        cleaned_data = super().clean()
        actual_quantities = {}

        for item in self.transfer.items.all():
            field_name = f'quantity_{item.id}'
            quantity = cleaned_data.get(field_name)
            if quantity is not None:
                actual_quantities[item.id] = quantity

        cleaned_data['actual_quantities'] = actual_quantities
        return cleaned_data
