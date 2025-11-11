from django.db.models.signals import post_save, post_migrate
from django.dispatch import receiver
from django.conf import settings
from django.contrib.auth.models import Group, Permission
from django.db import connection
from django.contrib.contenttypes.models import ContentType
from company.models import Company
from .models import Role, CustomUser
import logging
from django.utils.deprecation import MiddlewareMixin
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.utils import timezone
from .models import AuditLog, LoginHistory
from .utils import get_client_ip, parse_user_agent

import logging
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.utils import timezone
from django.db import connection


logger = logging.getLogger(__name__)

from django_tenants.utils import schema_context, get_tenant_model

def safe_schema_context(f):
    """Decorator to ensure signals always run in an active tenant schema"""
    def wrapper(*args, **kwargs):
        try:
            # If schema is already active, run directly
            return f(*args, **kwargs)
        except Exception as e:
            # Try fallback to each tenant schema if needed
            TenantModel = get_tenant_model()
            for tenant in TenantModel.objects.all():
                try:
                    with schema_context(tenant.schema_name):
                        return f(*args, **kwargs)
                except Exception:
                    continue
            import logging
            logging.getLogger(__name__).warning(f"Signal skipped due to schema issues: {e}")
    return wrapper

@receiver(post_migrate)
def create_saas_admin_if_needed(sender, **kwargs):
    """Create SaaS admin after migrations, but only inside tenant schemas"""
    if connection.schema_name == 'public':
        return

    if sender.name == 'accounts':
        try:
            if not CustomUser.objects.filter(is_saas_admin=True).exists():
                from company.models import Company
                if Company.objects.exists():
                    CustomUser.objects.create_saas_admin(
                        email=getattr(settings, 'DEFAULT_SAAS_ADMIN_EMAIL', 'admin@saas.com'),
                        password=getattr(settings, 'DEFAULT_SAAS_ADMIN_PASSWORD', 'saas_admin_2024'),
                        username='saas_admin',
                        first_name='SaaS',
                        last_name='Administrator'
                    )
                    print(f"[{connection.schema_name}] Created default SaaS admin")
        except Exception as e:
            print(f"[{connection.schema_name}] Could not create SaaS admin: {str(e)}")


