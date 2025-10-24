from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages


def require_active_company(view_func):
    """Decorator to ensure company has active access"""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')

        company = request.user.company
        if not company or not company.has_active_access:
            messages.error(request, "Your company account does not have active access.")
            return redirect('company_expired')

        return view_func(request, *args, **kwargs)

    return wrapper