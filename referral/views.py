import json
import base64
import io
from collections import defaultdict
from datetime import timedelta

from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.conf import settings
from django.db.models import Count
from django.db.models.functions import TruncMonth
from django.core.mail import send_mail
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.contrib.auth import update_session_auth_hash
from .forms import (ChangePasswordForm, ChangeEmailForm,
                   ForgotPasswordForm, PasswordResetForm)
from .models import Partner, ReferralSignup
from .forms import PartnerRegistrationForm, PartnerLoginForm, PartnerProfileForm, PartnerBrandingForm
from .decorators import partner_required


# ─────────────────────────────────────────────
# Auth Views
# ─────────────────────────────────────────────

def partner_register(request):
    if request.user.is_authenticated and isinstance(request.user, Partner):
        return redirect('referral:dashboard')

    if request.method == 'POST':
        form = PartnerRegistrationForm(request.POST)
        if form.is_valid():
            form.save()
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
def forgot_password(request):
    """
    Step 1: partner enters their email.
    We always show the same "check your inbox" message to avoid
    leaking whether an account exists.
    """
    if request.user.is_authenticated:
        return redirect('referral:dashboard')

    if request.method == 'POST':
        form = ForgotPasswordForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            _send_password_reset_email(request, email)
            return redirect('referral:forgot_password_done')
    else:
        form = ForgotPasswordForm()

    return render(request, 'referral/forgot_password.html', {'form': form})


def forgot_password_done(request):
    """Step 2: confirmation page — "check your inbox"."""
    return render(request, 'referral/forgot_password_done.html')


def password_reset_confirm(request, uidb64, token):
    """
    Step 3: partner clicks the link in their email.
    uidb64 + token are validated; on success the partner can set a new password.
    """
    partner = _get_partner_from_uid(uidb64)
    valid_link = partner is not None and default_token_generator.check_token(partner, token)

    if not valid_link:
        return render(request, 'referral/password_reset_invalid.html')

    if request.method == 'POST':
        form = PasswordResetForm(request.POST)
        if form.is_valid():
            partner.set_password(form.cleaned_data['password1'])
            partner.save(update_fields=['password'])
            messages.success(request, "✓ Password updated. You can now sign in.")
            return redirect('referral:login')
    else:
        form = PasswordResetForm()

    return render(request, 'referral/password_reset_confirm.html', {
        'form': form,
        'uidb64': uidb64,
        'token': token,
    })


# ── Change Password (authenticated) ────────────────────────────────────────

@partner_required
def change_password(request):
    partner = request.user
    if request.method == 'POST':
        form = ChangePasswordForm(partner, request.POST)
        if form.is_valid():
            form.save()
            # Keep the user logged in after password change
            update_session_auth_hash(request, partner)
            messages.success(request, "✓ Password changed successfully.")
            return redirect('referral:change_password')
    else:
        form = ChangePasswordForm(partner)

    return render(request, 'referral/change_password.html', {
        'form': form,
        'partner': partner,
    })


# ── Change Email (authenticated) ────────────────────────────────────────────

@partner_required
def change_email(request):
    """
    Partner requests an email change.
    We send a confirmation link to the NEW address before committing the change.
    """
    partner = request.user
    if request.method == 'POST':
        form = ChangeEmailForm(partner, request.POST)
        if form.is_valid():
            new_email = form.cleaned_data['new_email']
            _send_email_change_confirmation(request, partner, new_email)
            messages.success(
                request,
                f"A confirmation link has been sent to {new_email}. "
                "Click it to complete the email change."
            )
            return redirect('referral:change_email')
    else:
        form = ChangeEmailForm(partner)

    return render(request, 'referral/change_email.html', {
        'form': form,
        'partner': partner,
    })


def confirm_email_change(request, uidb64, token):
    """
    Partner clicks the link in the new-email confirmation message.
    We store the pending email in the token payload via a signed value in the session.
    Because default_token_generator doesn't carry a payload, we encode the
    new email in the uidb64 portion as: base64(partner_pk + ':' + new_email).
    """
    try:
        decoded = force_str(urlsafe_base64_decode(uidb64))
        pk_str, new_email = decoded.split(':', 1)
        uid = uuid.UUID(pk_str)
        partner = Partner.objects.get(pk=uid)
    except Exception:
        return render(request, 'referral/password_reset_invalid.html', {
            'message': "This email-change link is invalid or has expired."
        })

    if not default_token_generator.check_token(partner, token):
        return render(request, 'referral/password_reset_invalid.html', {
            'message': "This email-change link is invalid or has expired."
        })

    # Check the new email is still available
    if Partner.objects.filter(email__iexact=new_email).exclude(pk=partner.pk).exists():
        messages.error(request, "That email address is already in use by another account.")
        return redirect('referral:login')

    partner.email = new_email
    partner.save(update_fields=['email'])
    messages.success(request, f"✓ Email updated to {new_email}. Please sign in again.")
    return redirect('referral:login')


