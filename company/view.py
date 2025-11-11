from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import transaction
from django.utils.translation import gettext
from django.utils.text import slugify
from django.core.exceptions import ValidationError
from django_tenants.utils import schema_context, tenant_context
from django.conf import settings
import json
import uuid
from django.utils import timezone

from company.models import Company, Domain, SubscriptionPlan
from company.forms import CompanyForm
from stores.models import Store
from accounts.models import CustomUser
from efris.models import EFRISConfiguration


def is_saas_admin(user):
    """Check if user is SaaS admin"""
    return user.is_authenticated and (user.is_saas_admin or user.is_superuser)


@login_required
@user_passes_test(is_saas_admin)
def create_company(request):
    if request.method == 'POST':
        form = CompanyForm(request.POST, request.FILES)
        print(f"DEBUG: Form is bound: {form.is_bound}")
        print(f"DEBUG: Form data: {dict(request.POST)}")
        print(f"DEBUG: Files: {dict(request.FILES)}")

        if form.is_valid():
            print("DEBUG: Form is valid, proceeding with company creation")
            try:
                # Use public schema for tenant creation
                with tenant_context(Company.objects.get(schema_name='public')):
                    # Step 1: Create Company (Tenant)
                    company = form.save(commit=False)
                    print(f"DEBUG: Company instance created: {company}")

                    # Auto-generate schema_name if not provided
                    if not company.schema_name:
                        base_schema = slugify(company.name or company.trading_name)
                        base_schema = base_schema.replace('-', '_')[:50]
                        schema_name = base_schema
                        counter = 1
                        while Company.objects.filter(schema_name=schema_name).exists():
                            schema_name = f"{base_schema}_{counter}"
                            counter += 1
                        company.schema_name = schema_name
                        print(f"DEBUG: Auto-generated schema_name: {schema_name}")

                    # Handle JSON fields if they come as strings
                    json_fields = ['brand_colors', 'ip_whitelist', 'tags']
                    for field in json_fields:
                        value = getattr(company, field, None)
                        if isinstance(value, str):
                            try:
                                setattr(company, field, json.loads(value))
                                print(f"DEBUG: Parsed JSON for {field}")
                            except json.JSONDecodeError:
                                setattr(company, field, {} if field == 'brand_colors' else [])
                                print(f"DEBUG: Set default for {field}")

                    # Set default values - Handle SubscriptionPlan gracefully
                    if not company.plan:
                        try:
                            free_plan = SubscriptionPlan.objects.get(name='FREE')
                            company.plan = free_plan
                            print("DEBUG: Assigned FREE plan")
                        except SubscriptionPlan.DoesNotExist:
                            # Create a default free plan if it doesn't exist
                            free_plan = SubscriptionPlan.objects.create(
                                name='FREE',
                                display_name='Free Trial',
                                price=0,
                                trial_days=60,
                                max_users=5,
                                max_branches=1,
                                max_storage_gb=1,
                                is_active=True
                            )
                            company.plan = free_plan
                            print("DEBUG: Created and assigned FREE plan")

                    company.save()
                    print(f"DEBUG: Company saved with ID: {company.company_id}")

                    # Step 2: Create Domain with uniqueness check
                    domain_name = request.POST.get('domain_name', '').strip()
                    if not domain_name:
                        base_domain = getattr(settings, 'BASE_DOMAIN', 'localhost')
                        base_domain_clean = base_domain.split(':')[0]
                        domain_name = f"{company.schema_name}.{base_domain_clean}"
                        print(f"DEBUG: Auto-generated domain: {domain_name}")

                    # Ensure domain is unique
                    original_domain_name = domain_name
                    counter = 1
                    while Domain.objects.filter(domain=domain_name).exists():
                        domain_name = f"{original_domain_name}_{counter}"
                        counter += 1
                        print(f"DEBUG: Domain exists, trying: {domain_name}")

                    domain = Domain()
                    domain.domain = domain_name
                    domain.tenant = company
                    domain.is_primary = True
                    domain.ssl_enabled = request.POST.get('ssl_enabled', 'true').lower() == 'true'
                    domain.save()
                    print(f"DEBUG: Domain created: {domain.domain}")

                    # Step 3: Run migrations for the new tenant schema
                    try:
                        from django.core.management import call_command
                        print(f"DEBUG: Running migrations for schema: {company.schema_name}")
                        call_command('migrate_schemas',
                                     schema_name=company.schema_name,
                                     interactive=False,
                                     verbosity=1)
                        print(f"DEBUG: Migrations completed for schema: {company.schema_name}")
                    except Exception as e:
                        print(f"DEBUG: Migration warning for {company.schema_name}: {e}")
                        messages.warning(
                            request,
                            gettext(
                                'Migrations may not have completed fully. Some features might not work immediately.')
                        )

                    # Step 4: Create EFRIS Configuration if enabled
                    efris_enabled = form.cleaned_data.get('efris_enabled')
                    print(f"DEBUG: EFRIS enabled: {efris_enabled}")

                    if efris_enabled:
                        try:
                            from efris.models import EFRISConfiguration

                            with schema_context(company.schema_name):
                                efris_config = EFRISConfiguration(
                                    company=company,
                                    environment=form.cleaned_data.get('efris_environment', 'sandbox'),
                                    mode=form.cleaned_data.get('efris_mode', 'online'),
                                    device_number=form.cleaned_data.get('efris_device_number', ''),
                                    device_mac=form.cleaned_data.get('efris_device_mac', 'FFFFFFFFFFFF'),
                                    api_base_url=form.cleaned_data.get('efris_api_base_url', ''),
                                    public_certificate=form.cleaned_data.get('efris_public_certificate', ''),
                                    private_key=form.cleaned_data.get('efris_private_key', ''),
                                    key_password=form.cleaned_data.get('efris_key_password', ''),
                                    timeout_seconds=form.cleaned_data.get('efris_timeout_seconds', 30),
                                    max_retry_attempts=form.cleaned_data.get('efris_max_retry_attempts', 3),
                                    auto_sync_enabled=form.cleaned_data.get('efris_auto_sync_enabled', True),
                                    auto_fiscalize=form.cleaned_data.get('efris_auto_fiscalize', True),
                                    sync_interval_minutes=form.cleaned_data.get('efris_sync_interval_minutes', 60),
                                    is_active=True
                                )

                                print(f"DEBUG: EFRIS config created, validating...")
                                try:
                                    efris_config.full_clean()
                                    efris_config.save()
                                    print(f"DEBUG: EFRIS configuration saved for {company.name}")
                                except ValidationError as e:
                                    print(f"DEBUG: EFRIS configuration validation failed: {e}")
                                    error_messages = []
                                    for field, errors in e.error_dict.items():
                                        for error in errors:
                                            error_messages.append(f"{field}: {error}")
                                    messages.warning(
                                        request,
                                        gettext(
                                            'Company created but EFRIS configuration validation failed: %(error)s') % {
                                            'error': '; '.join(error_messages)}
                                    )
                        except Exception as e:
                            print(f"DEBUG: Error creating EFRIS configuration: {e}")
                            messages.warning(
                                request,
                                gettext('Company created but EFRIS configuration failed: %(error)s') % {
                                    'error': str(e)}
                            )

                    # Step 5: Create Default Store (in the new tenant schema)
                    store_created = False
                    store = None

                    try:
                        with schema_context(company.schema_name):
                            # Check if Store table exists
                            from django.db import connection
                            with connection.cursor() as cursor:
                                cursor.execute("""
                                    SELECT EXISTS (
                                        SELECT FROM information_schema.tables 
                                        WHERE table_name = 'stores_store'
                                    )
                                """)
                                table_exists = cursor.fetchone()[0]
                                print(f"DEBUG: Store table exists: {table_exists}")

                            if not table_exists:
                                print(f"DEBUG: ERROR: stores_store table doesn't exist in schema {company.schema_name}")
                                raise Exception(f"Store table not available in schema {company.schema_name}")

                            # Create store using the model
                            store_name = request.POST.get('store_name') or f"{company.display_name} - Main Store"
                            store_code = f"ST-{uuid.uuid4().hex[:6].upper()}"

                            print(f"DEBUG: Creating store: {store_name}")

                            # Create store instance
                            store = Store(
                                company=company,
                                name=store_name,
                                code=store_code,
                                store_type='MAIN',
                                is_main_branch=True,
                                allows_sales=True,
                                allows_inventory=True,
                                physical_address=company.physical_address or "Address to be updated",
                                phone=company.phone,
                                email=company.email,
                                tin=company.tin,
                                nin=company.nin,
                                efris_enabled=company.efris_enabled,
                                efris_device_number=form.cleaned_data.get('efris_device_number', ''),
                                region=request.POST.get('store_region', ''),
                                timezone=company.time_zone or 'Africa/Kampala',
                                operating_hours={
                                    'monday': {'is_open': True, 'open_time': '08:00', 'close_time': '18:00'},
                                    'tuesday': {'is_open': True, 'open_time': '08:00', 'close_time': '18:00'},
                                    'wednesday': {'is_open': True, 'open_time': '08:00', 'close_time': '18:00'},
                                    'thursday': {'is_open': True, 'open_time': '08:00', 'close_time': '18:00'},
                                    'friday': {'is_open': True, 'open_time': '08:00', 'close_time': '18:00'},
                                    'saturday': {'is_open': True, 'open_time': '08:00', 'close_time': '18:00'},
                                    'sunday': {'is_open': False, 'open_time': '', 'close_time': ''},
                                }
                            )

                            # Save the store
                            store.save()
                            store_created = True
                            print(f"DEBUG: Store created successfully with ID: {store.id}")

                            # Step 6: Create admin user for this tenant (optional)
                            create_admin = request.POST.get('create_admin_user', 'false').lower() == 'true'
                            print(f"DEBUG: Create admin user: {create_admin}")

                            if create_admin:
                                admin_email = request.POST.get('admin_email', '')
                                admin_username = request.POST.get('admin_username', '')
                                admin_password = request.POST.get('admin_password', '')

                                if admin_email and admin_username and admin_password:
                                    try:
                                        # Check if CustomUser table exists
                                        with connection.cursor() as cursor:
                                            cursor.execute("""
                                                SELECT EXISTS (
                                                    SELECT FROM information_schema.tables 
                                                    WHERE table_name = 'accounts_customuser'
                                                )
                                            """)
                                            user_table_exists = cursor.fetchone()[0]
                                            print(f"DEBUG: User table exists: {user_table_exists}")

                                        if user_table_exists:
                                            # Create admin user
                                            admin_user = CustomUser(
                                                email=admin_email,
                                                username=admin_username,
                                                company=company,
                                                user_type='COMPANY_ADMIN',
                                                company_admin=True,
                                                is_staff=True,
                                                is_active=True,
                                                first_name=request.POST.get('admin_first_name', 'Admin'),
                                                last_name=request.POST.get('admin_last_name', 'User'),
                                            )
                                            admin_user.set_password(admin_password)
                                            admin_user.save()

                                            # Assign store to admin
                                            admin_user.stores.add(store)

                                            print(f"DEBUG: Admin user created: {admin_user.username}")
                                            messages.success(
                                                request,
                                                gettext('Admin user created successfully for %(company)s') % {
                                                    'company': company.display_name}
                                            )
                                        else:
                                            messages.warning(
                                                request,
                                                gettext(
                                                    'User tables not ready. Admin user will be created on first login.')
                                            )
                                    except Exception as e:
                                        print(f"DEBUG: Admin user creation failed: {e}")
                                        messages.warning(
                                            request,
                                            gettext('Company created but admin user creation failed: %(error)s') % {
                                                'error': str(e)}
                                        )

                    except Exception as e:
                        print(f"DEBUG: Error creating store in schema {company.schema_name}: {e}")
                        import traceback
                        traceback.print_exc()
                        store_created = False

                    if store_created:
                        messages.success(
                            request,
                            gettext('Company "%(company)s" created successfully with domain "%(domain)s"!') % {
                                'company': company.display_name,
                                'domain': domain.domain
                            }
                        )
                    else:
                        messages.success(
                            request,
                            gettext(
                                'Company "%(company)s" created successfully with domain "%(domain)s"! Store creation will complete on first access.') % {
                                'company': company.display_name,
                                'domain': domain.domain
                            }
                        )

                    # Provide the actual URL to access
                    messages.info(
                        request,
                        gettext('Visit: http://%(domain)s:%(port)s/') % {
                            'domain': domain.domain,
                            'port': request.get_port() or '8000'
                        }
                    )

                    print("DEBUG: Company creation completed successfully")
                    return redirect('companies:company_list')

            except ValidationError as e:
                print(f"DEBUG: Validation Error: {e}")
                messages.error(request, gettext('Validation Error: %(error)s') % {'error': str(e)})
            except Exception as e:
                print(f"DEBUG: General Error: {e}")
                import traceback
                traceback.print_exc()
                messages.error(request, gettext('Error creating company: %(error)s') % {'error': str(e)})
        else:
            print("DEBUG: Form is invalid")
            print(f"DEBUG: Form errors: {form.errors}")
            print(f"DEBUG: Form non-field errors: {form.non_field_errors()}")

            # Log each field error in detail
            for field, errors in form.errors.items():
                print(f"DEBUG: Field '{field}' errors: {errors}")

            messages.error(request, gettext('Please correct the errors below.'))
    else:
        form = CompanyForm()
        print("DEBUG: GET request, form created")

    context = {
        'form': form,
        'title': gettext('Create New Company'),
        'submit_text': gettext('Create Company'),
    }

    return render(request, 'company/create_company.html', context)