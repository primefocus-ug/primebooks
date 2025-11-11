from django.core.mail.backends.smtp import EmailBackend as SMTPBackend
from django.conf import settings
from django_tenants.utils import get_tenant_model, tenant_context
from django.core.cache import cache
from django.db import connection
import logging
import threading

logger = logging.getLogger(__name__)


class TenantAwareEmailBackend(SMTPBackend):
    def __init__(self, *args, **kwargs):
        # Initialize the lock first
        self._lock = threading.RLock()
        # Call parent constructor
        super().__init__(fail_silently=kwargs.get('fail_silently', False))
        self.tenant_config = None

    def _get_tenant_email_config(self, tenant=None):
        """
        Retrieve email configuration for the current tenant
        """
        try:
            # Try to get tenant from connection if not provided
            if tenant is None:
                tenant = getattr(connection, 'tenant', None)

            if not tenant or tenant.schema_name == 'public':
                return None

            # Cache key for tenant email config
            cache_key = f'tenant_email_config_{tenant.schema_name}'
            config = cache.get(cache_key)

            if config is None:
                # Use tenant_context for database operations
                with tenant_context(tenant):
                    try:
                        from company.models import TenantEmailSettings
                        email_settings = TenantEmailSettings.objects.filter(
                            company=tenant,
                            is_active=True
                        ).first()

                        if email_settings:
                            config = {
                                'host': email_settings.smtp_host,
                                'port': email_settings.smtp_port,
                                'username': email_settings.smtp_username,
                                'password': email_settings.smtp_password,
                                'use_tls': email_settings.use_tls,
                                'use_ssl': email_settings.use_ssl,
                                'from_email': email_settings.from_email,
                                'timeout': email_settings.timeout or 30,
                            }
                            cache.set(cache_key, config, 3600)
                        else:
                            config = {}
                            cache.set(cache_key, config, 300)
                    except Exception as e:
                        logger.error(f"Error fetching email settings for tenant {tenant.schema_name}: {e}")
                        config = {}

            return config if config else None

        except Exception as e:
            logger.error(f"Error getting tenant email config: {e}")
            return None

    def open(self):
        """
        Open connection with tenant-specific or default SMTP settings
        """
        # Get tenant config once and cache it for this connection
        if self.tenant_config is None:
            self.tenant_config = self._get_tenant_email_config()

        if self.tenant_config:
            # Use tenant-specific settings
            self.host = self.tenant_config.get('host', settings.EMAIL_HOST)
            self.port = self.tenant_config.get('port', settings.EMAIL_PORT)
            self.username = self.tenant_config.get('username', settings.EMAIL_HOST_USER)
            self.password = self.tenant_config.get('password', settings.EMAIL_HOST_PASSWORD)
            self.use_tls = self.tenant_config.get('use_tls', settings.EMAIL_USE_TLS)
            self.use_ssl = self.tenant_config.get('use_ssl', False)
            self.timeout = self.tenant_config.get('timeout', 30)

            logger.info(f"Using tenant-specific email configuration: {self.host}")
        else:
            # Use default settings
            self.host = settings.EMAIL_HOST
            self.port = settings.EMAIL_PORT
            self.username = settings.EMAIL_HOST_USER
            self.password = settings.EMAIL_HOST_PASSWORD
            self.use_tls = getattr(settings, 'EMAIL_USE_TLS', False)
            self.use_ssl = getattr(settings, 'EMAIL_USE_SSL', False)
            self.timeout = getattr(settings, 'EMAIL_TIMEOUT', None)

            logger.info("Using default email configuration")

        return super().open()

    def send_messages(self, email_messages):
        """
        Send email messages with tenant context
        """
        if not email_messages:
            return 0

        try:
            # Get tenant from connection
            tenant = getattr(connection, 'tenant', None)
            tenant_config = self._get_tenant_email_config(tenant)

            if tenant_config and tenant_config.get('from_email'):
                # Override from_email for all messages if tenant has custom from_email
                for message in email_messages:
                    if not message.from_email:
                        message.from_email = tenant_config['from_email']

            # Reset tenant config to force fresh lookup on next operation
            self.tenant_config = None

            return super().send_messages(email_messages)

        except Exception as e:
            logger.error(f"Error sending emails: {e}")
            if not self.fail_silently:
                raise
            return 0


