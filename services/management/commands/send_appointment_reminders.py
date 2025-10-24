from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from services.models import ServiceAppointment


class Command(BaseCommand):
    help = 'Send reminders for upcoming appointments'

    def handle(self, *args, **options):
        # Get appointments scheduled for tomorrow that haven't been reminded
        tomorrow = timezone.now().date() + timedelta(days=1)

        appointments = ServiceAppointment.objects.filter(
            scheduled_date=tomorrow,
            status__in=[ServiceAppointment.SCHEDULED, ServiceAppointment.CONFIRMED],
            reminder_sent=False
        )

        for appointment in appointments:
            # Implement your reminder sending logic (email, SMS, push notification)
            # Example: send_reminder(appointment)

            appointment.reminder_sent = True
            appointment.reminder_sent_at = timezone.now()
            appointment.save()

            self.stdout.write(
                self.style.SUCCESS(f'Reminder sent for appointment {appointment.appointment_number}')
            )
