from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.conf import settings

from .models import Partner, ReferralSignup
from .forms import PartnerRegistrationForm, PartnerLoginForm, PartnerProfileForm
from .decorators import partner_required


# ─────────────────────────────────────────────
# Auth Views
# ─────────────────────────────────────────────

def partner_register(request):
    """Partner self-registration page."""
    if request.user.is_authenticated and isinstance(request.user, Partner):
        return redirect('referral:dashboard')

    if request.method == 'POST':
        form = PartnerRegistrationForm(request.POST)
        if form.is_valid():
            partner = form.save()
            messages.success(
                request,
                "🎉 Account created! Your application is under review. "
                "You'll be notified once approved."
            )
            return redirect('referral:login')
    else:
        form = PartnerRegistrationForm()

    return render(request, 'referral/register.html', {'form': form})


def partner_login(request):
    """Partner login page."""
    if request.user.is_authenticated and isinstance(request.user, Partner):
        return redirect('referral:dashboard')

    if request.method == 'POST':
        form = PartnerLoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            if isinstance(user, Partner):
                login(request, user, backend='referral.auth_backend.PartnerAuthBackend')
                return redirect(request.GET.get('next', 'referral:dashboard'))
            else:
                messages.error(request, "Invalid partner account.")
        else:
            messages.error(request, "Invalid email or password.")
    else:
        form = PartnerLoginForm(request)

    return render(request, 'referral/login.html', {'form': form})


def partner_logout(request):
    logout(request)
    return redirect('referral:login')


# ─────────────────────────────────────────────
# Dashboard Views
# ─────────────────────────────────────────────

@partner_required
def dashboard(request):
    """Main partner dashboard."""
    partner = request.user

    # Build referral link
    base_signup_url = getattr(settings, 'TENANT_SIGNUP_URL', request.build_absolute_uri('/signup'))
    referral_link = f"{base_signup_url}?ref={partner.referral_code}"

    # Referral stats
    all_referrals = partner.referrals.order_by('-registered_at')
    recent_referrals = all_referrals[:10]

    stats = {
        'total': partner.total_referrals,
        'completed': partner.successful_referrals,
        'pending': partner.pending_referrals,
        'cancelled': all_referrals.filter(status='cancelled').count(),
    }

    context = {
        'partner': partner,
        'referral_link': referral_link,
        'referral_code': partner.referral_code,
        'stats': stats,
        'recent_referrals': recent_referrals,
    }
    return render(request, 'referral/dashboard.html', context)


@partner_required
def referrals_list(request):
    """Full list of referrals for the partner."""
    partner = request.user
    referrals = partner.referrals.order_by('-registered_at')

    # Filter by status
    status_filter = request.GET.get('status', '')
    if status_filter:
        referrals = referrals.filter(status=status_filter)

    context = {
        'partner': partner,
        'referrals': referrals,
        'status_filter': status_filter,
    }
    return render(request, 'referral/referrals_list.html', context)


@partner_required
def profile(request):
    """Partner profile edit page."""
    partner = request.user
    if request.method == 'POST':
        form = PartnerProfileForm(request.POST, instance=partner)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated successfully.")
            return redirect('referral:profile')
    else:
        form = PartnerProfileForm(instance=partner)

    return render(request, 'referral/profile.html', {'form': form, 'partner': partner})


# ─────────────────────────────────────────────
# API / Utility
# ─────────────────────────────────────────────

def track_referral(request):
    """
    Called when a company completes tenant registration via a referral link.
    Integrate this into your existing tenant signup view.

    Example usage in your tenant signup view:
        ref_code = request.session.get('referral_code') or request.GET.get('ref')
        if ref_code:
            ReferralSignup.objects.create(
                partner=Partner.objects.filter(referral_code=ref_code).first(),
                referral_code_used=ref_code,
                company_name=company_name,
                company_email=company_email,
                status='pending',
            )
    """
    pass  # This is handled inline; see integration guide below


def resolve_referral_code(ref_code):
    """
    Helper: given a referral code, return the Partner or None.
    Use this in your tenant signup view.
    """
    try:
        return Partner.objects.get(referral_code=ref_code, is_active=True, is_approved=True)
    except Partner.DoesNotExist:
        return None


def store_referral_in_session(request):
    """
    Call this in your signup GET view to persist ref code across steps.
    Reads ?ref= from URL and stores in session.
    """
    ref = request.GET.get('ref')
    if ref:
        request.session['referral_code'] = ref