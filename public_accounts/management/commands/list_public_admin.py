from django.core.management.base import BaseCommand
from public_accounts.models import PublicUser


class Command(BaseCommand):
    help = 'List all public admin users'

    def handle(self, *args, **options):
        users = PublicUser.objects.all().order_by('-date_joined')

        self.stdout.write(self.style.SUCCESS(f'\nTotal Users: {users.count()}\n'))
        self.stdout.write('-' * 100)
        self.stdout.write(
            f"{'Identifier':<25} {'Email':<30} {'Name':<25} {'Role':<15} {'Active'}"
        )
        self.stdout.write('-' * 100)

        for user in users:
            active = '✓' if user.is_active else '✗'
            self.stdout.write(
                f"{user.identifier:<25} {user.email:<30} {user.get_full_name():<25} "
                f"{user.get_role_display():<15} {active}"
            )

        self.stdout.write('-' * 100)