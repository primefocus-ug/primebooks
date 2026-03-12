from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from .models import Partner


def partner_required(view_func):
    """
    Decorator that ensures:
    1. User is authenticated
    2. User is a Partner instance
    3. Partner account is approved
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f'/partners/login/?next={request.path}')

        if not isinstance(request.user, Partner):
            messages.error(request, "Access restricted to partner accounts.")
            return redirect('/partners/login/')

        if not request.user.is_approved:
            return redirect('referral:pending_approval')

        return view_func(request, *args, **kwargs)
    return _wrapped_view


def pending_approval(request):
    from django.shortcuts import render
    return render(request, 'referral/pending_approval.html', {'partner': request.user})