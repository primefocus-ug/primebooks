from django import forms
from django.contrib.auth.forms import AuthenticationForm
from .models import Partner


class PartnerRegistrationForm(forms.ModelForm):
    password1 = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={'placeholder': 'Create a password', 'class': 'form-input'}),
    )
    password2 = forms.CharField(
        label='Confirm Password',
        widget=forms.PasswordInput(attrs={'placeholder': 'Repeat your password', 'class': 'form-input'}),
    )

    class Meta:
        model = Partner
        fields = ['full_name', 'email', 'phone', 'company_name']
        widgets = {
            'full_name': forms.TextInput(attrs={'placeholder': 'Your full name', 'class': 'form-input'}),
            'email': forms.EmailInput(attrs={'placeholder': 'your@email.com', 'class': 'form-input'}),
            'phone': forms.TextInput(attrs={'placeholder': '+256 700 000 000', 'class': 'form-input'}),
            'company_name': forms.TextInput(attrs={'placeholder': 'Your agency / company (optional)', 'class': 'form-input'}),
        }

    def clean_password2(self):
        p1 = self.cleaned_data.get('password1')
        p2 = self.cleaned_data.get('password2')
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("Passwords do not match.")
        return p2

    def clean_password1(self):
        p1 = self.cleaned_data.get('password1')
        if p1 and len(p1) < 8:
            raise forms.ValidationError("Password must be at least 8 characters.")
        return p1

    def save(self, commit=True):
        partner = super().save(commit=False)
        partner.set_password(self.cleaned_data['password1'])
        if commit:
            partner.save()
        return partner


from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from .models import Partner


class PartnerLoginForm(AuthenticationForm):
    username = forms.EmailField(
        label='Email',
        widget=forms.EmailInput(attrs={
            'placeholder': 'your@email.com',
            'class': 'form-input',
            'autofocus': True,
        }),
    )
    password = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={
            'placeholder': 'Your password',
            'class': 'form-input',
        }),
    )

    def clean(self):
        email = self.cleaned_data.get('username')  # field is named 'username' by AuthenticationForm
        password = self.cleaned_data.get('password')

        if email and password:
            # Bypass django.contrib.auth.authenticate() entirely.
            # That function iterates ALL backends including CompanyAwareAuthBackend
            # which queries tenant-schema tables that don't exist in the public schema.
            from referral.auth_backend import PartnerAuthBackend
            self.user_cache = PartnerAuthBackend().authenticate(
                self.request, username=email, password=password
            )

            if self.user_cache is None:
                raise ValidationError("Invalid email or password.")

            if not self.user_cache.is_active:
                raise ValidationError("This account is inactive.")

            if not self.user_cache.is_approved:
                raise ValidationError(
                    "Your account is pending approval. "
                    "You'll be notified once an admin approves it."
                )

        return self.cleaned_data


class PartnerProfileForm(forms.ModelForm):
    class Meta:
        model = Partner
        fields = ['full_name', 'phone', 'company_name']
        widgets = {
            'full_name': forms.TextInput(attrs={'class': 'form-input'}),
            'phone': forms.TextInput(attrs={'class': 'form-input'}),
            'company_name': forms.TextInput(attrs={'class': 'form-input'}),
        }