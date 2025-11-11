import os
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db import transaction, connection
from django.utils.text import slugify
from django.utils import timezone
from datetime import timedelta
from company.models import Company, SubscriptionPlan, Domain
from django_tenants.utils import schema_context, tenant_context
from django.core.management import call_command

User = get_user_model()


class Command(BaseCommand):
    help = 'Create a superuser with company association for multi-tenant POS system'

    def add_arguments(self, parser):
        parser.add_argument(
            '--email',
            help='Email address for the superuser',
        )
        parser.add_argument(
            '--username',
            help='Username for the superuser',
        )
        parser.add_argument(
            '--company-id',
            help='Company ID to associate with the superuser',
        )
        parser.add_argument(
            '--company-name',
            help='Company name (if creating new company)',
        )
        parser.add_argument(
            '--schema-name',
            help='Schema name for the tenant (if creating new company)',
        )
        parser.add_argument(
            '--domain',
            help='Domain for the tenant (if creating new company)',
        )
        parser.add_argument(
            '--assign-role',
            help='Assign a specific role to the superuser (role name)',
        )
        parser.add_argument(
            '--make-company-admin',
            action='store_true',
            help='Make the user a company admin',
        )
        parser.add_argument(
            '--list-roles',
            action='store_true',
            help='List available roles for the company',
        )

    def handle(self, *args, **options):
        email = options.get('email')
        username = options.get('username')
        company_id = options.get('company_id')
        company_name = options.get('company_name')
        schema_name = options.get('schema_name')
        domain = options.get('domain')
        role_name = options.get('assign_role')
        make_company_admin = options.get('make_company_admin')
        list_roles = options.get('list_roles')

        # Handle company selection/creation
        company = None

        if company_id:
            try:
                company = Company.objects.get(company_id=company_id)
                self.stdout.write(f'Using existing company: {company.display_name} ({company.company_id})')
                self._ensure_tenant_schema(company)
            except Company.DoesNotExist:
                raise CommandError(f'Company with ID {company_id} does not exist')

        elif company_name:
            # Creating new company - PASS EMAIL TO COMPANY CREATION
            company = self._create_new_company(company_name, email, schema_name, domain)

        else:
            # Show available companies
            companies = Company.objects.all()
            if companies.exists():
                self.stdout.write('Available companies:')
                for comp in companies[:10]:
                    self.stdout.write(f'  {comp.company_id}: {comp.display_name} ({comp.status})')

                if companies.count() > 10:
                    self.stdout.write(f'  ... and {companies.count() - 10} more')

                company_choice = input('Enter company ID (or press Enter to create new): ')
                if company_choice:
                    try:
                        company = Company.objects.get(company_id=company_choice)
                        self.stdout.write(f'Selected company: {company.display_name}')
                        self._ensure_tenant_schema(company)
                    except Company.DoesNotExist:
                        raise CommandError('Invalid company ID')
                else:
                    company_name = input('Enter new company name: ')
                    company = self._create_new_company(company_name, email, schema_name, domain)
            else:
                company_name = input('No companies exist. Enter new company name: ')
                company = self._create_new_company(company_name, email, schema_name, domain)

        # List roles if requested
        if list_roles:
            self._list_available_roles(company)
            return

        # Get user email if not provided
        if not email:
            email = input('User Email Address: ')

        if not username:
            username = input('Username: ')

        # Role selection - IMPROVED
        if not role_name:
            self.stdout.write("Available roles:")
            self._list_available_roles(company, brief=True)
            role_input = input('Enter role name (press Enter for System Administrator): ').strip()
            role_name = role_input if role_input else 'System Administrator'

        # Validate role name input
        if role_name.lower() in ['y', 'yes', 'true', 'make_company_admin', 'n', 'no', 'false']:
            self.stdout.write(self.style.WARNING('Please enter a valid role name from the list above'))
            self._list_available_roles(company, brief=True)
            role_input = input('Enter role name: ').strip()
            role_name = role_input if role_input else 'System Administrator'

        # Company admin confirmation
        if not make_company_admin:
            make_admin = input('Make company admin? (y/N): ').strip().lower()
            make_company_admin = make_admin in ['y', 'yes']

        # Get password
        import getpass
        password = getpass.getpass('Password: ')
        password_confirm = getpass.getpass('Password (again): ')

        if password != password_confirm:
            raise CommandError('Passwords do not match')

        # Create superuser
        try:
            with transaction.atomic():
                with tenant_context(company):
                    # Use the fixed user creation method
                    user = self._create_superuser_fix(
                        email=email,
                        username=username,
                        password=password,
                        company=company,
                        make_company_admin=make_company_admin
                    )

                    # Assign role
                    self._assign_role_to_user(user, role_name)

                    self.stdout.write(self.style.SUCCESS('Superuser created successfully!'))
                    self.stdout.write(f'  Email: {user.email}')
                    self.stdout.write(f'  Username: {user.username}')
                    self.stdout.write(f'  Company: {company.display_name} ({company.company_id})')
                    self.stdout.write(f'  Company Admin: {user.company_admin}')
                    self.stdout.write(f'  Assigned Role: {role_name}')
                    self.stdout.write(f'  Display Role: {user.display_role}')
                    self.stdout.write(f'  Company Status: {company.status}')

                    primary_domain = company.domains.filter(is_primary=True).first()
                    if primary_domain:
                        self.stdout.write(f'  Primary Domain: {primary_domain.domain}')

        except Exception as e:
            raise CommandError(f'Error creating superuser: {str(e)}')

    def _create_superuser_fix(self, email, username, password, company, make_company_admin):
        """Create superuser with proper role assignment and fix for user_type issues."""
        try:
            # First try the normal way
            user = User.objects.create_user(
                email=email,
                username=username,
                password=password,
                company=company,
                is_staff=True,
                is_superuser=True,
                is_active=True,
                company_admin=make_company_admin,
            )
            return user

        except Exception as e:
            # If there's a user_type issue, try alternative approach
            self.stdout.write(self.style.WARNING(f'First attempt failed: {str(e)}'))
            self.stdout.write('Trying alternative user creation method...')

            # Alternative method - manually create user
            user = User(
                email=email,
                username=username,
                company=company,
                is_staff=True,
                is_superuser=True,
                is_active=True,
                company_admin=make_company_admin,
            )
            user.set_password(password)
            user.save()

            return user

    def _create_new_company(self, company_name, user_email, schema_name=None, domain=None):
        """Create a new company with proper setup."""
        self.stdout.write(f'Creating new company: {company_name}')

        trading_name = input(f'Trading name (press Enter to use "{company_name}"): ').strip()
        if not trading_name:
            trading_name = company_name

        # Get company email separately from user email
        company_email = input('Company email (required): ').strip()
        if not company_email:
            # Use user email as fallback
            company_email = user_email
            self.stdout.write(f'Using user email for company: {company_email}')

        phone = input('Company phone (optional): ').strip() or None
        physical_address = input('Physical address (optional): ').strip() or ""

        # Generate schema name if not provided
        if not schema_name:
            base_schema = slugify(trading_name or company_name).replace('-', '_')[:50]
            schema_name = input(f'Schema name (press Enter to use "{base_schema}"): ').strip()
            if not schema_name:
                schema_name = base_schema

        schema_name = schema_name.lower().replace('-', '_')
        if not schema_name.replace('_', '').isalnum():
            raise CommandError('Schema name must contain only letters, numbers, and underscores')

        if Company.objects.filter(schema_name=schema_name).exists():
            raise CommandError(f'Schema name "{schema_name}" already exists')

        if not domain:
            base_domain = f"{schema_name}.localhost"
            domain = input(f'Domain (press Enter to use "{base_domain}"): ').strip()
            if not domain:
                domain = base_domain

        if Domain.objects.filter(domain=domain).exists():
            raise CommandError(f'Domain "{domain}" already exists')

        try:
            with transaction.atomic():
                free_plan, created = SubscriptionPlan.objects.get_or_create(
                    name='FREE',
                    defaults={
                        'display_name': 'Free Trial',
                        'description': 'Free trial plan with basic features',
                        'price': 0,
                        'trial_days': 60,
                        'max_users': 5,
                        'max_branches': 1,
                        'max_storage_gb': 1,
                        'max_api_calls_per_month': 1000,
                        'max_transactions_per_month': 500,
                    }
                )

                if created:
                    self.stdout.write('Created FREE subscription plan')

                # Create company - EMAIL IS NOW PROVIDED
                company = Company.objects.create(
                    name=company_name,
                    trading_name=trading_name,
                    email=company_email,  # This was missing!
                    phone=phone,
                    physical_address=physical_address,
                    schema_name=schema_name,
                    plan=free_plan,
                    is_trial=True,
                    status='TRIAL',
                    trial_ends_at=timezone.now().date() + timedelta(days=60),
                )

                Domain.objects.create(
                    tenant=company,
                    domain=domain,
                    is_primary=True,
                    ssl_enabled=False
                )

                self.stdout.write(
                    self.style.SUCCESS(f'Created new company: {company.display_name} ({company.company_id})'))
                self.stdout.write(f'  Schema: {schema_name}')
                self.stdout.write(f'  Domain: {domain}')
                self.stdout.write(f'  Email: {company_email}')
                self.stdout.write(f'  Plan: {free_plan.display_name or free_plan.name}')
                self.stdout.write(f'  Trial ends: {company.trial_ends_at}')

                self._ensure_tenant_schema(company)
                self._create_default_roles(company)

                return company

        except Exception as e:
            raise CommandError(f'Error creating company: {str(e)}')

    def _assign_role_to_user(self, user, role_name):
        """Assign a role to the user using your role-based system."""
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
                            'priority': 100,  # High priority for superusers
                            'created_by': user
                        }
                    )
                    if created:
                        self.stdout.write(self.style.SUCCESS(f'Created new role: {role_name}'))

            if role:
                # Use the role assignment method from your model
                user.assign_role(role)
                self.stdout.write(self.style.SUCCESS(f'✓ Assigned role: {role.group.name}'))
            else:
                self.stdout.write(self.style.WARNING(f'Role not found: {role_name}'))
                # Create a default admin role
                self._create_default_admin_role(user, role_name)

        except Exception as e:
            self.stdout.write(self.style.WARNING(f'Could not assign role {role_name}: {str(e)}'))
            # Fallback: create default admin role
            self._create_default_admin_role(user, 'System Administrator')

    def _create_default_admin_role(self, user, role_name):
        """Create a default admin role if no role exists."""
        try:
            from accounts.models import Role
            from django.contrib.auth.models import Group

            # Create or get admin group
            group, created = Group.objects.get_or_create(name=role_name)
            if created:
                self.stdout.write(f'Created group: {role_name}')

            # Create role for the group
            role, created = Role.objects.get_or_create(
                group=group,
                defaults={
                    'description': f'System administrator role for {role_name}',
                    'is_system_role': True,
                    'priority': 100,  # Highest priority
                    'created_by': user
                }
            )

            # Assign the role to user
            user.assign_role(role)
            self.stdout.write(self.style.SUCCESS(f'✓ Created and assigned default role: {role.group.name}'))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Could not create default role: {str(e)}'))

    def _create_default_roles(self, company):
        """Create default roles for a new company."""
        try:
            with tenant_context(company):
                from accounts.models import Role
                from django.contrib.auth.models import Group

                default_roles = [
                    {
                        'name': 'System Administrator',
                        'priority': 100,
                        'description': 'Full system access with superuser privileges'
                    },
                    {
                        'name': 'Company Administrator',
                        'priority': 90,
                        'description': 'Company-level administrative access'
                    },
                    {
                        'name': 'Manager',
                        'priority': 80,
                        'description': 'Department management access'
                    },
                    {
                        'name': 'Cashier',
                        'priority': 60,
                        'description': 'Point of sale and transaction access'
                    },
                    {
                        'name': 'Standard User',
                        'priority': 50,
                        'description': 'Basic user access'
                    }
                ]

                for role_config in default_roles:
                    group, created = Group.objects.get_or_create(name=role_config['name'])
                    role, created = Role.objects.get_or_create(
                        group=group,
                        defaults={
                            'description': role_config['description'],
                            'is_system_role': True,
                            'priority': role_config['priority'],
                        }
                    )
                    if created:
                        self.stdout.write(f'Created default role: {role_config["name"]}')

                self.stdout.write(self.style.SUCCESS('Default roles created successfully'))

        except Exception as e:
            self.stdout.write(self.style.WARNING(f'Could not create default roles: {str(e)}'))

    def _list_available_roles(self, company, brief=False):
        """List available roles for the company."""
        try:
            with tenant_context(company):
                from accounts.models import Role
                roles = Role.objects.filter(is_active=True).select_related('group').order_by('-priority')

                if brief:
                    for role in roles:
                        self.stdout.write(f'  - {role.group.name} (Priority: {role.priority})')
                else:
                    self.stdout.write(self.style.SUCCESS(f'Available roles for {company.display_name}:'))
                    for role in roles:
                        self.stdout.write(f'  Role: {role.group.name}')
                        self.stdout.write(f'    Description: {role.description}')
                        self.stdout.write(f'    Priority: {role.priority}')
                        self.stdout.write(f'    Users: {role.user_count}')
                        self.stdout.write(f'    System Role: {role.is_system_role}')
                        self.stdout.write('')

        except Exception as e:
            self.stdout.write(self.style.WARNING(f'Could not list roles: {str(e)}'))

    def _validate_schema_name(self, schema_name):
        """Validate schema name for PostgreSQL."""
        if not schema_name:
            return False

        # Must start with letter or underscore
        if not (schema_name[0].isalpha() or schema_name[0] == '_'):
            return False

        # Can only contain letters, numbers, underscores
        if not schema_name.replace('_', '').isalnum():
            return False

        # Check length (PostgreSQL limit is 63 characters)
        if len(schema_name) > 63:
            return False

        return True

    def _ensure_tenant_schema(self, company):
        """Ensure tenant schema exists and is properly migrated."""
        self.stdout.write(f'Checking tenant schema: {company.schema_name}')

        try:
            with schema_context(company.schema_name):
                # Check if the User table exists in this schema
                with connection.cursor() as cursor:
                    cursor.execute("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables 
                            WHERE table_schema = %s 
                            AND table_name = 'accounts_customuser'
                        );
                    """, [company.schema_name])

                    table_exists = cursor.fetchone()[0]

                    if not table_exists:
                        self.stdout.write(
                            f'Schema {company.schema_name} exists but is not migrated. Running migrations...')

                        # Run migrations for this tenant
                        call_command('migrate_schemas',
                                     schema_name=company.schema_name,
                                     verbosity=0)

                        self.stdout.write(self.style.SUCCESS(f'Migrations completed for {company.schema_name}'))
                    else:
                        self.stdout.write(f'Schema {company.schema_name} is properly migrated')

        except Exception as e:
            # Schema might not exist, try to create it
            self.stdout.write(f'Schema {company.schema_name} does not exist. Creating and migrating...')

            try:
                # Create schema and run migrations
                call_command('migrate_schemas',
                             schema_name=company.schema_name,
                             verbosity=0)

                self.stdout.write(self.style.SUCCESS(f'Created and migrated schema: {company.schema_name}'))

            except Exception as create_error:
                raise CommandError(f'Failed to create/migrate schema {company.schema_name}: {str(create_error)}')