# ── Private helpers ─────────────────────────────────────────────────────────

def _get_partner_from_uid(uidb64):
    try:
        uid = uuid.UUID(force_str(urlsafe_base64_decode(uidb64)))
        return Partner.objects.get(pk=uid)
    except Exception:
        return None


def _send_password_reset_email(request, email):
    try:
        partner = Partner.objects.get(email__iexact=email, is_active=True)
    except Partner.DoesNotExist:
        return  # Silent — don't reveal account existence

    uid = urlsafe_base64_encode(force_bytes(str(partner.pk)))
    token = default_token_generator.make_token(partner)
    reset_url = request.build_absolute_uri(
        f'/partners/password-reset/{uid}/{token}/'
    )

    send_mail(
        subject='Reset your PrimeBooks Partner password',
        message=(
            f"Hi {partner.full_name},\n\n"
            f"Click the link below to reset your password (valid for 24 hours):\n\n"
            f"{reset_url}\n\n"
            f"If you didn't request this, you can safely ignore this email.\n\n"
            f"— PrimeBooks Partner Team"
        ),
        from_email=None,  # uses DEFAULT_FROM_EMAIL from settings
        recipient_list=[partner.email],
        fail_silently=True,
    )


def _send_email_change_confirmation(request, partner, new_email):
    # Encode both pk and new_email into uidb64
    payload = f"{str(partner.pk)}:{new_email}"
    uid = urlsafe_base64_encode(force_bytes(payload))
    token = default_token_generator.make_token(partner)
    confirm_url = request.build_absolute_uri(
        f'/partners/confirm-email-change/{uid}/{token}/'
    )

    send_mail(
        subject='Confirm your new PrimeBooks Partner email address',
        message=(
            f"Hi {partner.full_name},\n\n"
            f"You requested to change your sign-in email to: {new_email}\n\n"
            f"Click the link below to confirm (valid for 24 hours):\n\n"
            f"{confirm_url}\n\n"
            f"If you didn't request this, please ignore this email — "
            f"your current address will remain unchanged.\n\n"
            f"— PrimeBooks Partner Team"
        ),
        from_email=None,
        recipient_list=[new_email],
        fail_silently=True,
    )

@partner_required
def dashboard(request):
    partner = request.user
    base_signup_url = getattr(settings, 'TENANT_SIGNUP_URL', request.build_absolute_uri('/signup'))
    referral_link = f"{base_signup_url}?ref={partner.referral_code}"

    all_referrals = partner.referrals.order_by('-registered_at')
    recent_referrals = all_referrals[:10]

    stats = {
        'total': partner.total_referrals,
        'completed': partner.successful_referrals,
        'pending': partner.pending_referrals,
        'cancelled': all_referrals.filter(status='cancelled').count(),
        'earned': partner.total_earned,
        'paid': partner.total_paid,
        'pending_payout': partner.total_pending_payout,
    }

    # Monthly activity chart — last 12 months
    twelve_months_ago = timezone.now() - timedelta(days=365)
    monthly_data = (
        partner.referrals
        .filter(registered_at__gte=twelve_months_ago)
        .annotate(month=TruncMonth('registered_at'))
        .values('month', 'status')
        .annotate(count=Count('id'))
        .order_by('month')
    )

    # Build chart data
    chart_months = {}
    for entry in monthly_data:
        label = entry['month'].strftime('%b %Y')
        if label not in chart_months:
            chart_months[label] = {'pending': 0, 'completed': 0, 'cancelled': 0}
        chart_months[label][entry['status']] += entry['count']

    chart_labels = list(chart_months.keys())
    chart_completed = [chart_months[m]['completed'] for m in chart_labels]
    chart_pending = [chart_months[m]['pending'] for m in chart_labels]

    context = {
        'partner': partner,
        'referral_link': referral_link,
        'referral_code': partner.referral_code,
        'stats': stats,
        'recent_referrals': recent_referrals,
        'chart_labels': json.dumps(chart_labels),
        'chart_completed': json.dumps(chart_completed),
        'chart_pending': json.dumps(chart_pending),
    }
    return render(request, 'referral/dashboard.html', context)


@partner_required
def referrals_list(request):
    partner = request.user
    referrals = partner.referrals.order_by('-registered_at')

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
# QR Code Views
# ─────────────────────────────────────────────

