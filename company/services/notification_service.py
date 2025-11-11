import logging
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


class NotificationService:
    '''Service for sending notifications'''

    def send_subscription_expiry_warning(self, company, days_left):
        '''Send warning email when subscription is expiring'''
        try:
            subject = f'Your subscription expires in {days_left} days'

            context = {
                'company': company,
                'days_left': days_left,
                'renewal_url': f'{settings.SITE_URL}/companies/subscription/renew/',
            }

            html_message = render_to_string(
                'company/emails/expiry_warning.html',
                context
            )

            plain_message = f'''
            Dear {company.display_name},

            Your subscription will expire in {days_left} days.

            Please renew your subscription to continue using all features.

            Renew now: {context['renewal_url']}

            Thank you,
            The Team
            '''

            send_mail(
                subject=subject,
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[company.billing_email or company.email],
                html_message=html_message,
                fail_silently=False,
            )

            logger.info(f"Expiry warning sent to {company.company_id}")
            return True

        except Exception as e:
            logger.error(f"Error sending expiry warning: {e}", exc_info=True)
            return False

    def send_subscription_renewed(self, company):
        '''Send confirmation email when subscription is renewed'''
        try:
            subject = 'Subscription Renewed Successfully'

            context = {
                'company': company,
                'plan': company.plan,
                'renewal_date': company.subscription_ends_at,
            }

            html_message = render_to_string(
                'company/emails/renewal_confirmation.html',
                context
            )

            plain_message = f'''
            Dear {company.display_name},

            Your subscription has been renewed successfully!

            Plan: {company.plan.display_name}
            Valid until: {company.subscription_ends_at}

            Thank you for your continued business!

            The Team
            '''

            send_mail(
                subject=subject,
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[company.billing_email or company.email],
                html_message=html_message,
                fail_silently=False,
            )

            logger.info(f"Renewal confirmation sent to {company.company_id}")
            return True

        except Exception as e:
            logger.error(f"Error sending renewal confirmation: {e}", exc_info=True)
            return False

    def send_payment_failed(self, company, error_message):
        '''Send notification when payment fails'''
        try:
            subject = 'Payment Failed - Action Required'

            context = {
                'company': company,
                'error_message': error_message,
                'payment_url': f'{settings.SITE_URL}/companies/billing/payment-methods/',
            }

            plain_message = f'''
            Dear {company.display_name},

            We were unable to process your payment.

            Error: {error_message}

            Please update your payment method: {context['payment_url']}

            The Team
            '''

            send_mail(
                subject=subject,
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[company.billing_email or company.email],
                fail_silently=False,
            )

            logger.info(f"Payment failed notification sent to {company.company_id}")
            return True

        except Exception as e:
            logger.error(f"Error sending payment failed notification: {e}", exc_info=True)
            return False

    def send_plan_upgraded(self, company, old_plan, new_plan):
        '''Send confirmation when plan is upgraded'''
        try:
            subject = f'Plan Upgraded to {new_plan.display_name}'

            plain_message = f'''
            Dear {company.display_name},

            Your plan has been upgraded!

            Old Plan: {old_plan.display_name if old_plan else 'None'}
            New Plan: {new_plan.display_name}

            Enjoy your new features!

            The Team
            '''

            send_mail(
                subject=subject,
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[company.billing_email or company.email],
                fail_silently=False,
            )

            logger.info(f"Upgrade confirmation sent to {company.company_id}")
            return True

        except Exception as e:
            logger.error(f"Error sending upgrade confirmation: {e}", exc_info=True)
            return False

    def send_usage_limit_warning(self, company, limit_type, percentage):
        '''Send warning when approaching usage limits'''
        try:
            subject = f'Usage Limit Warning: {limit_type}'

            plain_message = f'''
            Dear {company.display_name},

            You are using {percentage}% of your {limit_type} limit.

            Consider upgrading your plan to avoid service interruption.

            Upgrade now: {settings.SITE_URL}/companies/subscription/plans/

            The Team
            '''

            send_mail(
                subject=subject,
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[company.billing_email or company.email],
                fail_silently=False,
            )

            logger.info(f"Usage warning sent to {company.company_id}: {limit_type}")
            return True

        except Exception as e:
            logger.error(f"Error sending usage warning: {e}", exc_info=True)
            return False