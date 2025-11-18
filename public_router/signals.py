from django.db.models.signals import post_save, pre_save
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
    """Create approval workflow when signup is created"""
    if created:
        TenantApprovalWorkflow.objects.create(
            signup_request=instance
        )
        logger.info(f"Created approval workflow for {instance.company_name}")


@receiver(post_save, sender=TenantSignupRequest)
def send_signup_notifications(sender, instance, created, **kwargs):
    """Send email notifications on signup"""
    if created:
        # Send notification to admin
        send_admin_notification(instance)

        # Send confirmation to client
        send_client_confirmation(instance)


def send_admin_notification(signup_request):
    """Send notification to admin about new signup"""
    try:
        subject = f"🎉 New Tenant Signup: {signup_request.company_name}"

        context = {
            'signup': signup_request,
            'admin_url': f"{settings.BASE_URL}/admin/tenant-signups/{signup_request.request_id}/"
        }

        html_message = render_to_string(
            'public_router/emails/admin_signup_notification.html',
            context
        )

        plain_message = render_to_string(
            'public_router/emails/admin_signup_notification.txt',
            context
        )

        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[ADMIN_EMAIL],
            html_message=html_message,
            fail_silently=False,
        )

        # Log notification
        TenantNotificationLog.objects.create(
            signup_request=signup_request,
            notification_type='SIGNUP_TO_ADMIN',
            recipient_email=ADMIN_EMAIL,
            subject=subject,
            sent_successfully=True
        )

        # Update workflow
        workflow = signup_request.approval_workflow
        workflow.signup_notification_sent = True
        workflow.signup_notification_sent_at = timezone.now()
        workflow.save()

        logger.info(f"Admin notification sent for {signup_request.company_name}")

    except Exception as e:
        logger.error(f"Failed to send admin notification: {str(e)}")
        TenantNotificationLog.objects.create(
            signup_request=signup_request,
            notification_type='SIGNUP_TO_ADMIN',
            recipient_email=ADMIN_EMAIL,
            subject=subject,
            sent_successfully=False,
            error_message=str(e)
        )


def send_client_confirmation(signup_request):
    """Send confirmation email to client"""
    try:
        subject = f"We've received your Primebooks signup request!"

        context = {
            'signup': signup_request,
            'support_email': ADMIN_EMAIL,
            'support_phone': '+256 773 011 108',
            'whatsapp_link': 'https://wa.me/256755777826',
        }

        html_message = render_to_string(
            'public_router/emails/client_confirmation.html',
            context
        )

        plain_message = render_to_string(
            'public_router/emails/client_confirmation.txt',
            context
        )

        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[signup_request.admin_email],
            html_message=html_message,
            fail_silently=False,
        )

        logger.info(f"Client confirmation sent to {signup_request.admin_email}")

    except Exception as e:
        logger.error(f"Failed to send client confirmation: {str(e)}")