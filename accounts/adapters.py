from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.account.adapter import DefaultAccountAdapter
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from company.models import Company, SubscriptionPlan, Domain
from django.utils import timezone
from datetime import timedelta
import re

User = get_user_model()


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    Custom adapter to handle Google OAuth signup with company creation
    """

    def pre_social_login(self, request, sociallogin):
        """
        Invoked just after a user successfully authenticates via a social provider,
        but before the login is actually processed.
        """
        # If user exists, link the social account
        if sociallogin.is_existing:
            return

        # Check if email already exists
        if sociallogin.email_addresses:
            email = sociallogin.email_addresses[0].email
            try:
                user = User.objects.get(email=email)
                # Connect social account to existing user
                sociallogin.connect(request, user)
            except User.DoesNotExist:
                pass

    def populate_user(self, request, sociallogin, data):
        """
        Populate user information from social provider data
        """
        user = super().populate_user(request, sociallogin, data)

        # Extract additional data from Google
        if sociallogin.account.provider == 'google':
            extra_data = sociallogin.account.extra_data

            # Set names
            user.first_name = extra_data.get('given_name', '')
            user.last_name = extra_data.get('family_name', '')

            # Generate username from email
            if not user.username:
                user.username = self._generate_unique_username(user.email)

            # Mark email as verified for Google accounts
            user.email_verified = True

        return user

    def save_user(self, request, sociallogin, form=None):
        """
        Save the user and create associated company if needed
        """
        user = super().save_user(request, sociallogin, form)

        # Only create company for new users
        if not user.company_id:
            try:
                company = self._create_company_for_user(user)
                user.company = company
                user.user_type = 'COMPANY_ADMIN'
                user.company_admin = True
                user.is_active = True
                user.save()
            except Exception as e:
                print(f"Error creating company for social login: {str(e)}")
                # You might want to handle this more gracefully
                raise

        return user

    def _create_company_for_user(self, user):
        """
        Create a default company for the new social login user
        """
        # Get or create free trial plan
        free_plan, _ = SubscriptionPlan.objects.get_or_create(
            name='FREE',
            defaults={
                'display_name': 'Free Trial',
                'description': 'Free trial plan for new users',
                'price': 0,
                'trial_days': 60,
                'max_users': 5,
                'max_branches': 1,
                'max_storage_gb': 1,
                'max_api_calls_per_month': 1000,
                'max_transactions_per_month': 500,
            }
        )

        # Create company name from user's name or email
        company_name = self._generate_company_name(user)
        schema_name = self._generate_schema_name(user.email)

        # Create company
        company = Company.objects.create(
            name=company_name,
            trading_name=company_name,
            email=user.email,
            schema_name=schema_name,
            plan=free_plan,
            is_trial=True,
            status='TRIAL',
            trial_ends_at=timezone.now().date() + timedelta(days=60),
        )

        # Create domain
        domain_name = f"{schema_name}.localhost"
        Domain.objects.create(
            tenant=company,
            domain=domain_name,
            is_primary=True,
            ssl_enabled=False
        )

        return company

    def _generate_company_name(self, user):
        """
        Generate a company name from user information
        """
        if user.first_name and user.last_name:
            return f"{user.first_name} {user.last_name}'s Company"
        elif user.first_name:
            return f"{user.first_name}'s Company"
        else:
            # Use email username part
            email_prefix = user.email.split('@')[0]
            return f"{email_prefix.title()}'s Company"

    def _generate_schema_name(self, email):
        """
        Generate a unique schema name from email
        """
        # Get email prefix and clean it
        prefix = email.split('@')[0]
        schema_base = re.sub(r'[^a-z0-9]', '_', prefix.lower())

        # Ensure uniqueness
        schema_name = schema_base
        counter = 1
        while Company.objects.filter(schema_name=schema_name).exists():
            schema_name = f"{schema_base}_{counter}"
            counter += 1

        return schema_name

    def _generate_unique_username(self, email):
        """
        Generate a unique username from email
        """
        base_username = email.split('@')[0].lower()
        username = base_username
        counter = 1

        while User.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1

        return username


class CustomAccountAdapter(DefaultAccountAdapter):
    """
    Custom adapter for regular account operations
    """

    def is_open_for_signup(self, request):
        """
        Allow signups
        """
        return True

    def save_user(self, request, user, form, commit=True):
        """
        Save user from signup form
        """
        user = super().save_user(request, user, form, commit=False)

        # Set additional fields if needed
        if commit:
            user.save()

        return user