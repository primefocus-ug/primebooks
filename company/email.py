from django.core.mail.backends.smtp import EmailBackend as SMTPBackend
from django.conf import settings
from django_tenants.utils import get_tenant_model, schema_context
from django.core.cache import cache
import logging

logger = logging.getLogger(__name__)


class TenantAwareEmailBackend(SMTPBackend):
    def __init__(self, *args, **kwargs):
        # Don't call super().__init__() yet, we'll do it with tenant settings
        self.fail_silently = kwargs.get('fail_silently', False)
        self._lock = None
        self.connection = None

    def _get_tenant_email_config(self):
        """
        Retrieve email configuration for the current tenant
        Returns dict with SMTP settings or None if not configured
        """
        try:
            from django_tenants.utils import get_current_tenant
            tenant = get_current_tenant()

            if not tenant or tenant.schema_name == 'public':
                return None

            # Cache key for tenant email config
            cache_key = f'tenant_email_config_{tenant.schema_name}'
            config = cache.get(cache_key)

            if config is None:
                # Fetch from tenant's database
                with schema_context(tenant.schema_name):
                    # Assuming you have a TenantEmailSettings model
                    from company.models import TenantEmailSettings

                    try:
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
                            # Cache for 1 hour
                            cache.set(cache_key, config, 3600)
                        else:
                            config = {}
                            # Cache empty config for 5 minutes
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
        tenant_config = self._get_tenant_email_config()

        if tenant_config:
            # Use tenant-specific settings
            self.host = tenant_config.get('host', settings.EMAIL_HOST)
            self.port = tenant_config.get('port', settings.EMAIL_PORT)
            self.username = tenant_config.get('username', settings.EMAIL_HOST_USER)
            self.password = tenant_config.get('password', settings.EMAIL_HOST_PASSWORD)
            self.use_tls = tenant_config.get('use_tls', settings.EMAIL_USE_TLS)
            self.use_ssl = tenant_config.get('use_ssl', False)
            self.timeout = tenant_config.get('timeout', 30)

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
            # Get tenant config for from_email override
            tenant_config = self._get_tenant_email_config()

            if tenant_config and tenant_config.get('from_email'):
                # Override from_email for all messages if tenant has custom from_email
                for message in email_messages:
                    if not message.from_email:
                        message.from_email = tenant_config['from_email']

            return super().send_messages(email_messages)

        except Exception as e:
            logger.error(f"Error sending emails: {e}")
            if not self.fail_silently:
                raise
            return 0


def send_tenant_email(subject, message, recipient_list, html_message=None,
                      from_email=None, fail_silently=False):
    """
    Helper function to send emails in tenant context

    Usage:
        from company.email import send_tenant_email

        send_tenant_email(
            subject='Invoice Generated',
            message='Your invoice has been generated.',
            recipient_list=['customer@example.com'],
            html_message='<p>Your invoice has been generated.</p>'
        )
    """
    from django.core.mail import EmailMultiAlternatives
    from django_tenants.utils import get_current_tenant

    try:
        tenant = get_current_tenant()

        # Get tenant-specific from email
        if not from_email:
            tenant_config = TenantAwareEmailBackend()._get_tenant_email_config()
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


def send_invoice_email(invoice, recipient_email=None):
    from django.template.loader import render_to_string
    from django_tenants.utils import get_current_tenant

    tenant = get_current_tenant()

    if not recipient_email:
        recipient_email = invoice.customer.email

    context = {
        'invoice': invoice,
        'tenant': tenant,
        'company_name': tenant.name,
    }

    subject = f'Invoice {invoice.invoice_number} from {tenant.name}'
    html_message = render_to_string('invoices/email/invoice_notification.html', context)
    text_message = render_to_string('invoices/email/invoice_notification.txt', context)

    return send_tenant_email(
        subject=subject,
        message=text_message,
        recipient_list=[recipient_email],
        html_message=html_message
    )