def get_default_roles_config():
    """
    Complete role configuration with all default roles.
    Priority determines hierarchy: higher = more privileges

    Key changes:
    1. Added custom permissions (can_manage_users, can_view_reports, etc.)
    2. Structured permissions more logically by role responsibility
    3. Added permission dependencies and hierarchy
    """
    return {
        'SaaS Admin': {
            'description': 'System-wide administrator with access to all companies and features. Highest level access.',
            'color_code': '#000000',
            'priority': 110,
            'is_system_role': True,
            'permissions': 'all',  # Special case: gets all permissions
            'custom_permissions': [
                'accounts.can_manage_users',
                'accounts.can_view_reports',
                'accounts.can_manage_settings',
                'accounts.can_export_data',
                'accounts.can_access_saas_admin',
                'accounts.can_manage_all_companies',
            ]
        },
        'Company Admin': {
            'description': 'Tenant owner with full control over their company. Can manage billing, users, settings, and all company data.',
            'color_code': '#8b0000',
            'priority': 100,
            'is_system_role': True,
            'custom_permissions': [
                'accounts.can_manage_users',
                'accounts.can_view_reports',
                'accounts.can_manage_settings',
                'accounts.can_export_data',
            ],
            'permissions': {
                # Company Management
                'company.company': ['change', 'view'],
                'company.companysubscription': ['add', 'change', 'view', 'delete'],

                # User Management
                'accounts.customuser': ['add', 'change', 'view', 'delete'],
                'accounts.role': ['add', 'change', 'view', 'delete'],
                'accounts.rolehistory': ['view'],
                'accounts.usersignature': ['add', 'change', 'view', 'delete'],

                # Inventory Management
                'inventory.product': ['add', 'change', 'view', 'delete'],
                'inventory.category': ['add', 'change', 'view', 'delete'],
                'inventory.stock': ['add', 'change', 'view', 'delete'],
                'inventory.stockmovement': ['add', 'change', 'view', 'delete'],
                'inventory.supplier': ['add', 'change', 'view', 'delete'],
                'inventory.importresult': ['add', 'change', 'view', 'delete'],

                # Invoice & Payments
                'invoices.invoice': ['add', 'change', 'view', 'delete'],
                'invoices.invoicepayment': ['add', 'change', 'view', 'delete'],
                'invoices.receipt': ['add', 'change', 'view', 'delete'],

                # Sales Management
                'sales.sale': ['add', 'change', 'view', 'delete'],
                'sales.saleitem': ['add', 'change', 'view', 'delete'],
                'sales.receipt': ['add', 'change', 'view', 'delete'],
                'sales.payment': ['add', 'change', 'view', 'delete'],
                'sales.cart': ['add', 'change', 'view', 'delete'],
                'sales.cartitem': ['add', 'change', 'view', 'delete'],

                # Store Management
                'stores.store': ['add', 'change', 'view', 'delete'],
                'stores.storeoperatinghours': ['add', 'change', 'view', 'delete'],
                'stores.storedevice': ['add', 'change', 'view', 'delete'],
                'stores.userdevicesession': ['add', 'change', 'view', 'delete'],
                'stores.securityalert': ['view', 'delete'],
                'stores.devicefingerprint': ['view', 'delete'],

                # Reports
                'reports.savedreport': ['add', 'change', 'view', 'delete'],
                'reports.reportschedule': ['add', 'change', 'view', 'delete'],
                'reports.generatedreport': ['add', 'change', 'view', 'delete'],
                'reports.reportaccesslog': ['view', 'delete'],
                'reports.reportcomparison': ['add', 'change', 'view', 'delete'],

                # Customer Management
                'customers.customer': ['add', 'change', 'view', 'delete'],
                'customers.customergroup': ['add', 'change', 'view', 'delete'],

                # Branch Management
                'branches.companybranch': ['add', 'change', 'view', 'delete'],

                # Expense Management
                'expenses.expense': ['add', 'change', 'view', 'delete'],
                'expenses.expensecategory': ['add', 'change', 'view', 'delete'],

                # Finance
                'finance.account': ['add', 'change', 'view', 'delete'],
                'finance.transaction': ['add', 'change', 'view', 'delete'],

                # EFRIS Integration
                'efris.efrisconfig': ['add', 'change', 'view', 'delete'],
                'efris.efrisinvoice': ['add', 'change', 'view', 'delete'],

                # Notifications
                'notifications.notification': ['add', 'change', 'view', 'delete'],
            }
        },
        'Super Admin': {
            'description': 'Trusted company administrator. Can manage operations, users, and data but cannot modify company settings or billing.',
            'color_code': '#dc3545',
            'priority': 90,
            'is_system_role': True,
            'custom_permissions': [
                'accounts.can_manage_users',
                'accounts.can_view_reports',
                'accounts.can_manage_settings',
            ],
            'permissions': {
                # User Management (limited)
                'accounts.customuser': ['add', 'change', 'view'],
                'accounts.role': ['view'],
                'accounts.rolehistory': ['view'],
                'accounts.usersignature': ['add', 'change', 'view'],

                # Full Inventory Control
                'inventory.product': ['add', 'change', 'view', 'delete'],
                'inventory.category': ['add', 'change', 'view', 'delete'],
                'inventory.stock': ['add', 'change', 'view', 'delete'],
                'inventory.stockmovement': ['add', 'change', 'view', 'delete'],
                'inventory.supplier': ['add', 'change', 'view', 'delete'],
                'inventory.importresult': ['view'],

                # Invoice Management
                'invoices.invoice': ['add', 'change', 'view', 'delete'],
                'invoices.invoicepayment': ['add', 'change', 'view'],
                'invoices.receipt': ['add', 'change', 'view'],

                # Sales Management
                'sales.sale': ['add', 'change', 'view', 'delete'],
                'sales.saleitem': ['add', 'change', 'view', 'delete'],
                'sales.receipt': ['add', 'change', 'view'],
                'sales.payment': ['add', 'change', 'view'],
                'sales.cart': ['add', 'change', 'view', 'delete'],
                'sales.cartitem': ['add', 'change', 'view', 'delete'],

                # Store Operations
                'stores.store': ['change', 'view'],
                'stores.storeoperatinghours': ['add', 'change', 'view'],
                'stores.storedevice': ['change', 'view'],
                'stores.userdevicesession': ['view', 'delete'],
                'stores.securityalert': ['view'],
                'stores.devicefingerprint': ['view'],

                # Full Report Access
                'reports.savedreport': ['add', 'change', 'view', 'delete'],
                'reports.reportschedule': ['add', 'change', 'view', 'delete'],
                'reports.generatedreport': ['add', 'change', 'view', 'delete'],
                'reports.reportaccesslog': ['view'],
                'reports.reportcomparison': ['add', 'change', 'view'],

                # Customer Management
                'customers.customer': ['add', 'change', 'view', 'delete'],
                'customers.customergroup': ['add', 'change', 'view', 'delete'],

                # Branch View
                'branches.companybranch': ['view'],

                # Expense Management
                'expenses.expense': ['add', 'change', 'view', 'delete'],
                'expenses.expensecategory': ['add', 'change', 'view', 'delete'],

                # Finance View
                'finance.account': ['view'],
                'finance.transaction': ['add', 'change', 'view'],

                # EFRIS
                'efris.efrisconfig': ['view'],
                'efris.efrisinvoice': ['add', 'change', 'view'],

                # Notifications
                'notifications.notification': ['add', 'change', 'view', 'delete'],
            }
        },
        'Manager': {
            'description': 'Store manager with access to sales, inventory, reports, and staff management.',
            'color_code': '#0d6efd',
            'priority': 80,
            'is_system_role': True,
            'custom_permissions': [
                'accounts.can_manage_users',
                'accounts.can_view_reports',
            ],
            'permissions': {
                # Limited User Management
                'accounts.customuser': ['add', 'change', 'view'],
                'accounts.role': ['view'],

                # Inventory Management
                'inventory.product': ['add', 'change', 'view'],
                'inventory.category': ['add', 'change', 'view'],
                'inventory.stock': ['add', 'change', 'view'],
                'inventory.stockmovement': ['add', 'change', 'view'],
                'inventory.supplier': ['add', 'change', 'view'],
                'inventory.importresult': ['view'],

                # Invoice Management
                'invoices.invoice': ['add', 'change', 'view'],
                'invoices.invoicepayment': ['add', 'change', 'view'],
                'invoices.receipt': ['view'],

                # Sales Operations
                'sales.sale': ['add', 'change', 'view'],
                'sales.saleitem': ['add', 'change', 'view'],
                'sales.receipt': ['add', 'change', 'view'],
                'sales.payment': ['add', 'change', 'view'],
                'sales.cart': ['add', 'change', 'view', 'delete'],
                'sales.cartitem': ['add', 'change', 'view', 'delete'],

                # Store Management
                'stores.store': ['change', 'view'],
                'stores.storeoperatinghours': ['add', 'change', 'view'],
                'stores.storedevice': ['change', 'view'],
                'stores.userdevicesession': ['view', 'change'],
                'stores.securityalert': ['view'],
                'stores.devicefingerprint': ['view'],

                # Reports
                'reports.savedreport': ['add', 'change', 'view'],
                'reports.reportschedule': ['add', 'change', 'view'],
                'reports.generatedreport': ['add', 'change', 'view'],
                'reports.reportaccesslog': ['view'],
                'reports.reportcomparison': ['view'],

                # Customer Management
                'customers.customer': ['add', 'change', 'view'],
                'customers.customergroup': ['add', 'change', 'view'],

                # Expense Management
                'expenses.expense': ['add', 'change', 'view'],
                'expenses.expensecategory': ['view'],

                # Notifications
                'notifications.notification': ['view'],
            }
        },
        'Accountant': {
            'description': 'Financial management and reporting. Full access to financial reports, payments, and expenses.',
            'color_code': '#6f42c1',
            'priority': 70,
            'is_system_role': True,
            'custom_permissions': [
                'accounts.can_view_reports',
                'accounts.can_export_data',
            ],
            'permissions': {
                # View Users Only
                'accounts.customuser': ['view'],

                # Invoice & Payment Management
                'invoices.invoice': ['add', 'change', 'view'],
                'invoices.invoicepayment': ['add', 'change', 'view'],
                'invoices.receipt': ['add', 'change', 'view'],

                # Sales View & Payment
                'sales.sale': ['view'],
                'sales.saleitem': ['view'],
                'sales.receipt': ['view'],
                'sales.payment': ['add', 'change', 'view'],

                # Reports - Full Access
                'reports.savedreport': ['add', 'change', 'view', 'delete'],
                'reports.generatedreport': ['add', 'change', 'view', 'delete'],
                'reports.reportschedule': ['add', 'change', 'view'],
                'reports.reportaccesslog': ['view'],
                'reports.reportcomparison': ['add', 'change', 'view'],

                # Expense Management - Full
                'expenses.expense': ['add', 'change', 'view', 'delete'],
                'expenses.expensecategory': ['add', 'change', 'view', 'delete'],

                # Finance - Full Access
                'finance.account': ['add', 'change', 'view', 'delete'],
                'finance.transaction': ['add', 'change', 'view', 'delete'],

                # Customer View
                'customers.customer': ['view'],
                'customers.customergroup': ['view'],

                # Inventory View Only
                'inventory.product': ['view'],
                'inventory.stock': ['view'],

                # Store View
                'stores.store': ['view'],

                # EFRIS
                'efris.efrisconfig': ['view'],
                'efris.efrisinvoice': ['view'],

                # Notifications
                'notifications.notification': ['view'],
            }
        },
        'Cashier': {
            'description': 'Point of sale operator. Can process sales, handle payments, and view basic inventory.',
            'color_code': '#198754',
            'priority': 60,
            'is_system_role': True,
            'custom_permissions': [],
            'permissions': {
                # Sales Operations
                'sales.sale': ['add', 'view'],
                'sales.saleitem': ['add', 'view'],
                'sales.payment': ['add', 'view'],
                'sales.receipt': ['add', 'view'],
                'sales.cart': ['add', 'change', 'view', 'delete'],
                'sales.cartitem': ['add', 'change', 'view', 'delete'],

                # Invoice Creation
                'invoices.invoice': ['add', 'view'],
                'invoices.invoicepayment': ['add', 'view'],
                'invoices.receipt': ['view'],

                # Inventory View Only
                'inventory.product': ['view'],
                'inventory.category': ['view'],
                'inventory.stock': ['view'],

                # Store View
                'stores.store': ['view'],

                # Customer Management (Limited)
                'customers.customer': ['add', 'view'],

                # EFRIS Invoice
                'efris.efrisinvoice': ['add', 'view'],

                # Notifications
                'notifications.notification': ['view'],
            }
        },
        'Stock Keeper': {
            'description': 'Inventory management specialist. Can manage stock levels, receive deliveries, and perform stock adjustments.',
            'color_code': '#fd7e14',
            'priority': 50,
            'is_system_role': True,
            'custom_permissions': [],
            'permissions': {
                # Full Inventory Management
                'inventory.product': ['add', 'change', 'view'],
                'inventory.category': ['add', 'change', 'view'],
                'inventory.stock': ['add', 'change', 'view'],
                'inventory.stockmovement': ['add', 'change', 'view'],
                'inventory.supplier': ['add', 'change', 'view'],
                'inventory.importresult': ['view'],

                # Store View
                'stores.store': ['view'],

                # Reports - Inventory Only
                'reports.generatedreport': ['view'],
                'reports.savedreport': ['view'],

                # Notifications
                'notifications.notification': ['view'],
            }
        },
        'Sales Rep': {
            'description': 'Sales representative with customer management. Can create quotes, manage customers, and view sales reports.',
            'color_code': '#20c997',
            'priority': 40,
            'is_system_role': True,
            'custom_permissions': [],
            'permissions': {
                # Sales Management
                'sales.sale': ['add', 'change', 'view'],
                'sales.saleitem': ['add', 'change', 'view'],
                'sales.payment': ['add', 'view'],
                'sales.receipt': ['view'],

                # Invoice Management
                'invoices.invoice': ['add', 'change', 'view'],
                'invoices.invoicepayment': ['add', 'view'],

                # Customer Management - Full
                'customers.customer': ['add', 'change', 'view'],
                'customers.customergroup': ['add', 'change', 'view'],

                # Inventory View
                'inventory.product': ['view'],
                'inventory.category': ['view'],
                'inventory.stock': ['view'],

                # Reports View
                'reports.savedreport': ['view'],
                'reports.generatedreport': ['view'],

                # Store View
                'stores.store': ['view'],

                # Notifications
                'notifications.notification': ['view'],
            }
        },
        'Viewer': {
            'description': 'Read-only access. Can view all data but cannot make any changes.',
            'color_code': '#6c757d',
            'priority': 10,
            'is_system_role': True,
            'custom_permissions': [
                'accounts.can_view_reports',
            ],
            'permissions': {
                # View Everything, Change Nothing
                'inventory.product': ['view'],
                'inventory.category': ['view'],
                'inventory.stock': ['view'],
                'inventory.stockmovement': ['view'],
                'inventory.supplier': ['view'],
                'invoices.invoice': ['view'],
                'invoices.invoicepayment': ['view'],
                'invoices.receipt': ['view'],
                'sales.sale': ['view'],
                'sales.saleitem': ['view'],
                'sales.receipt': ['view'],
                'sales.payment': ['view'],
                'stores.store': ['view'],
                'stores.storeoperatinghours': ['view'],
                'stores.storedevice': ['view'],
                'accounts.customuser': ['view'],
                'accounts.role': ['view'],
                'reports.savedreport': ['view'],
                'reports.generatedreport': ['view'],
                'reports.reportcomparison': ['view'],
                'customers.customer': ['view'],
                'customers.customergroup': ['view'],
                'branches.companybranch': ['view'],
                'expenses.expense': ['view'],
                'expenses.expensecategory': ['view'],
                'finance.account': ['view'],
                'finance.transaction': ['view'],
                'efris.efrisconfig': ['view'],
                'efris.efrisinvoice': ['view'],
                'notifications.notification': ['view'],
            }
        }
    }


