from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from datetime import timedelta
from .models import PaymentReminder, Invoice
import logging

logger = logging.getLogger(__name__)


class PaymentReminderService:
    """Service to handle payment reminder logic"""

    # Reminder schedule configuration
    REMINDER_SCHEDULE = {
        'UPCOMING': -3,  # 3 days before due date
        'DUE': 0,  # On due date
        'OVERDUE': 7,  # 7 days after due date
        'FINAL_NOTICE': 14,  # 14 days after due date
    }

    @classmethod
    def send_reminder(cls, invoice, reminder_type='DUE',
                      payment_schedule=None, method='EMAIL'):
        """
        Send payment reminder for invoice

        Args:
            invoice: Invoice instance
            reminder_type: Type of reminder (UPCOMING, DUE, OVERDUE, FINAL_NOTICE)
            payment_schedule: Specific payment schedule being reminded (optional)
            method: Reminder method (EMAIL, SMS, etc.)

        Returns:
            PaymentReminder instance
        """
        if not invoice.customer or not invoice.customer.email:
            logger.warning(f"Cannot send reminder for invoice {invoice.id} - no customer email")
            return None

        try:
            # Prepare reminder data
            context = cls._prepare_reminder_context(
                invoice, reminder_type, payment_schedule
            )

            # Send based on method
            if method == 'EMAIL':
                success, error = cls._send_email_reminder(invoice, context)
            elif method == 'SMS':
                success, error = cls._send_sms_reminder(invoice, context)
            else:
                success, error = False, f"Unsupported method: {method}"

            # Create reminder record
            reminder = PaymentReminder.objects.create(
                invoice=invoice,
                payment_schedule=payment_schedule,
                reminder_type=reminder_type,
                reminder_method=method,
                recipient_email=invoice.customer.email,
                recipient_phone=getattr(invoice.customer, 'phone', None),
                subject=context.get('subject'),
                message=context.get('message'),
                is_successful=success,
                error_message=error,
                next_reminder_date=cls._calculate_next_reminder_date(
                    reminder_type, invoice
                )
            )

            logger.info(
                f"Sent {reminder_type} reminder for invoice {invoice.invoice_number}"
            )

            return reminder

        except Exception as e:
            logger.error(f"Error sending reminder for invoice {invoice.id}: {e}")
            return None

    @classmethod
    def _prepare_reminder_context(cls, invoice, reminder_type, payment_schedule):
        """Prepare context data for reminder templates"""

        if payment_schedule:
            due_date = payment_schedule.due_date
            amount = payment_schedule.amount_outstanding
            installment = payment_schedule.installment_number
        else:
            due_date = invoice.due_date
            amount = invoice.amount_outstanding
            installment = None

        context = {
            'invoice': invoice,
            'customer': invoice.customer,
            'company': invoice.store.company if invoice.store else None,
            'due_date': due_date,
            'amount_due': amount,
            'total_amount': invoice.total_amount,
            'amount_paid': invoice.amount_paid,
            'days_overdue': invoice.days_overdue,
            'installment_number': installment,
            'payment_url': cls._generate_payment_url(invoice),
        }

        # Set subject based on reminder type
        subject_map = {
            'UPCOMING': f'Upcoming Payment Reminder - Invoice #{invoice.invoice_number}',
            'DUE': f'Payment Due Today - Invoice #{invoice.invoice_number}',
            'OVERDUE': f'Overdue Payment Notice - Invoice #{invoice.invoice_number}',
            'FINAL_NOTICE': f'FINAL NOTICE - Invoice #{invoice.invoice_number}',
        }

        context['subject'] = subject_map.get(reminder_type, 'Payment Reminder')
        context['reminder_type'] = reminder_type

        return context

    @classmethod
    def _send_email_reminder(cls, invoice, context):
        """Send email reminder"""
        try:
            # Render HTML and text versions
            html_message = render_to_string(
                'invoices/emails/payment_reminder.html',
                context
            )
            text_message = strip_tags(html_message)

            # Create email
            email = EmailMultiAlternatives(
                subject=context['subject'],
                body=text_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[invoice.customer.email],
            )
            email.attach_alternative(html_message, "text/html")

            # Optionally attach invoice PDF
            if hasattr(invoice, 'generate_pdf'):
                pdf = invoice.generate_pdf()
                email.attach(
                    f'Invoice_{invoice.invoice_number}.pdf',
                    pdf,
                    'application/pdf'
                )

            email.send()

            return True, None

        except Exception as e:
            return False, str(e)

    @classmethod
    def _send_sms_reminder(cls, invoice, context):
        """Send SMS reminder (implement based on your SMS provider)"""
        # Implement SMS sending logic here
        # Example using Twilio, Africa's Talking, etc.
        try:
            phone = context.get('customer').phone if context.get('customer') else None
            if not phone:
                return False, "No phone number available"

            message = f"""Payment Reminder: Invoice #{invoice.invoice_number}
Amount Due: {invoice.currency_code} {context['amount_due']}
Due Date: {context['due_date']}
Pay now: {context['payment_url']}"""

            # TODO: Implement actual SMS sending
            # sms_provider.send(phone, message)

            return True, None

        except Exception as e:
            return False, str(e)

    @classmethod
    def _generate_payment_url(cls, invoice):
        """Generate payment URL for customer"""
        # Implement based on your payment gateway
        from django.urls import reverse
        return f"{settings.SITE_URL}{reverse('invoice_payment', args=[invoice.id])}"

    @classmethod
    def _calculate_next_reminder_date(cls, current_type, invoice):
        """Calculate when next reminder should be sent"""
        type_order = ['UPCOMING', 'DUE', 'OVERDUE', 'FINAL_NOTICE']

        try:
            current_index = type_order.index(current_type)
            if current_index < len(type_order) - 1:
                next_type = type_order[current_index + 1]
                days_offset = cls.REMINDER_SCHEDULE[next_type]
                return invoice.due_date + timedelta(days=days_offset)
        except (ValueError, IndexError):
            pass

        return None

    @classmethod
    def process_due_reminders(cls):
        """
        Process all invoices and send reminders where appropriate
        Called by scheduled task (Celery/Cron)
        """
        from django.utils import timezone
        today = timezone.now().date()

        # Get all unpaid invoices
        unpaid_invoices = Invoice.objects.filter(
            sale__payment_status__in=['PENDING', 'PARTIALLY_PAID', 'OVERDUE'],
            sale__is_voided=False
        ).select_related('sale', 'customer', 'store')

        reminders_sent = 0

        for invoice in unpaid_invoices:
            # Check each payment schedule
            for schedule in invoice.payment_schedules.filter(
                    status__in=['PENDING', 'PARTIALLY_PAID', 'OVERDUE']
            ):
                days_diff = (schedule.due_date - today).days

                # Determine reminder type based on days difference
                if days_diff == 3:
                    reminder_type = 'UPCOMING'
                elif days_diff == 0:
                    reminder_type = 'DUE'
                elif days_diff == -7:
                    reminder_type = 'OVERDUE'
                elif days_diff == -14:
                    reminder_type = 'FINAL_NOTICE'
                else:
                    continue  # Not a reminder day

                # Check if reminder already sent today
                existing = PaymentReminder.objects.filter(
                    invoice=invoice,
                    payment_schedule=schedule,
                    reminder_type=reminder_type,
                    sent_at__date=today
                ).exists()

                if not existing:
                    cls.send_reminder(
                        invoice=invoice,
                        reminder_type=reminder_type,
                        payment_schedule=schedule
                    )
                    reminders_sent += 1

        logger.info(f"Processed reminders: {reminders_sent} sent")
        return reminders_sent