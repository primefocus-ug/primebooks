from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import transaction, connection
from django.contrib.auth import get_user_model
from django_tenants.utils import schema_context, get_tenant_model
import getpass

User = get_user_model()
Tenant = get_tenant_model()


class Command(BaseCommand):
    help = 'Create or manage SaaS admin users (runs on tenant schemas)'

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
        parser.add_argument(
            '--schema',
            type=str,
            help='Tenant schema name (default: all tenants)',
            default=None
        )

    def handle(self, *args, **options):
        schema_name = options['schema']

        # Decide which schemas to operate on
        if schema_name:
            tenants = [Tenant.objects.get(schema_name=schema_name)]
        else:
            tenants = Tenant.objects.exclude(schema_name='public')  # skip public schema

        for tenant in tenants:
            with schema_context(tenant.schema_name):
                self.stdout.write(self.style.SUCCESS(f'Running on tenant schema: {tenant.schema_name}'))

                if options['list']:
                    self.list_saas_admins()
                    continue

                if options['activate']:
                    self.activate_saas_admin(options['activate'])
                    continue

                if options['deactivate']:
                    self.deactivate_saas_admin(options['deactivate'])
                    continue

                if options['delete']:
                    self.delete_saas_admin(options['delete'])
                    continue

                self.create_saas_admin(options)

    def create_saas_admin(self, options):
        email = options['email']
        username = options['username']
        first_name = options['first_name']
        last_name = options['last_name']
        force = options['force']

        try:
            existing_saas_admins = User.objects.filter(is_saas_admin=True)
            if existing_saas_admins.exists() and not force:
                self.stdout.write(self.style.WARNING(
                    f'SaaS admin already exists: {", ".join([u.email for u in existing_saas_admins])}'
                ))
                self.stdout.write(self.style.WARNING('Use --force to create another one or --list to see existing admins'))
                return

            if User.objects.filter(email=email).exists() and not force:
                self.stdout.write(self.style.ERROR(f'User with email {email} already exists'))
                return

            if User.objects.filter(username=username).exclude(email=email).exists():
                username = f"{username}_{User.objects.count() + 1}"
                self.stdout.write(self.style.WARNING(f'Username taken, using: {username}'))

            password = options['password'] or getpass.getpass('Password for SaaS admin: ') \
                       or getattr(settings, 'DEFAULT_SAAS_ADMIN_PASSWORD', 'saas_admin_2024')

            with transaction.atomic():
                user = User.objects.filter(email=email).first()
                if user and force:
                    # update existing
                    user.is_saas_admin = True
                    user.is_hidden = True
                    user.is_superuser = True
                    user.is_staff = True
                    user.can_access_all_companies = True
                    user.user_type = 'SAAS_ADMIN'
                    user.username = username
                    user.first_name = first_name
                    user.last_name = last_name
                    user.set_password(password)
                    user.save()
                    self.stdout.write(self.style.SUCCESS(f'✓ Updated SaaS admin: {user.email}'))
                elif not user:
                    # create new
                    saas_admin = User.objects.create_saas_admin(
                        email=email,
                        username=username,
                        password=password,
                        first_name=first_name,
                        last_name=last_name
                    )
                    self.stdout.write(self.style.SUCCESS(f'✓ Created SaaS admin: {saas_admin.email}'))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error: {str(e)}'))
            import traceback
            self.stdout.write(self.style.ERROR(traceback.format_exc()))

    def list_saas_admins(self):
        admins = User.objects.filter(is_saas_admin=True)
        if not admins.exists():
            self.stdout.write(self.style.WARNING('No SaaS admins found'))
            return

        for a in admins:
            status = "Active" if a.is_active else "Inactive"
            self.stdout.write(f'{a.email} ({a.username}) - {status}')

    def activate_saas_admin(self, email):
        try:
            admin = User.objects.get(email=email, is_saas_admin=True)
            admin.is_active = True
            admin.save(update_fields=['is_active'])
            self.stdout.write(self.style.SUCCESS(f'Activated SaaS admin: {email}'))
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'SaaS admin not found: {email}'))

    def deactivate_saas_admin(self, email):
        try:
            admin = User.objects.get(email=email, is_saas_admin=True)
            admin.is_active = False
            admin.save(update_fields=['is_active'])
            self.stdout.write(self.style.SUCCESS(f'Deactivated SaaS admin: {email}'))
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'SaaS admin not found: {email}'))

    def delete_saas_admin(self, email):
        try:
            admin = User.objects.get(email=email, is_saas_admin=True)
            confirm = input(f'Type "yes" to delete SaaS admin "{email}": ')
            if confirm.lower() == 'yes':
                admin.delete()
                self.stdout.write(self.style.SUCCESS(f'Deleted SaaS admin: {email}'))
            else:
                self.stdout.write(self.style.WARNING('Operation cancelled'))
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'SaaS admin not found: {email}'))