@receiver(post_save, sender=Company)
def create_default_roles_for_tenant(sender, instance, created, **kwargs):
    """Create default roles when a new company is created"""
    if not created:
        return

    if instance.schema_name == 'public':
        return

    from django_tenants.utils import schema_context

    with schema_context(instance.schema_name):
        try:
            # Check if tables exist
            existing_tables = connection.introspection.table_names()
            if "auth_group" not in existing_tables or "accounts_role" not in existing_tables:
                logger.warning(
                    f"Skipping role creation for {instance.schema_name} — auth tables not ready"
                )
                return

            logger.info(f"Creating default roles for tenant: {instance.schema_name}")

            roles_config = get_default_roles_config()
            created_roles = []

            for role_name, config in roles_config.items():
                group, group_created = Group.objects.get_or_create(name=role_name)
                role, role_created = Role.objects.get_or_create(
                    group=group,
                    company=instance,
                    defaults={
                        'description': config['description'],
                        'color_code': config['color_code'],
                        'priority': config['priority'],
                        'is_system_role': config.get('is_system_role', True),
                        'is_active': True,
                    }
                )

                if role_created:
                    if config['permissions'] == 'all':
                        group.permissions.set(Permission.objects.all())
                    else:
                        permissions_to_add = []
                        for model_path, actions in config['permissions'].items():
                            app_label, model_name = model_path.split('.')
                            try:
                                content_type = ContentType.objects.get(
                                    app_label=app_label,
                                    model=model_name.lower()
                                )
                                for action in actions:
                                    codename = f"{action}_{model_name.lower()}"
                                    try:
                                        permission = Permission.objects.get(
                                            codename=codename,
                                            content_type=content_type
                                        )
                                        permissions_to_add.append(permission)
                                    except Permission.DoesNotExist:
                                        logger.warning(
                                            f"Permission {codename} not found for {app_label}.{model_name}"
                                        )
                            except ContentType.DoesNotExist:
                                logger.warning(f"ContentType not found for {model_path}")

                        if permissions_to_add:
                            group.permissions.add(*permissions_to_add)

                    created_roles.append(role_name)
                    logger.info(f"✓ Created role: {role_name} (priority: {config['priority']})")

            if created_roles:
                logger.info(f"✅ Created {len(created_roles)} roles: {', '.join(created_roles)}")
            else:
                logger.info(f"ℹ️  All roles already exist for {instance.schema_name}")

        except Exception as e:
            logger.error(
                f"❌ Error creating default roles for tenant {instance.schema_name}: {e}",
                exc_info=True
            )



