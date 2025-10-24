from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from .models import ServiceAppointment, ServiceExecution, ServiceDiscount


@receiver(pre_save, sender=ServiceAppointment)
def calculate_appointment_total(sender, instance, **kwargs):
    """Calculate total amount before saving appointment"""
    if instance.service:
        instance.price = instance.service.calculate_price(
            duration_minutes=instance.duration_minutes,
            tier_level=instance.pricing_tier.tier_level if instance.pricing_tier else None
        )

        # Apply discount
        instance.price -= instance.discount_amount

        # Calculate tax
        instance.tax_amount = instance.service.calculate_tax(instance.price)

        # Calculate total
        if instance.service.is_tax_inclusive:
            instance.total_amount = instance.price
        else:
            instance.total_amount = instance.price + instance.tax_amount


@receiver(post_save, sender=ServiceExecution)
def update_execution_status(sender, instance, created, **kwargs):
    """Update related appointment status when execution status changes"""
    if instance.appointment and not created:
        if instance.status == ServiceExecution.COMPLETED:
            instance.appointment.status = ServiceAppointment.COMPLETED
            instance.appointment.save()
        elif instance.status == ServiceExecution.CANCELLED:
            instance.appointment.status = ServiceAppointment.CANCELLED
            instance.appointment.save()


@receiver(post_save, sender=ServiceAppointment)
def send_appointment_confirmation(sender, instance, created, **kwargs):
    """Send confirmation email/SMS when appointment is created or confirmed"""
    if created or instance.status == ServiceAppointment.CONFIRMED:
        # Implement email/SMS sending logic here
        # Example: send_email(instance.customer_email, 'Appointment Confirmed', ...)
        pass
