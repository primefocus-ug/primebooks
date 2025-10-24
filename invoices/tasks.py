
from celery import shared_task
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from .models import Invoice
import logging

logger = logging.getLogger('invoices')

@shared_task
def send_invoice_email(invoice_id, recipient_email=None):
    """Send invoice via email"""
    try:
        invoice = Invoice.objects.get(id=invoice_id)
        
        if not recipient_email and invoice.sale and invoice.sale.customer:
            recipient_email = invoice.sale.customer.email
        
        if not recipient_email:
            logger.error(f"No email address for invoice {invoice.invoice_number}")
            return False
        
        subject = f"Invoice {invoice.invoice_number} from {settings.INVOICE_SETTINGS['COMPANY_INFO']['name']}"
        
        html_message = render_to_string('invoices/email/invoice_email.html', {
            'invoice': invoice,
            'company_info': settings.INVOICE_SETTINGS['COMPANY_INFO']
        })
        
        send_mail(
            subject=subject,
            message='',
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[recipient_email],
            html_message=html_message,
            fail_silently=False
        )
        
        logger.info(f"Invoice {invoice.invoice_number} sent to {recipient_email}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send invoice {invoice_id}: {str(e)}")
        return False


@shared_task
def send_payment_reminder(invoice_id):
    """Send payment reminder for overdue invoices"""
    try:
        invoice = Invoice.objects.get(id=invoice_id)
        
        if not invoice.is_overdue:
            return False
            
        if not (invoice.sale and invoice.sale.customer and invoice.sale.customer.email):
            return False
        
        subject = f"Payment Reminder - Invoice {invoice.invoice_number}"
        
        html_message = render_to_string('invoices/email/payment_reminder.html', {
            'invoice': invoice,
            'company_info': settings.INVOICE_SETTINGS['COMPANY_INFO']
        })
        
        send_mail(
            subject=subject,
            message='',
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[invoice.sale.customer.email],
            html_message=html_message,
            fail_silently=False
        )
        
        logger.info(f"Payment reminder sent for invoice {invoice.invoice_number}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send payment reminder for invoice {invoice_id}: {str(e)}")
        return False


# @shared_task
# def fiscalize_invoice_async(invoice_id, user_id):
#     """Fiscalize invoice asynchronously with EFRIS"""
#     try:
#         from django.contrib.auth import get_user_model
#         User = get_user_model()
#
#         invoice = Invoice.objects.get(id=invoice_id)
#         user = User.objects.get(id=user_id)
#
#         # Simulate EFRIS API call
#         # In real implementation, this would call the URA EFRIS API
#         success = invoice.fiscalize(user)
#
#         if success:
#             logger.info(f"Invoice {invoice.invoice_number} fiscalized successfully")
#         else:
#             logger.error(f"Failed to fiscalize invoice {invoice.invoice_number}")
#
#         return success
#
#     except Exception as e:
#         logger.error(f"Fiscalization task failed for invoice {invoice_id}: {str(e)}")
#         return False

