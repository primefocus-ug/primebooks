from django.db.models.signals import post_save,post_migrate, pre_save
from django.dispatch import receiver
from django.conf import  settings
from django.contrib.auth.models import Group, Permission
from django.db import connection
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from company.models import Company
from .models import Role, CustomUser
import logging

logger = logging.getLogger(__name__)
USER_TYPE_TO_ROLE = {
    'SUPER_ADMIN': 'Super Admin',
    'MANAGER': 'Manager',
    'CASHIER': 'Cashier',
    'EMPLOYEE': 'Viewer',  # Default lowest role
    # Add more if roles exist, like:
    # 'STOCK_KEEPER': 'Stock Keeper',
    # 'ACCOUNTANT': 'Accountant',
}


@receiver(post_migrate)
def create_saas_admin_if_needed(sender, **kwargs):
    """Create SaaS admin after migrations, but only inside tenant schemas"""
    # Skip if we're not in a tenant schema
    if connection.schema_name == 'public':
        return

    if sender.name == 'accounts':  # Only run after accounts app migration
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
                    print(f"[{connection.schema_name}] Created default SaaS admin via signal")
        except Exception as e:
            print(f"[{connection.schema_name}] Could not create SaaS admin via signal: {str(e)}")


def get_default_roles_config():
    return {
        'Super Admin': {
            'description': 'Full system access. Can manage all aspects of the system including users, settings, and critical operations.',
            'color_code': '#dc3545',  # Red
            'priority': 100,
            'is_system_role': True,
            'permissions': 'all',  # Special case - gets all permissions
        },
        'Manager': {
            'description': 'Store manager with access to sales, inventory, reports, and staff management. Cannot modify system settings.',
            'color_code': '#0d6efd',  # Blue
            'priority': 80,
            'is_system_role': True,
            'permissions': {
                # Inventory Management
                'inventory.product': ['add', 'change', 'view'],
                'inventory.category': ['add', 'change', 'view'],
                'inventory.stock': ['add', 'change', 'view'],
                'inventory.stockmovement': ['add', 'view'],
                'inventory.supplier': ['add', 'change', 'view'],

                # Invoices
                'invoices.invoice': ['add', 'change', 'view'],
                'invoices.invoicepayment': ['add', 'view'],

                #sales
                'sales.sale': ['add','change','view'],
                'sales.saleitem': ['add','change','view'],
                'sales.receipt': ['add','change','view'],
                'sales.payment': ['add','change','view'],
                'sales.cart': ['add', 'change', 'view'],
                'sales.cartitem': ['add', 'change', 'view'],

                # Store Management
                'stores.store': ['view'],
                'stores.storeoperatinghours': ['view', 'change'],
                'stores.storedevice': ['view', 'change'],
                'stores.userdevicesession': ['view', 'change'],
                'stores.securityalert': ['view'],
                'stores.devicefingerprint': ['view'],

                # Reports
                'reports.savedreport': ['view','add','change'],
                'reports.reportschedule': ['view','change','add'],
                'reports.generatedreport': ['view','add','change'],
                'reports.reportaccesslog': ['view'],
                'reports.reportcomparison': ['view'],

                # Users (limited)
                'accounts.customuser': ['view','change'],
                'accounts.role': ['view'],
            }
        },
        'Cashier': {
            'description': 'Point of sale operator. Can process sales, handle payments, and view basic inventory. No access to reports or settings.',
            'color_code': '#198754',  # Green
            'priority': 60,
            'is_system_role': True,
            'permissions': {
                # Sales Only
                'invoices.invoice': ['add', 'view'],
                'invoices.payment': ['add', 'view'],
                'invoices.receipt': ['view'],

                'sales.sale': ['add', 'view'],
                'sales.payment': ['add', 'view'],
                'sales.receipt': ['view'],

                # Limited Inventory (view only)
                'inventory.product': ['view'],
                'inventory.category': ['view'],

                # Store
                'stores.store': ['view'],
            }
        },
        'Stock Keeper': {
            'description': 'Inventory management specialist. Can manage stock levels, receive deliveries, and perform stock adjustments. No sales access.',
            'color_code': '#fd7e14',  # Orange
            'priority': 50,
            'is_system_role': True,
            'permissions': {
                # Full Inventory Access
                'inventory.product': ['add', 'change', 'view'],
                'inventory.category': ['add', 'change', 'view'],
                'inventory.stockmovement': ['add', 'change', 'view'],
                'inventory.stock': ['add', 'change', 'view'],
                'inventory.supplier': ['add', 'change', 'view'],
                'inventory.importresult': [ 'view'],

                # Store (view only)
                'stores.store': ['view'],

                # Reports (inventory only)
                'reports.generatedreport': ['view'],
            }
        },
        'Accountant': {
            'description': 'Financial management and reporting. Full access to financial reports, payments, and expenses. No inventory management.',
            'color_code': '#6f42c1',  # Purple
            'priority': 70,
            'is_system_role': True,
            'permissions': {
                # Financial
                'invoices.invoice': ['view'],
                'sales.sale': ['add', 'change', 'view'],
                'sales.receipt': ['view'],

                # Reports (all)
                'reports.savedreport': ['view'],
                'reports.generatedreport': ['view'],

                # Limited User View
                'accounts.customuser': ['view'],
            }
        },
        'Sales Rep': {
            'description': 'Sales representative with customer management. Can create quotes, manage customers, and view sales reports.',
            'color_code': '#20c997',  # Teal
            'priority': 40,
            'is_system_role': True,
            'permissions': {
                # Sales
                'invoices.invoice': ['add', 'view'],
                'sales.sale': ['add', 'change', 'view'],
                'customers.customer': ['add', 'change', 'view'],

                # Limited Inventory
                'inventory.product': ['view'],
                'inventory.category': ['view'],

                # Reports (sales only)
                'reports.savedreport': ['view'],
            }
        },
        'Viewer': {
            'description': 'Read-only access. Can view all data but cannot make any changes. Useful for auditors or external consultants.',
            'color_code': '#6c757d',  # Gray
            'priority': 10,
            'is_system_role': True,
            'permissions': {
                # View everything
                'inventory.product': ['view'],
                'inventory.category': ['view'],
                'inventory.stockmovement': ['view'],
                'inventory.supplier': ['view'],
                'invoices.invoice': ['view'],
                'sales.sale': ['view'],
                'sales.receipt': ['view'],
                'stores.store': ['view'],
                'accounts.customuser': ['view'],
                'reports.savedreport': ['view'],
                'reports.generatedreport': ['view'],
            }
        }
    }


