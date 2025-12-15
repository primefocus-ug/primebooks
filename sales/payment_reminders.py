from django.db import models
from django.utils import timezone
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)


class PaymentReminder(models.Model):
    """Track payment reminders for invoices"""

    REMINDER_TYPES = [
        ('BEFORE_DUE', 'Before Due Date'),
        ('ON_DUE', 'On Due Date'),
        ('OVERDUE_3', '3 Days Overdue'),
        ('OVERDUE_7', '7 Days Overdue'),
        ('OVERDUE_14', '14 Days Overdue'),
        ('OVERDUE_30', '30 Days Overdue'),
        ('MANUAL', 'Manual Reminder'),
    ]

    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('SENT', 'Sent'),
        ('FAILED', 'Failed'),
        ('CANCELLED', 'Cancelled'),
    ]

    sale = models.ForeignKey(
        'Sale',
        on_delete=models.CASCADE,
        related_name='payment_reminders'
    )

    reminder_type = models.CharField(
        max_length=20,
        choices=REMINDER_TYPES,
        default='MANUAL'
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='PENDING'
    )

    scheduled_for = models.DateTimeField(
        help_text="When this reminder should be sent"
    )

    sent_at = models.DateTimeField(
        null=True,
        blank=True
    )

    sent_to = models.EmailField()

    subject = models.CharField(max_length=200)
    message = models.TextField()

    error_message = models.TextField(
        blank=True,
        null=True
    )

    created_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_reminders'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-scheduled_for']
        indexes = [
            models.Index(fields=['sale', 'status']),
            models.Index(fields=['scheduled_for', 'status']),
            models.Index(fields=['reminder_type']),
        ]

    def __str__(self):
        return f"{self.get_reminder_type_display()} - {self.sale.document_number}"

    def send(self):
        """Send the reminder email"""
        try:
            if self.status == 'SENT':
                logger.warning(f"Reminder {self.id} already sent")
                return False

            # Prepare email context
            context = {
                'reminder': self,
                'sale': self.sale,
                'customer': self.sale.customer,
                'invoice': self.sale.invoice_detail if hasattr(self.sale, 'invoice_detail') else None,
                'company': self.sale.store.company,
                'store': self.sale.store,
                'days_overdue': self.sale.days_overdue,
                'amount_outstanding': self.sale.amount_outstanding,
            }

            # Render email
            html_message = render_to_string('sales/emails/payment_reminder.html', context)
            text_message = render_to_string('sales/emails/payment_reminder.txt', context)

            # Send email
            email = EmailMessage(
                subject=self.subject,
                body=text_message,
                to=[self.sent_to],
                from_email=self.sale.store.company.email,
            )
            email.content_subtype = 'html'
            email.body = html_message
            email.send(fail_silently=False)

            # Update status
            self.status = 'SENT'
            self.sent_at = timezone.now()
            self.save(update_fields=['status', 'sent_at'])

            logger.info(f"Payment reminder sent: {self.id} to {self.sent_to}")
            return True

        except Exception as e:
            logger.error(f"Error sending reminder {self.id}: {e}", exc_info=True)
            self.status = 'FAILED'
            self.error_message = str(e)
            self.save(update_fields=['status', 'error_message'])
            return False

    @classmethod
    def create_automatic_reminders(cls, sale):
        """Create automatic reminders for an invoice"""
        if sale.document_type != 'INVOICE':
            return []

        if not sale.customer or not sale.customer.email:
            logger.warning(f"Cannot create reminders for sale {sale.id}: No customer email")
            return []

        if not sale.due_date:
            logger.warning(f"Cannot create reminders for sale {sale.id}: No due date")
            return []

        reminders = []

        # Before due date (3 days before)
        before_due = sale.due_date - timedelta(days=3)
        if before_due > timezone.now().date():
            reminder = cls.objects.create(
                sale=sale,
                reminder_type='BEFORE_DUE',
                scheduled_for=timezone.make_aware(
                    timezone.datetime.combine(before_due, timezone.datetime.min.time())
                ),
                sent_to=sale.customer.email,
                subject=f"Reminder: Invoice {sale.document_number} due in 3 days",
                message=f"Your invoice {sale.document_number} is due on {sale.due_date}. Outstanding amount: {sale.amount_outstanding} UGX",
            )
            reminders.append(reminder)

        # On due date
        on_due = sale.due_date
        reminder = cls.objects.create(
            sale=sale,
            reminder_type='ON_DUE',
            scheduled_for=timezone.make_aware(
                timezone.datetime.combine(on_due, timezone.datetime.min.time())
            ),
            sent_to=sale.customer.email,
            subject=f"Payment Due: Invoice {sale.document_number}",
            message=f"Your invoice {sale.document_number} is due today. Outstanding amount: {sale.amount_outstanding} UGX",
        )
        reminders.append(reminder)

        # Overdue reminders (3, 7, 14, 30 days)
        for days, reminder_type in [(3, 'OVERDUE_3'), (7, 'OVERDUE_7'), (14, 'OVERDUE_14'), (30, 'OVERDUE_30')]:
            overdue_date = sale.due_date + timedelta(days=days)
            reminder = cls.objects.create(
                sale=sale,
                reminder_type=reminder_type,
                scheduled_for=timezone.make_aware(
                    timezone.datetime.combine(overdue_date, timezone.datetime.min.time())
                ),
                sent_to=sale.customer.email,
                subject=f"Overdue Invoice: {sale.document_number} - {days} days past due",
                message=f"Your invoice {sale.document_number} is {days} days overdue. Outstanding amount: {sale.amount_outstanding} UGX",
            )
            reminders.append(reminder)

        logger.info(f"Created {len(reminders)} automatic reminders for sale {sale.id}")
        return reminders

    @classmethod
    def send_pending_reminders(cls):
        """Send all pending reminders that are due"""
        now = timezone.now()

        pending_reminders = cls.objects.filter(
            status='PENDING',
            scheduled_for__lte=now
        ).select_related('sale', 'sale__customer')

        sent_count = 0
        failed_count = 0

        for reminder in pending_reminders:
            # Check if invoice is still unpaid
            if reminder.sale.payment_status in ['PAID', 'COMPLETED']:
                reminder.status = 'CANCELLED'
                reminder.save(update_fields=['status'])
                continue

            # Send reminder
            if reminder.send():
                sent_count += 1
            else:
                failed_count += 1

        logger.info(f"Sent {sent_count} reminders, {failed_count} failed")
        return sent_count, failed_count