def create_default_roles_on_migrate(sender, **kwargs):
    """
    Alternative approach: Create default roles when running migrations.
    This is useful if you want to create roles for existing tenants.
    """
    from django.db import connection

    if hasattr(connection, 'tenant') and connection.tenant:
        tenant = connection.tenant

        # Skip public schema
        if tenant.schema_name == 'public':
            return

        # Check if roles already exist
        if Role.objects.filter(is_system_role=True).exists():
            logger.info(f"Default roles already exist for {tenant.schema_name}, skipping...")
            return

        # Create roles
        logger.info(f"Creating default roles during migration for {tenant.schema_name}")
        create_default_roles_for_tenant(Company, tenant, created=True)


def table_exists(table_name: str) -> bool:
    """Check if a given database table exists."""
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = %s)",
                [table_name],
            )
            return cursor.fetchone()[0]
    except Exception:
        return False


# ------------------- AUTH EVENT LOGGING -------------------

@receiver(user_logged_in)
@safe_schema_context
def log_user_login(sender, request, user, **kwargs):
    """Log successful user login"""
    from .utils import get_location_from_ip
    from .models import LoginHistory, AuditLog

    # ✅ Skip if tables aren't ready
    if not table_exists(LoginHistory._meta.db_table) or not table_exists(AuditLog._meta.db_table):
        return

    from .utils import get_client_ip, parse_user_agent

    ip_address = get_client_ip(request)
    user_agent = request.META.get('HTTP_USER_AGENT', '')
    browser_info = parse_user_agent(user_agent)

    # Create login history
    login_history = LoginHistory.objects.create(
        user=user,
        status='success',
        ip_address=ip_address,
        user_agent=user_agent,
        browser=browser_info.get('browser', ''),
        os=browser_info.get('os', ''),
        device_type=browser_info.get('device_type', ''),
        session_key=request.session.session_key
    )

    # Get location (optional)
    try:
        location_data = get_location_from_ip(ip_address)
        if location_data:
            login_history.location = location_data.get('city', '')
            login_history.latitude = location_data.get('latitude')
            login_history.longitude = location_data.get('longitude')
            login_history.save(update_fields=['location', 'latitude', 'longitude'])
    except Exception:
        pass  # Don't fail login if location lookup fails

    # Create audit log
    AuditLog.objects.create(
        user=user,
        action='login_success',
        action_description=f"User {user.get_full_name()} logged in successfully",
        ip_address=ip_address,
        user_agent=user_agent,
        request_path=request.path,
        request_method=request.method,
        company=getattr(user, 'company', None),
        metadata={
            'browser': browser_info.get('browser', ''),
            'os': browser_info.get('os', ''),
            'device_type': browser_info.get('device_type', '')
        }
    )