@partner_required
def qr_dashboard(request):
    """QR code & branded share card management page."""
    partner = request.user
    base_signup_url = getattr(settings, 'TENANT_SIGNUP_URL', request.build_absolute_uri('/signup'))
    referral_link = f"{base_signup_url}?ref={partner.referral_code}&utm_source=qrcode"

    branding_form = PartnerBrandingForm(instance=partner)
    if request.method == 'POST':
        branding_form = PartnerBrandingForm(request.POST, instance=partner)
        if branding_form.is_valid():
            branding_form.save()
            messages.success(request, "Share card updated!")
            return redirect('referral:qr_dashboard')

    # Pre-built UTM campaign links
    utm_sources = [
        ('WhatsApp', f"{base_signup_url}?ref={partner.referral_code}&utm_source=whatsapp"),
        ('Instagram / Facebook', f"{base_signup_url}?ref={partner.referral_code}&utm_source=social"),
        ('Email / Newsletter', f"{base_signup_url}?ref={partner.referral_code}&utm_source=email"),
        ('Printed Flyer / QR', f"{base_signup_url}?ref={partner.referral_code}&utm_source=print"),
        ('LinkedIn', f"{base_signup_url}?ref={partner.referral_code}&utm_source=linkedin"),
        ('Direct / SMS', f"{base_signup_url}?ref={partner.referral_code}&utm_source=sms"),
    ]

    context = {
        'partner': partner,
        'referral_link': referral_link,
        'branding_form': branding_form,
        'utm_links': utm_sources,
    }
    return render(request, 'referral/qr_dashboard.html', context)


@partner_required
def qr_code_svg(request):
    """
    Returns a pure SVG QR code for the partner's referral link.
    Uses the qrcode library with SVG image factory — no PIL required.
    Falls back to a data-URL PNG if SVG factory unavailable.
    """
    partner = request.user
    base_signup_url = getattr(settings, 'TENANT_SIGNUP_URL', request.build_absolute_uri('/signup'))
    referral_link = f"{base_signup_url}?ref={partner.referral_code}&utm_source=qrcode"

    utm = request.GET.get('utm', 'qrcode')
    link = f"{base_signup_url}?ref={partner.referral_code}&utm_source={utm}"

    fmt = request.GET.get('format', 'svg')

    try:
        import qrcode
        if fmt == 'png':
            import qrcode
            qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=10, border=2)
            qr.add_data(link)
            qr.make(fit=True)
            img = qr.make_image(fill_color='#0c19dd', back_color='white')
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            buf.seek(0)
            return HttpResponse(buf.read(), content_type='image/png')
        else:
            from qrcode.image.svg import SvgPathFillImage
            qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=10, border=2)
            qr.add_data(link)
            qr.make(fit=True)
            img = qr.make_image(image_factory=SvgPathFillImage)
            buf = io.BytesIO()
            img.save(buf)
            buf.seek(0)
            return HttpResponse(buf.read(), content_type='image/svg+xml')
    except ImportError:
        # qrcode not installed — return a placeholder SVG
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" viewBox="0 0 200 200">
            <rect width="200" height="200" fill="#f5f5f5" rx="8"/>
            <text x="100" y="90" font-family="sans-serif" font-size="11" fill="#888" text-anchor="middle">QR unavailable</text>
            <text x="100" y="108" font-family="sans-serif" font-size="9" fill="#aaa" text-anchor="middle">pip install qrcode[pil]</text>
        </svg>'''
        return HttpResponse(svg, content_type='image/svg+xml')


@partner_required
def share_card_data(request):
    """
    Returns JSON with all data needed to render the share card on the client.
    The actual share card is rendered client-side using Canvas API for download.
    """
    partner = request.user
    base_signup_url = getattr(settings, 'TENANT_SIGNUP_URL', request.build_absolute_uri('/signup'))
    referral_link = f"{base_signup_url}?ref={partner.referral_code}&utm_source=sharecard"

    return JsonResponse({
        'name': partner.full_name,
        'company': partner.company_name or 'Partner',
        'referral_code': partner.referral_code,
        'referral_link': referral_link,
        'tagline': partner.ad_tagline or 'Manage your business smarter with PrimeBooks',
        'promo': partner.ad_promo_text or 'Free trial available — no credit card needed',
        'qr_url': request.build_absolute_uri(f'/partners/qr-code/?format=png&utm=sharecard'),
    })


# ─────────────────────────────────────────────
# Earnings Views
# ─────────────────────────────────────────────

@partner_required
def earnings(request):
    """Detailed earnings breakdown."""
    partner = request.user
    paid_referrals = partner.referrals.filter(status='completed', commission_paid=True).order_by('-commission_paid_at')
    unpaid_referrals = partner.referrals.filter(status='completed', commission_paid=False).order_by('-completed_at')

    context = {
        'partner': partner,
        'paid_referrals': paid_referrals,
        'unpaid_referrals': unpaid_referrals,
        'total_earned': partner.total_earned,
        'total_paid': partner.total_paid,
        'total_pending_payout': partner.total_pending_payout,
    }
    return render(request, 'referral/earnings.html', context)


# ─────────────────────────────────────────────
# Utility / Integration helpers
# ─────────────────────────────────────────────

def resolve_referral_code(ref_code):
    try:
        return Partner.objects.get(referral_code=ref_code, is_active=True, is_approved=True)
    except Partner.DoesNotExist:
        return None


def store_referral_in_session(request):
    ref = request.GET.get('ref')
    if ref:
        request.session['referral_code'] = ref
    utm_source = request.GET.get('utm_source', '')
    if utm_source:
        request.session['referral_utm_source'] = utm_source