def send_tenant_email(subject, message, recipient_list, html_message=None,
                      from_email=None, fail_silently=False, tenant=None):
    """
    Helper function to send emails in tenant context
    """
    from django.core.mail import EmailMultiAlternatives
    from django.db import connection

    try:
        # Get current tenant if not provided
        if tenant is None:
            tenant = getattr(connection, 'tenant', None)

        if not tenant:
            logger.warning("No tenant context available, using default email configuration")
            # Fall back to regular email sending
            email = EmailMultiAlternatives(
                subject=subject,
                body=message,
                from_email=from_email or settings.DEFAULT_FROM_EMAIL,
                to=recipient_list
            )
            if html_message:
                email.attach_alternative(html_message, "text/html")
            return email.send(fail_silently=fail_silently)

        # Use tenant_context to ensure proper isolation
        with tenant_context(tenant):
            # Get tenant-specific from email within tenant context
            backend = TenantAwareEmailBackend()
            tenant_config = backend._get_tenant_email_config(tenant)

            if not from_email:
                if tenant_config and tenant_config.get('from_email'):
                    from_email = tenant_config['from_email']
                else:
                    from_email = settings.DEFAULT_FROM_EMAIL

            # Create email
            email = EmailMultiAlternatives(
                subject=subject,
                body=message,
                from_email=from_email,
                to=recipient_list
            )

            if html_message:
                email.attach_alternative(html_message, "text/html")

            # Send using tenant-aware backend
            return email.send(fail_silently=fail_silently)

    except Exception as e:
        logger.error(f"Error in send_tenant_email: {e}")
        if not fail_silently:
            raise
        return 0


def send_invoice_email(invoice, recipient_email=None, tenant=None):
    """
    Send invoice email with proper tenant context
    """
    from django.template.loader import render_to_string
    from django.db import connection

    try:
        # Determine tenant
        if tenant is None:
            tenant = getattr(connection, 'tenant', None) or getattr(invoice, 'company', None)

        if not tenant:
            logger.error("No tenant context available for sending invoice email")
            return 0

        if not recipient_email:
            recipient_email = getattr(invoice.customer, 'email', None)

        if not recipient_email:
            logger.error("No recipient email provided for invoice email")
            return 0

        # Use tenant_context for template rendering and email sending
        with tenant_context(tenant):
            context = {
                'invoice': invoice,
                'tenant': tenant,
                'company_name': getattr(tenant, 'name', 'Our Company'),
            }

            subject = f'Invoice {getattr(invoice, "invoice_number", "Unknown")} from {getattr(tenant, "name", "Our Company")}'
            html_message = render_to_string('invoices/email/invoice_notification.html', context)
            text_message = render_to_string('invoices/email/invoice_notification.txt', context)

            return send_tenant_email(
                subject=subject,
                message=text_message,
                recipient_list=[recipient_email],
                html_message=html_message,
                tenant=tenant
            )

    except Exception as e:
        logger.error(f"Error in send_invoice_email: {e}")
        return 0


# Simple function for password reset that always works
def send_password_reset_email(user_email, reset_url, tenant=None):
    """
    Simple password reset email function that works with or without tenant context
    """
    from django.core.mail import send_mail
    from django.db import connection

    subject = 'Password Reset Request'
    message = f'Please click the link to reset your password: {reset_url}'

    try:
        if tenant:
            with tenant_context(tenant):
                return send_mail(
                    subject=subject,
                    message=message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[user_email],
                    fail_silently=False
                )
        else:
            # Get tenant from connection if available
            current_tenant = getattr(connection, 'tenant', None)
            if current_tenant:
                with tenant_context(current_tenant):
                    return send_mail(
                        subject=subject,
                        message=message,
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[user_email],
                        fail_silently=False
                    )
            else:
                # Fallback to regular email
                return send_mail(
                    subject=subject,
                    message=message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[user_email],
                    fail_silently=False
                )
    except Exception as e:
        logger.error(f"Error sending password reset email: {e}")
        return 0