@receiver(user_login_failed)
@safe_schema_context
def log_failed_login(sender, credentials, request, **kwargs):
    """Log failed login attempt"""
    from .models import LoginHistory, AuditLog

    # ✅ Skip if tables aren't ready
    if not table_exists(LoginHistory._meta.db_table) or not table_exists(AuditLog._meta.db_table):
        return

    from django.contrib.auth import get_user_model
    from .utils import get_client_ip

    ip_address = get_client_ip(request)
    user_agent = request.META.get('HTTP_USER_AGENT', '')

    User = get_user_model()
    username = credentials.get('username', '')
    user = None

    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        try:
            user = User.objects.get(email=username)
        except User.DoesNotExist:
            pass

    if user:
        LoginHistory.objects.create(
            user=user,
            status='failed',
            ip_address=ip_address,
            user_agent=user_agent,
            failure_reason='Invalid credentials'
        )

    AuditLog.objects.create(
        user=user,
        action='login_failed',
        action_description=f"Failed login attempt for username: {username}",
        ip_address=ip_address,
        user_agent=user_agent,
        request_path=getattr(request, 'path', ''),
        request_method=getattr(request, 'method', ''),
        success=False,
        severity='warning',
        metadata={'username_attempted': username}
    )


@receiver(user_logged_out)
@safe_schema_context
def log_user_logout(sender, request, user, **kwargs):
    """Log user logout"""
    from .models import LoginHistory, AuditLog
    from .utils import get_client_ip

    # ✅ Skip if tables aren't ready
    if not table_exists(LoginHistory._meta.db_table) or not table_exists(AuditLog._meta.db_table):
        return

    ip_address = get_client_ip(request)

    # Update login history
    if hasattr(request, 'session') and request.session.session_key:
        LoginHistory.objects.filter(
            user=user,
            session_key=request.session.session_key,
            logout_timestamp__isnull=True
        ).update(logout_timestamp=timezone.now())

    AuditLog.objects.create(
        user=user,
        action='logout',
        action_description=f"User {user.get_full_name()} logged out",
        ip_address=ip_address,
        user_agent=request.META.get('HTTP_USER_AGENT', ''),
        request_path=request.path,
        request_method=request.method,
        company=getattr(user, 'company', None)
    )


