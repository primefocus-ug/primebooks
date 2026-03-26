"""
public_router/signals.py
"""
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone
from .models import TenantSignupRequest, TenantApprovalWorkflow, TenantNotificationLog
import logging

logger = logging.getLogger(__name__)

ADMIN_EMAIL = 'primefocusug@gmail.com'


@receiver(post_save, sender=TenantSignupRequest)
def create_approval_workflow(sender, instance, created, **kwargs):
    """
    Create an approval workflow row when a FREE-plan signup is saved.

    Paid-plan signups already have their workflow created by the view
    (with generated_password set) before the task is queued.  We must
    not overwrite that with an empty one.
    """
    if not created:
        return

    # Paid signups: view already created the workflow — nothing to do.
    if instance.is_paid_plan:
        return

    try:
        TenantApprovalWorkflow.objects.create(signup_request=instance)
        logger.info('Created approval workflow for free signup: %s', instance.company_name)
    except Exception as e:
        # Log but don't raise — a workflow failure must not abort the signup save.
        logger.error(
            'Failed to create approval workflow for %s: %s',
            instance.company_name, e,
        )


@receiver(post_save, sender=TenantSignupRequest)
def send_signup_notifications(sender, instance, created, **kwargs):
    """
    Send email notifications on new signup.

    Free plan  → notify admin (they need to approve) + confirm to client.
    Paid plan  → only confirm to client (no admin action required;
                 provisioning is already running).
    """
    if not created:
        return

    if instance.is_free_plan:
        # Admin needs to know so they can approve.
        _send_admin_notification(instance)

    # Always confirm receipt to the client regardless of plan.
    _send_client_confirmation(instance)


# ─────────────────────────────────────────────────────────────────────────────
# Email helpers
# ─────────────────────────────────────────────────────────────────────────────

def _send_admin_notification(signup_request):
    """Notify admin about a new FREE-plan signup that needs approval."""
    subject = f"🎉 New Tenant Signup (FREE): {signup_request.company_name}"
    try:
        context = {
            'signup': signup_request,
            'admin_url': (
                f"{settings.BASE_URL}/admin/tenant-signups/"
                f"{signup_request.request_id}/"
            ),
        }

        html_message = render_to_string(
            'public_router/emails/admin_signup_notification.html', context
        )
        plain_message = render_to_string(
            'public_router/emails/admin_signup_notification.txt', context
        )

        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[ADMIN_EMAIL],
            html_message=html_message,
            fail_silently=False,
        )

        TenantNotificationLog.objects.create(
            signup_request=signup_request,
            notification_type='SIGNUP_TO_ADMIN',
            recipient_email=ADMIN_EMAIL,
            subject=subject,
            sent_successfully=True,
        )

        # Update workflow if already created
        workflow = getattr(signup_request, 'approval_workflow', None)
        if workflow:
            workflow.signup_notification_sent    = True
            workflow.signup_notification_sent_at = timezone.now()
            workflow.save(update_fields=[
                'signup_notification_sent',
                'signup_notification_sent_at',
            ])

        logger.info('Admin notification sent for %s', signup_request.company_name)

    except Exception as e:
        logger.error('Failed to send admin notification: %s', e)
        TenantNotificationLog.objects.create(
            signup_request=signup_request,
            notification_type='SIGNUP_TO_ADMIN',
            recipient_email=ADMIN_EMAIL,
            subject=subject,
            sent_successfully=False,
            error_message=str(e),
        )


def _send_client_confirmation(signup_request):
    """
    Send confirmation to the client.

    Free plan  → "We received your request, we'll be in touch."
    Paid plan  → "We're setting up your workspace now — you'll get login
                  details in a few minutes."
    """
    subject = "We've received your PrimeBooks signup request!"
    try:
        plan = signup_request.selected_plan
        plan_name = (plan.display_name or plan.name) if plan else 'Free Trial'

        context = {
            'signup':        signup_request,
            'support_email': ADMIN_EMAIL,
            'support_phone': '+256 773 011 108',
            'whatsapp_link': 'https://wa.me/256755777826',
            'plan_name':     plan_name,
            # Template can branch on this flag
            'is_paid_plan':  signup_request.is_paid_plan,
        }

        html_message = render_to_string(
            'public_router/emails/client_confirmation.html', context
        )
        plain_message = render_to_string(
            'public_router/emails/client_confirmation.txt', context
        )

        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[signup_request.admin_email],
            html_message=html_message,
            fail_silently=False,
        )

        logger.info('Client confirmation sent to %s', signup_request.admin_email)

    except Exception as e:
        logger.error('Failed to send client confirmation: %s', e)