from django.core.management.base import BaseCommand
from public_accounts.models import PublicUser


class Command(BaseCommand):
    help = 'Create a public admin user'

    def add_arguments(self, parser):
        parser.add_argument('email', type=str, help='Email address')
        parser.add_argument('username', type=str, help='Username')
        parser.add_argument('--first-name', type=str, default='')
        parser.add_argument('--last-name', type=str, default='')
        parser.add_argument('--phone', type=str, default='')
        parser.add_argument('--superuser', action='store_true', help='Create as superuser')

    def handle(self, *args, **options):
        email = options['email']
        username = options['username']

        if PublicUser.objects.filter(email=email).exists():
            self.stdout.write(self.style.ERROR(f'User with email {email} already exists'))
            return

        if PublicUser.objects.filter(username=username).exists():
            self.stdout.write(self.style.ERROR(f'User with username {username} already exists'))
            return

        if options['superuser']:
            user = PublicUser.objects.create_superuser(
                email=email,
                username=username,
                first_name=options.get('first_name', ''),
                last_name=options.get('last_name', ''),
                phone=options.get('phone', ''),
            )
            self.stdout.write(self.style.SUCCESS(f'Superuser created successfully!'))
        else:
            user = PublicUser.objects.create_user(
                email=email,
                username=username,
                first_name=options.get('first_name', ''),
                last_name=options.get('last_name', ''),
                phone=options.get('phone', ''),
            )
            self.stdout.write(self.style.SUCCESS(f'User created successfully!'))

        self.stdout.write(self.style.SUCCESS(f'Login Identifier: {user.identifier}'))
        self.stdout.write(self.style.WARNING(f'Credentials have been sent to {user.email}'))
        self.stdout.write(self.style.WARNING(f'User must change password on first login'))

