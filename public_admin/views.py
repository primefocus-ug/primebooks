from django.views.generic import FormView, View
from django.shortcuts import redirect, render
from django.urls import reverse
from django.contrib import messages
from django.utils import timezone
from django import forms
from .models import PublicStaffUser


class LoginForm(forms.Form):
    username = forms.CharField(max_length=150)
    password = forms.CharField(widget=forms.PasswordInput)


class PublicStaffLoginView(FormView):
    """Login view for public staff users"""
    template_name = 'public_admin/login.html'
    form_class = LoginForm

    def dispatch(self, request, *args, **kwargs):
        # If already logged in, redirect to analytics
        if hasattr(request, 'public_staff_user'):
            return redirect('public_analytics:dashboard')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        username = form.cleaned_data['username']
        password = form.cleaned_data['password']

        try:
            user = PublicStaffUser.objects.get(username=username, is_active=True)

            if user.check_password(password):
                # Generate session token
                token = user.generate_session_token()

                # Update last login
                user.last_login = timezone.now()
                user.save()

                # Set session
                self.request.session['staff_token'] = token

                # Redirect to next or dashboard
                next_url = self.request.GET.get('next', reverse('public_analytics:dashboard'))
                return redirect(next_url)
            else:
                messages.error(self.request, 'Invalid username or password')
        except PublicStaffUser.DoesNotExist:
            messages.error(self.request, 'Invalid username or password')

        return self.form_invalid(form)


class PublicStaffLogoutView(View):
    """Logout view"""

    def get(self, request):
        # Clear session token
        if hasattr(request, 'public_staff_user'):
            user = request.public_staff_user
            user.session_token = None
            user.token_expires_at = None
            user.save()

        # Clear session
        request.session.flush()

        messages.success(request, 'You have been logged out successfully.')
        return redirect('public_admin:login')