# ------------------- GENERIC MODEL CHANGE TRACKING -------------------

def should_audit_model(model_class):
    """Check if model should be audited"""
    audit_models = [
        'CustomUser', 'Company', 'Store', 'Product',
        'Sale', 'Invoice', 'Expense', 'Stock'
    ]
    return model_class.__name__ in audit_models


@receiver(post_save)
@safe_schema_context
def log_model_save(sender, instance, created, **kwargs):
    """Log model creation/update"""
    from .models import AuditLog

    # ✅ Skip if AuditLog table doesn't exist yet
    if not table_exists(AuditLog._meta.db_table):
        return

    if not should_audit_model(sender) or sender.__name__ == 'AuditLog':
        return

    action = f"{sender.__name__.lower()}_created" if created else f"{sender.__name__.lower()}_updated"
    description = f"{'Created' if created else 'Updated'} {sender._meta.verbose_name}: {str(instance)}"

    user = getattr(instance, 'created_by', None) or getattr(instance, 'updated_by', None)

    try:
        AuditLog.objects.create(
            user=user,
            action=action if action in dict(AuditLog.ACTION_TYPES) else 'other',
            action_description=description,
            content_object=instance,
            resource_name=str(instance),
            is_system_action=user is None,
            company=getattr(instance, 'company', None),
            metadata={
                'model': sender.__name__,
                'created': created
            }
        )
    except Exception as e:
        logger.error(f"Failed to create audit log: {e}")


@receiver(post_delete)
@safe_schema_context
def log_model_delete(sender, instance, **kwargs):
    """Log model deletion"""
    from .models import AuditLog

    # ✅ Skip if AuditLog table doesn't exist yet
    if not table_exists(AuditLog._meta.db_table):
        return

    if not should_audit_model(sender) or sender.__name__ == 'AuditLog':
        return

    action = f"{sender.__name__.lower()}_deleted"
    description = f"Deleted {sender._meta.verbose_name}: {str(instance)}"
    user = getattr(instance, 'deleted_by', None)

    try:
        AuditLog.objects.create(
            user=user,
            action=action if action in dict(AuditLog.ACTION_TYPES) else 'other',
            action_description=description,
            resource_name=str(instance),
            is_system_action=user is None,
            company=getattr(instance, 'company', None),
            metadata={
                'model': sender.__name__,
                'deleted': True
            }
        )
    except Exception as e:
        logger.error(f"Failed to create audit log for deletion: {e}")
