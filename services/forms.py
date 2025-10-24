from django import forms
from .models import (
    Service, ServiceAppointment, ServiceExecution,
    ServicePackage, ServiceReview
)


class ServiceForm(forms.ModelForm):
    class Meta:
        model = Service
        fields = [
            'name', 'code', 'description', 'category', 'service_type',
            'base_price', 'cost_price', 'hourly_rate', 'tax_rate',
            'default_duration', 'requires_appointment', 'allow_online_booking',
            'is_recurring', 'recurrence_interval', 'requires_staff',
            'staff_commission_rate', 'consumes_inventory', 'is_active',
            'is_featured', 'available_online', 'image', 'tags'
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
            'tags': forms.TextInput(attrs={'placeholder': 'Comma-separated tags'}),
            'base_price': forms.NumberInput(attrs={'step': '0.01'}),
            'cost_price': forms.NumberInput(attrs={'step': '0.01'}),
            'hourly_rate': forms.NumberInput(attrs={'step': '0.01'}),
            'tax_rate': forms.NumberInput(attrs={'step': '0.01'}),
            'staff_commission_rate': forms.NumberInput(attrs={'step': '0.01'}),
        }


class ServiceAppointmentForm(forms.ModelForm):
    class Meta:
        model = ServiceAppointment
        fields = [
            'service', 'pricing_tier', 'scheduled_date', 'scheduled_time',
            'duration_minutes', 'assigned_staff', 'notes'
        ]
        widgets = {
            'scheduled_date': forms.DateInput(attrs={'type': 'date'}),
            'scheduled_time': forms.TimeInput(attrs={'type': 'time'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }


class ServiceExecutionForm(forms.ModelForm):
    class Meta:
        model = ServiceExecution
        fields = [
            'work_description', 'findings', 'recommendations',
            'quality_rating', 'customer_feedback', 'status'
        ]
        widgets = {
            'work_description': forms.Textarea(attrs={'rows': 4}),
            'findings': forms.Textarea(attrs={'rows': 3}),
            'recommendations': forms.Textarea(attrs={'rows': 3}),
            'customer_feedback': forms.Textarea(attrs={'rows': 3}),
        }


class ServicePackageForm(forms.ModelForm):
    class Meta:
        model = ServicePackage
        fields = [
            'name', 'code', 'description', 'price',
            'discount_amount', 'discount_percentage',
            'validity_days', 'max_uses', 'is_active'
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
        }


class ServiceReviewForm(forms.ModelForm):
    class Meta:
        model = ServiceReview
        fields = ['rating', 'review_text', 'staff_rating']
        widgets = {
            'review_text': forms.Textarea(attrs={'rows': 4}),
            'rating': forms.RadioSelect(choices=[(i, f'{i} Star{"s" if i > 1 else ""}') for i in range(1, 6)]),
            'staff_rating': forms.RadioSelect(choices=[(i, f'{i} Star{"s" if i > 1 else ""}') for i in range(1, 6)]),
        }


