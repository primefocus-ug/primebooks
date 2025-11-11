from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction, connection
from django.core.management import call_command
from django.utils.text import slugify
from django_tenants.utils import schema_context, get_public_schema_name
from company.models import Company, Domain, SubscriptionPlan
from accounts.models import CustomUser,Role
from django.contrib.auth import get_user_model
from functools import wraps
import uuid
import logging

User = get_user_model()
logger = logging.getLogger(__name__)


def require_public_schema(view_func):
    """
    Decorator to ensure a view runs in the public schema.
    Critical for tenant creation operations.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        public_schema = get_public_schema_name()
        current_schema = connection.schema_name

        if current_schema != public_schema:
            logger.warning(
                f"View {view_func.__name__} called from tenant schema '{current_schema}'. "
                f"Switching to public schema '{public_schema}'"
            )
            connection.set_schema_to_public()

        return view_func(request, *args, **kwargs)
    return wrapper


def _extract_form_data(request):
    """Extract and return all form data from request."""
    form_data = {
        # Company information
        'schema_name': request.POST.get('schema_name', '').strip().lower(),
        'company_name': request.POST.get('name', '').strip(),
        'trading_name': request.POST.get('trading_name', '').strip(),
        'email': request.POST.get('email', '').strip().lower(),
        'phone': request.POST.get('phone', '').strip(),
        'physical_address': request.POST.get('physical_address', '').strip(),
        'tin': request.POST.get('tin', '').strip().upper(),

        # Domain information
        'domain_name': request.POST.get('domain', '').strip().lower(),

        # Admin user information
        'admin_username': request.POST.get('admin_username', '').strip(),
        'admin_email': request.POST.get('admin_email', '').strip().lower(),
        'admin_first_name': request.POST.get('admin_first_name', '').strip(),
        'admin_last_name': request.POST.get('admin_last_name', '').strip(),
        'admin_password': request.POST.get('admin_password', ''),

        # Subscription information
        'plan_id': request.POST.get('plan'),
        'is_trial': request.POST.get('is_trial') == 'on',

        # Additional company fields
        'postal_address': request.POST.get('postal_address', '').strip(),
        'website': request.POST.get('website', '').strip(),
        'brn': request.POST.get('brn', '').strip().upper(),
        'nin': request.POST.get('nin', '').strip().upper(),
        'description': request.POST.get('description', '').strip(),

        # EFRIS settings
        'efris_enabled': request.POST.get('efris_enabled') == 'on',
        'efris_is_production': request.POST.get('efris_is_production') == 'on',
        'efris_integration_mode': request.POST.get('efris_integration_mode', 'offline'),
        'efris_device_number': request.POST.get('efris_device_number', '').strip(),

        # Localization
        'time_zone': request.POST.get('time_zone', 'Africa/Kampala'),
        'locale': request.POST.get('locale', 'en-UG'),
        'date_format': request.POST.get('date_format', '%d/%m/%Y'),
        'time_format': request.POST.get('time_format', '24'),
        'preferred_currency': request.POST.get('preferred_currency', 'UGX'),
    }

    # Auto-generate admin username if not provided
    if not form_data['admin_username'] and form_data['admin_email']:
        form_data['admin_username'] = form_data['admin_email'].split('@')[0]

    return form_data


def _validate_form_data(form_data, plans):
    """Validate form data and return error messages if any."""
    errors = []

    if not form_data['company_name']:
        errors.append("Company name is required.")

    if not form_data['domain_name']:
        errors.append("Domain name is required.")

    # Email validation
    if not form_data['admin_email'] or '@' not in form_data['admin_email']:
        errors.append("Valid admin email address is required.")

    if not form_data['admin_username']:
        errors.append("Admin username is required.")
    elif len(form_data['admin_username']) < 3:
        errors.append("Admin username must be at least 3 characters long.")

    if not form_data['admin_password']:
        errors.append("Admin password is required.")
    elif len(form_data['admin_password']) < 8:
        errors.append("Admin password must be at least 8 characters long.")

    # Check if domain already exists
    if Domain.objects.filter(domain=form_data['domain_name']).exists():
        errors.append(f"Domain '{form_data['domain_name']}' already exists.")

    return errors

def _generate_schema_name(company_name):
    """Generate a unique schema name based on company name."""
    base_schema = slugify(company_name).replace('-', '_')[:20]
    if not base_schema[0].isalpha():
        base_schema = f"c_{base_schema}"

    schema_name = f"{base_schema}_{uuid.uuid4().hex[:8]}"

    # Ensure schema_name is unique
    counter = 1
    original_schema = schema_name
    while Company.objects.filter(schema_name=schema_name).exists():
        schema_name = f"{original_schema}_{counter}"
        counter += 1

    return schema_name[:63]  # Respect PostgreSQL limit


def _get_subscription_plan(plan_id):
    """Get subscription plan by ID or return None."""
    if plan_id:
        try:
            return SubscriptionPlan.objects.get(id=plan_id)
        except SubscriptionPlan.DoesNotExist:
            return None
    return None


def _create_company(form_data, schema_name, plan):
    """Create and save Company instance."""
    company = Company()
    company.schema_name = schema_name
    company.name = form_data['company_name']
    company.trading_name = form_data['trading_name'] or form_data['company_name']
    company.email = form_data['email']
    company.phone = form_data['phone']
    company.physical_address = form_data['physical_address']
    company.tin = form_data['tin']
    company.plan = plan
    company.is_trial = form_data['is_trial']

    # Set additional fields
    company.postal_address = form_data['postal_address']
    company.website = form_data['website']
    company.brn = form_data['brn']
    company.nin = form_data['nin']
    company.description = form_data['description']

    # EFRIS settings
    company.efris_enabled = form_data['efris_enabled']
    company.efris_is_production = form_data['efris_is_production']
    company.efris_integration_mode = form_data['efris_integration_mode']
    company.efris_device_number = form_data['efris_device_number']

    # Localization
    company.time_zone = form_data['time_zone']
    company.locale = form_data['locale']
    company.date_format = form_data['date_format']
    company.time_format = form_data['time_format']
    company.preferred_currency = form_data['preferred_currency']

    company.save()
    return company


def _create_domain(domain_name, company):
    """Create and save Domain instance."""
    domain = Domain()
    domain.domain = domain_name
    domain.tenant = company
    domain.is_primary = True
    domain.ssl_enabled = True
    domain.save()
    return domain


def _create_tenant_admin(schema_name, form_data, company):
    """Create admin user in tenant schema and run migrations."""
    logger.info(f"Running migrations for tenant {schema_name}")

    # ✅ Correct way to apply migrations for this tenant
    call_command('migrate', schema_name=schema_name, interactive=False, verbosity=0)

    # Now the schema exists with all tables
    with schema_context(schema_name):
        logger.info(f"Creating admin user for tenant {schema_name}")

        # Validate email before creating user
        admin_email = form_data['admin_email']
        if not admin_email or '@' not in admin_email:
            raise ValueError(f"Invalid admin email address: {admin_email}")

        # Ensure username is provided and valid
        admin_username = form_data['admin_username']
        if not admin_username or len(admin_username) < 3:
            admin_username = admin_email.split('@')[0]  # Use email prefix as username
            if len(admin_username) < 3:
                admin_username = f"admin_{uuid.uuid4().hex[:6]}"

        try:
            admin_user = CustomUser.objects.create_user(
                username=admin_username,
                email=admin_email,
                password=form_data['admin_password'],
                first_name=form_data['admin_first_name'],
                last_name=form_data['admin_last_name'],
                company=company,
                is_staff=True,
                is_active=True,
                company_admin=True,
            )

            # ✅ Assign primary role (Company Admin)
            admin_role, _ = Role.objects.get_or_create(
                company=company,
                name='Company Admin',
                defaults={'priority': 100, 'description': 'Full access to all company resources'},
            )
            admin_user.primary_role = admin_role
            admin_user.save(update_fields=['primary_role'])

            logger.info(f"Admin user {admin_username} created for company {company.company_id}")

            # ✅ Optional: create EFRIS configuration
            if form_data.get('efris_enabled'):
                try:
                    from efris.models import EFRISConfiguration

                    env = 'production' if form_data.get('efris_is_production') else 'sandbox'
                    mode = form_data.get('efris_integration_mode')  # 'online' or 'offline'

                    efris_config, created = EFRISConfiguration.objects.get_or_create(
                        company=company,
                        defaults={
                            'environment': env,
                            'mode': mode,
                            'device_number': form_data.get('efris_device_number'),
                            'is_active': True,
                        }
                    )

                    if created:
                        logger.info(f"EFRIS configuration created for company {company.company_id}")
                    else:
                        logger.info(f"EFRIS configuration already exists for company {company.company_id}")

                except Exception as efris_error:
                    logger.error(
                        f"Failed to create EFRIS configuration for {company.name}: {efris_error}",
                        exc_info=True
                    )

            return admin_user

        except Exception as e:
            logger.error(f"Failed to create admin user: {str(e)}", exc_info=True)
            raise


@login_required
@require_public_schema
def create_tenant_view(request):
    """
    Frontend view for creating new tenants/companies.
    Only accessible by SaaS admins.
    IMPORTANT: Must run in public schema context.
    """
    # Check if user is SaaS admin
    if not request.user.is_saas_admin:
        messages.error(request, "You don't have permission to create new tenants.")
        return redirect('companies:company_list')

    # Get available subscription plans
    plans = SubscriptionPlan.objects.filter(is_active=True).order_by('sort_order', 'price')

    if request.method == 'POST':
        company = None
        schema_name = None
        public_schema = get_public_schema_name()
        connection.set_schema_to_public()

        try:
            form_data = _extract_form_data(request)
            validation_errors = _validate_form_data(form_data, plans)
            if validation_errors:
                for error in validation_errors:
                    messages.error(request, error)
                return render(request, 'company/create_tenant.html', {
                    'plans': plans,
                    'form_data': request.POST
                })

            schema_name = form_data['schema_name'] or _generate_schema_name(form_data['company_name'])
            plan = _get_subscription_plan(form_data['plan_id'])

            # Create company and domain first
            company = _create_company(form_data, schema_name, plan)
            logger.info(f"Created company {company.company_id}")

            domain = _create_domain(form_data['domain_name'], company)
            logger.info(f"Domain {domain.domain} created")

            # Then create tenant admin
            _create_tenant_admin(schema_name, form_data, company)

            messages.success(
                request,
                f"✅ Tenant '{company.name}' created successfully! "
                f"Domain: {form_data['domain_name']} | Schema: {schema_name} | "
                f"Admin: {form_data['admin_username']}"
            )
            return redirect('companies:company_detail', company_id=company.company_id)

        except Exception as e:
            logger.exception(f"Error creating tenant: {e}")
            messages.error(request, f"❌ Error creating tenant: {e}")

            # Safe cleanup - only attempt if company was created
            if company and company.pk:
                try:
                    # Ensure we're in public schema for cleanup
                    connection.set_schema_to_public()

                    # Delete domain first (foreign key constraint)
                    Domain.objects.filter(tenant=company).delete()

                    # Then delete company (this will drop the schema)
                    company.delete(force_drop=True)
                    logger.info(f"Cleaned up failed tenant creation for {schema_name}")

                except Exception as cleanup_error:
                    logger.error(f"Failed cleanup for {schema_name}: {cleanup_error}")

            return render(request, 'company/create_tenant.html', {
                'plans': plans,
                'form_data': request.POST
            })

    # GET request - show the form
    return render(request, 'company/create_tenant.html', {
        'plans': plans
    })