# accounts/management/commands/create_company_superuser.py
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

    def handle(self, *args, **options):
        email = options.get('email')
        username = options.get('username')
        company_id = options.get('company_id')
        company_name = options.get('company_name')
        schema_name = options.get('schema_name')
        domain = options.get('domain')

        # Interactive input if not provided
        if not email:
            email = input('Email Address: ')

        if not username:
            username = input('Username: ')

        # Handle company selection/creation
        company = None

        if company_id:
            try:
                company = Company.objects.get(company_id=company_id)
                self.stdout.write(f'Using existing company: {company.display_name} ({company.company_id})')
                # Check if tenant schema exists and is migrated
                self._ensure_tenant_schema(company)
            except Company.DoesNotExist:
                raise CommandError(f'Company with ID {company_id} does not exist')

        elif company_name:
            # Creating new company
            company = self._create_new_company(company_name, email, schema_name, domain)

        else:
            # Show available companies
            companies = Company.objects.all()
            if companies.exists():
                self.stdout.write('Available companies:')
                for comp in companies[:10]:  # Show first 10
                    self.stdout.write(f'  {comp.company_id}: {comp.display_name} ({comp.status})')

                if companies.count() > 10:
                    self.stdout.write(f'  ... and {companies.count() - 10} more')

                company_choice = input('Enter company ID (or press Enter to create new): ')
                if company_choice:
                    try:
                        company = Company.objects.get(company_id=company_choice)
                        self.stdout.write(f'Selected company: {company.display_name}')
                        # Check if tenant schema exists and is migrated
                        self._ensure_tenant_schema(company)
                    except Company.DoesNotExist:
                        raise CommandError('Invalid company ID')
                else:
                    company_name = input('Enter new company name: ')
                    company = self._create_new_company(company_name, email, schema_name, domain)
            else:
                company_name = input('No companies exist. Enter new company name: ')
                company = self._create_new_company(company_name, email, schema_name, domain)

        # Get password
        import getpass
        password = getpass.getpass('Password: ')
        password_confirm = getpass.getpass('Password (again): ')

        if password != password_confirm:
            raise CommandError('Passwords do not match')

        # Create superuser
        try:
            with transaction.atomic():
                # Switch to the tenant schema context
                with tenant_context(company):
                    user = User.objects.create_superuser(
                        email=email,
                        username=username,
                        password=password,
                        company=company
                    )
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'Superuser created successfully!'
                        )
                    )
                    self.stdout.write(f'  Email: {user.email}')
                    self.stdout.write(f'  Username: {user.username}')
                    self.stdout.write(f'  Company: {company.display_name} ({company.company_id})')
                    self.stdout.write(f'  Company Status: {company.status}')

                    # Show domain information
                    primary_domain = company.domains.filter(is_primary=True).first()
                    if primary_domain:
                        self.stdout.write(f'  Primary Domain: {primary_domain.domain}')

        except Exception as e:
            raise CommandError(f'Error creating superuser: {str(e)}')

    def _create_new_company(self, company_name, email, schema_name=None, domain=None):
        """Create a new company with proper setup."""
        self.stdout.write(f'Creating new company: {company_name}')

        # Get additional company details interactively
        trading_name = input(f'Trading name (press Enter to use "{company_name}"): ').strip()
        if not trading_name:
            trading_name = company_name

        phone = input('Company phone (optional): ').strip() or None
        physical_address = input('Physical address (optional): ').strip() or ""

        # Generate schema name if not provided
        if not schema_name:
            base_schema = slugify(trading_name or company_name).replace('-', '_')[:50]
            schema_name = input(f'Schema name (press Enter to use "{base_schema}"): ').strip()
            if not schema_name:
                schema_name = base_schema

        # Ensure schema name is valid
        schema_name = schema_name.lower().replace('-', '_')
        if not schema_name.replace('_', '').isalnum():
            raise CommandError('Schema name must contain only letters, numbers, and underscores')

        # Check if schema name is unique
        if Company.objects.filter(schema_name=schema_name).exists():
            raise CommandError(f'Schema name "{schema_name}" already exists')

        # Generate domain if not provided
        if not domain:
            base_domain = f"{schema_name}.localhost"
            domain = input(f'Domain (press Enter to use "{base_domain}"): ').strip()
            if not domain:
                domain = base_domain

        # Check if domain is unique
        if Domain.objects.filter(domain=domain).exists():
            raise CommandError(f'Domain "{domain}" already exists')

        try:
            with transaction.atomic():
                # Get or create free plan
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

                # Create company
                company = Company.objects.create(
                    name=company_name,
                    trading_name=trading_name,
                    email=email,
                    phone=phone,
                    physical_address=physical_address,
                    schema_name=schema_name,
                    plan=free_plan,
                    is_trial=True,
                    status='TRIAL',
                    trial_ends_at=timezone.now().date() + timedelta(days=60),
                )

                # Create domain
                Domain.objects.create(
                    tenant=company,
                    domain=domain,
                    is_primary=True,
                    ssl_enabled=False  # Set to True if you have SSL setup
                )

                self.stdout.write(
                    self.style.SUCCESS(f'Created new company: {company.display_name} ({company.company_id})')
                )
                self.stdout.write(f'  Schema: {schema_name}')
                self.stdout.write(f'  Domain: {domain}')
                self.stdout.write(f'  Plan: {free_plan.display_name or free_plan.name}')
                self.stdout.write(f'  Trial ends: {company.trial_ends_at}')

                # Ensure the tenant schema is created and migrated
                self._ensure_tenant_schema(company)

                return company

        except Exception as e:
            raise CommandError(f'Error creating company: {str(e)}')

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