@receiver(post_save, sender=Company)
def create_default_roles_for_tenant(sender, instance, created, **kwargs):
    """
    Create default roles when a new tenant (company) is created.
    Only runs for non-public schemas.
    """
    if not created:
        return

    # Skip for public schema
    if instance.schema_name == 'public':
        return

    # Use schema_context to work within tenant
    from django_tenants.utils import schema_context

    with schema_context(instance.schema_name):
        try:
            logger.info(f"Creating default roles for tenant: {instance.schema_name}")

            roles_config = get_default_roles_config()
            created_roles = []

            for role_name, config in roles_config.items():
                # Create the underlying Group
                group, group_created = Group.objects.get_or_create(
                    name=role_name
                )

                # Create the Role wrapper
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
                    # Assign permissions
                    if config['permissions'] == 'all':
                        # Super Admin gets all permissions
                        all_permissions = Permission.objects.all()
                        group.permissions.set(all_permissions)
                    else:
                        # Assign specific permissions
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
                                            f"Permission {codename} not found for {model_path}"
                                        )
                            except ContentType.DoesNotExist:
                                logger.warning(
                                    f"ContentType not found for {model_path}"
                                )

                        if permissions_to_add:
                            group.permissions.add(*permissions_to_add)

                    created_roles.append(role_name)
                    logger.info(f"Created role: {role_name} with {group.permissions.count()} permissions")

            if created_roles:
                logger.info(
                    f"Successfully created {len(created_roles)} default roles for "
                    f"tenant {instance.schema_name}: {', '.join(created_roles)}"
                )

        except Exception as e:
            logger.error(
                f"Error creating default roles for tenant {instance.schema_name}: {str(e)}",
                exc_info=True
            )


# Optional: Also create roles when running migrations
def create_default_roles_on_migrate(sender, **kwargs):
    """
    Alternative approach: Create default roles when running migrations.
    This is useful if you want to create roles for existing tenants.
    """
    from django_tenants.utils import get_tenant_model, schema_context

    # Get current tenant from connection
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

@receiver(pre_save, sender=CustomUser)
def assign_role_and_staff_status(sender, instance: CustomUser, **kwargs):
    """
    Assign group permissions based on user_type before saving the user.
    Avoid recursion by using pre_save and not calling instance.save().
    """
    role_name = USER_TYPE_TO_ROLE.get(instance.user_type)
    if not role_name:
        logger.warning(f"No role mapping defined for user_type '{instance.user_type}'")
        return

    try:
        role = Role.objects.get(group__name=role_name)
    except Role.DoesNotExist:
        logger.warning(f"Role '{role_name}' does not exist. Cannot assign group.")
        return

    # Set the user's groups to this role's group
    # Use set() instead of clear() + add() to avoid multiple queries
    instance.groups.set([role.group])

    # Optionally set is_staff based on user_type
    instance.is_staff = instance.user_type in ['SUPER_ADMIN', 'MANAGER']



# Connect the migration signal (optional)
from django.db.models.signals import post_migrate
# Uncomment to enable role creation on migrate:
# post_migrate.connect(create_default_roles_on_migrate, sender=None)