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
        parser.add_argument(
            '--assign-role',
            type=str,
            help='Assign a specific role to the SaaS admin (role name)',
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
        role_name = options['assign_role']

        try:
            existing_saas_admins = User.objects.filter(is_saas_admin=True)
            if existing_saas_admins.exists() and not force:
                self.stdout.write(self.style.WARNING(
                    f'SaaS admin already exists: {", ".join([u.email for u in existing_saas_admins])}'
                ))
                self.stdout.write(
                    self.style.WARNING('Use --force to create another one or --list to see existing admins'))
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
                    # update existing user to be SaaS admin
                    user.is_saas_admin = True
                    user.is_hidden = True
                    user.is_superuser = True
                    user.is_staff = True
                    user.can_access_all_companies = True
                    user.username = username
                    user.first_name = first_name
                    user.last_name = last_name
                    user.set_password(password)
                    user.save()

                    # Assign role if specified
                    if role_name:
                        self.assign_role_to_user(user, role_name)

                    self.stdout.write(self.style.SUCCESS(f'✓ Updated SaaS admin: {user.email}'))

                elif not user:
                    # create new SaaS admin
                    saas_admin = User.objects.create_saas_admin(
                        email=email,
                        username=username,
                        password=password,
                        first_name=first_name,
                        last_name=last_name
                    )

                    # Assign role if specified
                    if role_name:
                        self.assign_role_to_user(saas_admin, role_name)

                    self.stdout.write(self.style.SUCCESS(f'✓ Created SaaS admin: {saas_admin.email}'))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error: {str(e)}'))
            import traceback
            self.stdout.write(self.style.ERROR(traceback.format_exc()))

    def assign_role_to_user(self, user, role_name):
        """Assign a role to the user using your role-based system"""
        try:
            from accounts.models import Role
            from django.contrib.auth.models import Group

            # Try to find the role by name
            role = Role.objects.filter(
                group__name__iexact=role_name,
                is_active=True
            ).first()

            if not role:
                # Try to find by group name directly
                group = Group.objects.filter(name__iexact=role_name).first()
                if group:
                    # Create a role for this group if it doesn't exist
                    role, created = Role.objects.get_or_create(
                        group=group,
                        defaults={
                            'description': f'Auto-created role for {role_name}',
                            'is_system_role': True,
                            'priority': 100,  # High priority for SaaS admins
                            'created_by': user
                        }
                    )

            if role:
                # Use the role assignment method from your model
                user.assign_role(role)
                self.stdout.write(self.style.SUCCESS(f'✓ Assigned role: {role.group.name}'))
            else:
                self.stdout.write(self.style.WARNING(f'Role not found: {role_name}'))

        except Exception as e:
            self.stdout.write(self.style.WARNING(f'Could not assign role {role_name}: {str(e)}'))

    def list_saas_admins(self):
        """List all SaaS admins with their roles"""
        admins = User.objects.filter(is_saas_admin=True).prefetch_related('groups__role')
        if not admins.exists():
            self.stdout.write(self.style.WARNING('No SaaS admins found'))
            return

        self.stdout.write(self.style.SUCCESS('SaaS Administrators:'))
        self.stdout.write('-' * 80)

        for admin in admins:
            status = "Active" if admin.is_active else "Inactive"
            roles = admin.role_names

            self.stdout.write(f'Email:    {admin.email}')
            self.stdout.write(f'Username: {admin.username}')
            self.stdout.write(f'Name:     {admin.get_full_name()}')
            self.stdout.write(f'Status:   {status}')
            self.stdout.write(f'Roles:    {", ".join(roles) if roles else "No roles assigned"}')
            self.stdout.write(f'Company:  {admin.company.name if admin.company else "No company"}')
            self.stdout.write(f'Last Login: {admin.last_login or "Never"}')
            self.stdout.write('-' * 80)

    def activate_saas_admin(self, email):
        """Activate a SaaS admin by email"""
        try:
            admin = User.objects.get(email=email, is_saas_admin=True)
            admin.is_active = True
            admin.save(update_fields=['is_active'])
            self.stdout.write(self.style.SUCCESS(f'Activated SaaS admin: {email}'))
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'SaaS admin not found: {email}'))

    def deactivate_saas_admin(self, email):
        """Deactivate a SaaS admin by email"""
        try:
            admin = User.objects.get(email=email, is_saas_admin=True)
            admin.is_active = False
            admin.save(update_fields=['is_active'])
            self.stdout.write(self.style.SUCCESS(f'Deactivated SaaS admin: {email}'))
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'SaaS admin not found: {email}'))

    def delete_saas_admin(self, email):
        """Delete a SaaS admin by email (with confirmation)"""
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

    def get_saas_admin_stats(self):
        """Get statistics about SaaS admins (optional enhancement)"""
        total_admins = User.objects.filter(is_saas_admin=True).count()
        active_admins = User.objects.filter(is_saas_admin=True, is_active=True).count()
        hidden_admins = User.objects.filter(is_saas_admin=True, is_hidden=True).count()

        self.stdout.write(self.style.SUCCESS('SaaS Admin Statistics:'))
        self.stdout.write(f'Total SaaS Admins: {total_admins}')
        self.stdout.write(f'Active SaaS Admins: {active_admins}')
        self.stdout.write(f'Hidden SaaS Admins: {hidden_admins}')