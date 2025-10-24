from django.core.management.base import BaseCommand
from django.conf import settings
from accounts.models import CustomUser
from django.contrib.auth import get_user_model
from django.db import transaction
import getpass

User = get_user_model()


class Command(BaseCommand):
    help = 'Create or manage SaaS admin users'

    def add_arguments(self, parser):
        parser.add_argument(
            '--email',
            type=str,
            help='Email for the SaaS admin',
            default=getattr(settings, 'DEFAULT_SAAS_ADMIN_EMAIL', 'admin@saas.com')
        )
        parser.add_argument(
            '--username',
            type=str,
            help='Username for the SaaS admin',
            default='saas_admin'
        )
        parser.add_argument(
            '--password',
            type=str,
            help='Password for the SaaS admin (if not provided, will prompt)'
        )
        parser.add_argument(
            '--first-name',
            type=str,
            help='First name for the SaaS admin',
            default='SaaS'
        )
        parser.add_argument(
            '--last-name',
            type=str,
            help='Last name for the SaaS admin',
            default='Administrator'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force creation even if SaaS admin already exists'
        )
        parser.add_argument(
            '--list',
            action='store_true',
            help='List all existing SaaS admins'
        )
        parser.add_argument(
            '--activate',
            type=str,
            help='Activate SaaS admin by email'
        )
        parser.add_argument(
            '--deactivate',
            type=str,
            help='Deactivate SaaS admin by email'
        )
        parser.add_argument(
            '--delete',
            type=str,
            help='Delete SaaS admin by email (use with caution)'
        )

    def handle(self, *args, **options):
        # List existing SaaS admins
        if options['list']:
            self.list_saas_admins()
            return

        # Activate SaaS admin
        if options['activate']:
            self.activate_saas_admin(options['activate'])
            return

        # Deactivate SaaS admin
        if options['deactivate']:
            self.deactivate_saas_admin(options['deactivate'])
            return

        # Delete SaaS admin
        if options['delete']:
            self.delete_saas_admin(options['delete'])
            return

        # Create SaaS admin
        self.create_saas_admin(options)

    def create_saas_admin(self, options):
        """Create a new SaaS admin"""
        email = options['email']
        username = options['username']
        first_name = options['first_name']
        last_name = options['last_name']
        force = options['force']

        # Check if SaaS admin already exists
        existing_saas_admins = User.objects.filter(is_saas_admin=True)
        if existing_saas_admins.exists() and not force:
            self.stdout.write(
                self.style.WARNING(
                    f'SaaS admin already exists: {", ".join([u.email for u in existing_saas_admins])}'
                )
            )
            self.stdout.write(
                self.style.WARNING(
                    'Use --force to create another one or --list to see existing admins'
                )
            )
            return

        # Check if email is already in use
        if User.objects.filter(email=email).exists():
            if not force:
                self.stdout.write(
                    self.style.ERROR(f'User with email {email} already exists')
                )
                return
            else:
                self.stdout.write(
                    self.style.WARNING(f'User with email {email} already exists - updating to SaaS admin')
                )

        # Check if username is already in use
        if User.objects.filter(username=username).exclude(email=email).exists():
            username = f"{username}_{User.objects.count() + 1}"
            self.stdout.write(
                self.style.WARNING(f'Username was taken, using: {username}')
            )

        # Get password
        password = options['password']
        if not password:
            password = getpass.getpass('Password for SaaS admin: ')
            if not password:
                password = getattr(settings, 'DEFAULT_SAAS_ADMIN_PASSWORD', 'saas_admin_2024')
                self.stdout.write(
                    self.style.WARNING(f'No password provided, using default password')
                )

        # Check if we have companies
        try:
            from company.models import Company
            if not Company.objects.exists():
                self.stdout.write(
                    self.style.ERROR(
                        'No companies exist. Please create at least one company first.'
                    )
                )
                return
        except ImportError:
            self.stdout.write(
                self.style.ERROR(
                    'Company model not found. Please ensure the company app is properly set up.'
                )
            )
            return

        try:
            with transaction.atomic():
                # Check if user exists and update or create new
                existing_user = User.objects.filter(email=email).first()

                if existing_user and force:
                    # Update existing user to SaaS admin
                    existing_user.is_saas_admin = True
                    existing_user.is_hidden = True
                    existing_user.is_superuser = True
                    existing_user.is_staff = True
                    existing_user.can_access_all_companies = True
                    existing_user.user_type = 'SAAS_ADMIN'
                    existing_user.username = username
                    existing_user.first_name = first_name
                    existing_user.last_name = last_name
                    if password:
                        existing_user.set_password(password)
                    existing_user.save()

                    self.stdout.write(
                        self.style.SUCCESS(f'Updated existing user to SaaS admin: {existing_user.email}')
                    )
                else:
                    # Create new SaaS admin
                    saas_admin = User.objects.create_saas_admin(
                        email=email,
                        password=password,
                        username=username,
                        first_name=first_name,
                        last_name=last_name
                    )

                    self.stdout.write(
                        self.style.SUCCESS(f'Successfully created SaaS admin: {saas_admin.email}')
                    )

                self.stdout.write(
                    self.style.SUCCESS('SaaS admin setup completed!')
                )
                self.stdout.write(f'  Email: {email}')
                self.stdout.write(f'  Username: {username}')
                self.stdout.write(f'  Name: {first_name} {last_name}')
                self.stdout.write(f'  Hidden: Yes')
                self.stdout.write(f'  Can access all companies: Yes')

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error creating SaaS admin: {str(e)}')
            )

    def list_saas_admins(self):
        """List all existing SaaS admins"""
        saas_admins = User.objects.filter(is_saas_admin=True)

        if not saas_admins.exists():
            self.stdout.write(self.style.WARNING('No SaaS admins found'))
            return

        self.stdout.write(self.style.SUCCESS(f'Found {saas_admins.count()} SaaS admin(s):'))
        self.stdout.write('-' * 60)

        for admin in saas_admins:
            status = "Active" if admin.is_active else "Inactive"
            self.stdout.write(f'Email: {admin.email}')
            self.stdout.write(f'Username: {admin.username}')
            self.stdout.write(f'Name: {admin.get_full_name()}')
            self.stdout.write(f'Status: {status}')
            self.stdout.write(f'Last Login: {admin.last_login or "Never"}')
            self.stdout.write(f'Date Joined: {admin.date_joined}')
            self.stdout.write(f'Hidden: {admin.is_hidden}')
            self.stdout.write(f'Can Access All Companies: {admin.can_access_all_companies}')
            self.stdout.write('-' * 60)

    def activate_saas_admin(self, email):
        """Activate a SaaS admin"""
        try:
            admin = User.objects.get(email=email, is_saas_admin=True)
            admin.is_active = True
            admin.save(update_fields=['is_active'])
            self.stdout.write(
                self.style.SUCCESS(f'Activated SaaS admin: {email}')
            )
        except User.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'SaaS admin with email {email} not found')
            )

    def deactivate_saas_admin(self, email):
        """Deactivate a SaaS admin"""
        try:
            admin = User.objects.get(email=email, is_saas_admin=True)
            admin.is_active = False
            admin.save(update_fields=['is_active'])
            self.stdout.write(
                self.style.SUCCESS(f'Deactivated SaaS admin: {email}')
            )
        except User.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'SaaS admin with email {email} not found')
            )

    def delete_saas_admin(self, email):
        """Delete a SaaS admin (with confirmation)"""
        try:
            admin = User.objects.get(email=email, is_saas_admin=True)

            # Confirmation prompt
            confirm = input(f'Are you sure you want to delete SaaS admin "{email}"? '
                            f'This action cannot be undone. Type "yes" to confirm: ')

            if confirm.lower() != 'yes':
                self.stdout.write(self.style.WARNING('Operation cancelled'))
                return

            admin.delete()
            self.stdout.write(
                self.style.SUCCESS(f'Deleted SaaS admin: {email}')
            )
        except User.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'SaaS admin with email {email} not found')
            )