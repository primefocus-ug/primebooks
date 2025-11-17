from django import forms
from django.contrib.auth.forms import ReadOnlyPasswordHashField
from django.core.exceptions import ValidationError
from .models import PublicUser, PasswordResetToken
from django.utils import timezone


class PublicUserCreationForm(forms.ModelForm):
    """Form for creating new users in public admin"""

    password1 = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        required=False,
        help_text='Leave blank to auto-generate a secure password'
    )
    password2 = forms.CharField(
        label='Password confirmation',
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        required=False
    )

    class Meta:
        model = PublicUser
        fields = (
            'email', 'username', 'first_name', 'last_name', 'phone',
            'role', 'is_active', 'is_staff', 'is_admin',
            'can_manage_seo', 'can_manage_blog', 'can_manage_support',
            'can_manage_companies', 'can_view_analytics'
        )
        widgets = {
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'role': forms.Select(attrs={'class': 'form-control'}),
        }

    def clean_password2(self):
        password1 = self.cleaned_data.get('password1')
        password2 = self.cleaned_data.get('password2')

        if password1 or password2:
            if password1 != password2:
                raise ValidationError("Passwords don't match")

        return password2

    def save(self, commit=True):
        user = super().save(commit=False)

        password = self.cleaned_data.get('password1')
        if password:
            user.set_password(password)
        else:
            # Auto-generate password
            password = PublicUser.generate_default_password()
            user.set_password(password)

        user.identifier = PublicUser.generate_identifier()

        if commit:
            user.save()
            # Send welcome email with credentials
            user.send_welcome_email(password)

        return user


class PublicUserChangeForm(forms.ModelForm):
    """Form for updating users in public admin"""

    password = ReadOnlyPasswordHashField(
        label="Password",
        help_text=(
            'Raw passwords are not stored, so there is no way to see this '
            'user\'s password, but you can change the password using '
            '<a href="../password/">this form</a>.'
        ),
    )

    class Meta:
        model = PublicUser
        fields = (
            'email', 'username', 'first_name', 'last_name', 'phone',
            'role', 'is_active', 'is_staff', 'is_admin',
            'can_manage_seo', 'can_manage_blog', 'can_manage_support',
            'can_manage_companies', 'can_view_analytics',
            'avatar', 'bio', 'email_verified', 'force_password_change'
        )
        widgets = {
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'role': forms.Select(attrs={'class': 'form-control'}),
            'bio': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def clean_password(self):
        return self.initial.get('password')


class PasswordChangeForm(forms.Form):
    """Form for users to change their own password"""

    old_password = forms.CharField(
        label='Current Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )
    new_password1 = forms.CharField(
        label='New Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        help_text='Minimum 8 characters with letters, numbers and symbols'
    )
    new_password2 = forms.CharField(
        label='Confirm New Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_old_password(self):
        old_password = self.cleaned_data.get('old_password')
        if not self.user.check_password(old_password):
            raise ValidationError('Your current password is incorrect.')
        return old_password

    def clean_new_password2(self):
        password1 = self.cleaned_data.get('new_password1')
        password2 = self.cleaned_data.get('new_password2')

        if password1 and password2:
            if password1 != password2:
                raise ValidationError("The two password fields didn't match.")

        # Validate password strength
        if len(password1) < 8:
            raise ValidationError("Password must be at least 8 characters long.")

        return password2

    def save(self, commit=True):
        password = self.cleaned_data['new_password1']
        self.user.set_password(password)
        self.user.force_password_change = False
        self.user.password_changed_at = timezone.now()

        if commit:
            self.user.save()

        return self.user


class AdminPasswordResetForm(forms.Form):
    """Form for admins to reset a user's password"""

    new_password1 = forms.CharField(
        label='New Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        required=False,
        help_text='Leave blank to auto-generate a secure password'
    )
    new_password2 = forms.CharField(
        label='Confirm New Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        required=False
    )
    force_password_change = forms.BooleanField(
        label='Require password change on next login',
        required=False,
        initial=True
    )
    send_email = forms.BooleanField(
        label='Send new password via email',
        required=False,
        initial=True
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_new_password2(self):
        password1 = self.cleaned_data.get('new_password1')
        password2 = self.cleaned_data.get('new_password2')

        if password1 or password2:
            if password1 != password2:
                raise ValidationError("The two password fields didn't match.")

        return password2

    def save(self, commit=True):
        password = self.cleaned_data.get('new_password1')

        if not password:
            # Auto-generate password
            password = PublicUser.generate_default_password()

        self.user.set_password(password)
        self.user.force_password_change = self.cleaned_data.get('force_password_change', True)
        self.user.password_changed_at = timezone.now()

        if commit:
            self.user.save()

            # Send email if requested
            if self.cleaned_data.get('send_email'):
                self.user.send_welcome_email(password)

        return self.user, password


class PasswordResetRequestForm(forms.Form):
    """Form for users to request password reset"""

    identifier = forms.CharField(
        label='Login Identifier',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'PRIME-XXXXPF-YYMM-LTD'
        })
    )
    email = forms.EmailField(
        label='Email Address',
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'your.email@example.com'
        })
    )


class PasswordResetConfirmForm(forms.Form):
    """Form to set new password after reset"""

    new_password1 = forms.CharField(
        label='New Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        help_text='Minimum 8 characters with letters, numbers and symbols'
    )
    new_password2 = forms.CharField(
        label='Confirm New Password',
        widget=forms.PasswordInput(attrs={'class': 'form-control'})
    )

    def clean_new_password2(self):
        password1 = self.cleaned_data.get('new_password1')
        password2 = self.cleaned_data.get('new_password2')

        if password1 and password2:
            if password1 != password2:
                raise ValidationError("The two password fields didn't match.")

            if len(password1) < 8:
                raise ValidationError("Password must be at least 8 characters long.")

        return password2


class ProfileUpdateForm(forms.ModelForm):
    """Form for users to update their profile"""

    class Meta:
        model = PublicUser
        fields = ['first_name', 'last_name', 'phone', 'avatar', 'bio']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'bio': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }