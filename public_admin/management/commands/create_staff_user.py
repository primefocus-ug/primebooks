from django.core.management.base import BaseCommand
from public_admin.models import PublicStaffUser


class Command(BaseCommand):
    help = 'Create a public staff user for analytics access'

    def add_arguments(self, parser):
        parser.add_argument('username', type=str)
        parser.add_argument('email', type=str)
        parser.add_argument('password', type=str)

    def handle(self, *args, **options):
        username = options['username']
        email = options['email']
        password = options['password']

        if PublicStaffUser.objects.filter(username=username).exists():
            self.stdout.write(self.style.ERROR(f'User {username} already exists'))
            return

        user = PublicStaffUser.objects.create(
            username=username,
            email=email,
        )
        user.set_password(password)
        user.save()

        self.stdout.write(self.style.SUCCESS(f'Successfully created staff user: {username}'))