# accounts/management/commands/create_tenant_superuser_safe.py
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from company.models import Company, SubscriptionPlan, Domain
from django_tenants.utils import tenant_context, schema_context
import getpass

User = get_user_model()


class Command(BaseCommand):
    help = 'Safely create a superuser for a specific tenant with proper schema handling'

    def add_arguments(self, parser):
        parser.add_argument(
            '--company-id',
            required=True,
            help='Company ID (required)',
        )
        parser.add_argument(
            '--email',
            help='Email address for the superuser',
        )
        parser.add_argument(
            '--username',
            help='Username for the superuser',
        )

    def handle(self, *args, **options):
        company_id = options['company_id']
        email = options.get('email')
        username = options.get('username')

        # Get the company
        try:
            company = Company.objects.get(company_id=company_id)
            self.stdout.write(f'Found company: {company.display_name} ({company.company_id})')
            self.stdout.write(f'Schema: {company.schema_name}')
            self.stdout.write(f'Status: {company.status}')
        except Company.DoesNotExist:
            raise CommandError(f'Company with ID {company_id} does not exist')

        # Interactive input if not provided
        if not email:
            email = input('Email Address: ')

        if not username:
            username = input('Username: ')

        # Get password
        password = getpass.getpass('Password: ')
        password_confirm = getpass.getpass('Password (again): ')

        if password != password_confirm:
            raise CommandError('Passwords do not match')

        # Validate inputs
        if not email or not username or not password:
            raise CommandError('Email, username, and password are required')

        # Create superuser in tenant context
        try:
            with tenant_context(company):
                # Check if user already exists
                if User.objects.filter(email=email).exists():
                    raise CommandError(f'User with email {email} already exists in this tenant')

                if User.objects.filter(username=username).exists():
                    raise CommandError(f'User with username {username} already exists in this tenant')

                # Create the superuser
                with transaction.atomic():
                    user = User.objects.create_user(
                        email=email,
                        username=username,
                        password=password,
                        company=company,
                        is_staff=True,
                        is_superuser=True,
                        is_active=True,
                        user_type='SUPER_ADMIN'
                    )

                    self.stdout.write(
                        self.style.SUCCESS('Superuser created successfully!')
                    )
                    self.stdout.write(f'  Email: {user.email}')
                    self.stdout.write(f'  Username: {user.username}')
                    self.stdout.write(f'  User Type: {user.user_type}')
                    self.stdout.write(f'  Company: {company.display_name}')

                    # Show access information
                    primary_domain = company.domains.filter(is_primary=True).first()
                    if primary_domain:
                        self.stdout.write(f'  Access URL: https://{primary_domain.domain}')

        except Exception as e:
            raise CommandError(f'Error creating superuser: {str(e)}')