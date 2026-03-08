from django.db.models.signals import post_save, post_migrate, post_delete
from django.conf import settings
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from company.models import Company
from .models import Role, CustomUser
import threading
from .models import AuditLog, LoginHistory
from .utils import get_client_ip, parse_user_agent

import logging
from django.dispatch import receiver
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.utils import timezone
from django.db import connection


logger = logging.getLogger(__name__)



def should_suppress_signals():
    """Check if signals should be suppressed for current thread"""
    return getattr(threading.current_thread(), '_suppress_signals', False)


def table_exists(table_name: str) -> bool:
    """Check if a given database table exists in current schema"""
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_schema = %s 
                    AND table_name = %s
                )
            """, [connection.schema_name, table_name])
            return cursor.fetchone()[0]
    except Exception as e:
        logger.debug(f"Could not check table existence: {e}")
        return False


def safe_schema_context(f):
    """Decorator to ensure signals run safely in tenant schemas"""

    def wrapper(*args, **kwargs):
        try:
            # Skip if signals suppressed
            if should_suppress_signals():
                return

            # Skip if in public schema
            if connection.schema_name == 'public':
                return

            # Run the signal handler
            return f(*args, **kwargs)

        except Exception as e:
            logger.warning(f"Signal {f.__name__} failed: {e}")

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
                'company.subscriptionplan': [ 'view'],

                # User Management
                'accounts.customuser': ['add', 'change', 'view', 'delete'],
                'accounts.role': ['add', 'change', 'view'],
                'accounts.rolehistory': ['view'],
                'accounts.auditlog': ['add', 'change', 'view', 'delete'],

                # Inventory Management
                'inventory.product': ['add', 'change', 'view', 'delete'],
                'inventory.category': ['add', 'change', 'view', 'delete'],
                'inventory.stock': ['add', 'change', 'view', 'delete'],
                'inventory.service': ['add', 'change', 'view', 'delete'],
                'inventory.stockmovement': ['add', 'change', 'view', 'delete'],
                'inventory.supplier': ['add', 'change', 'view', 'delete'],
                'inventory.importresult': ['add', 'change', 'view', 'delete'],
                'inventory.importsession': ['add', 'change', 'view', 'delete'],
                'inventory.importlog': ['add', 'change', 'view', 'delete'],

                # Invoice & Payments
                'invoices.invoice': ['add', 'change', 'view', 'delete'],
                'invoices.invoicepayment': ['add', 'change', 'view', 'delete'],
                'invoices.fiscalizationaudit': ['add', 'change', 'view', 'delete'],

                # Sales Management
                'sales.sale': ['add', 'change', 'view', 'delete'],
                'sales.saleitem': ['add', 'change', 'view', 'delete'],
                'sales.receipt': ['add', 'change', 'view', 'delete'],
                'sales.payment': ['add', 'change', 'view', 'delete'],
                'sales.cart': ['add', 'change', 'view', 'delete'],
                'sales.cartitem': ['add', 'change', 'view', 'delete'],

                # Store Management
                'stores.store': ['add', 'change', 'view', 'delete'],
                'stores.storeaccess': ['add', 'change', 'view', 'delete'],
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
                'customers.customernote':['add','change','view','delete'],
                'customers.efriscustomersync': ['add', 'change', 'view', 'delete'],

                # Branch Management
                'branches.companybranch': ['add', 'change', 'view', 'delete'],

                # Expense Management
                'expenses.expense': ['add', 'change', 'view', 'delete'],
                'expenses.expensecategory': ['add', 'change', 'view', 'delete'],
                'expenses.expenseattachment': ['add', 'change', 'view', 'delete'],
                'expenses.expensecomment': ['add', 'change', 'view', 'delete'],


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
                'accounts.role': ['view','change'],
                'accounts.rolehistory': ['view'],
                'accounts.auditlog': ['add', 'change', 'view'],

                'company.company': ['change', 'view'],
                'company.subscriptionplan': ['change', 'view'],

                # Full Inventory Control
                'inventory.product': ['add', 'change', 'view', 'delete'],
                'inventory.category': ['add', 'change', 'view', 'delete'],
                'inventory.stock': ['add', 'change', 'view', 'delete'],
                'inventory.service': ['add', 'change', 'view', 'delete'],
                'inventory.stockmovement': ['add', 'change', 'view', 'delete'],
                'inventory.supplier': ['add', 'change', 'view', 'delete'],
                'inventory.importresult': ['add', 'change', 'view', 'delete'],
                'inventory.importsession': ['add', 'change', 'view', 'delete'],
                'inventory.importlog': ['add', 'change', 'view', 'delete'],

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
                'stores.storeaccess': [ 'change', 'view', ],
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
                'accounts.auditlog': ['view'],

                'company.company': [ 'view'],
                'company.subscriptionplan': [ 'view'],

                # Inventory Management
                'inventory.product': ['add', 'change', 'view'],
                'inventory.category': ['add', 'change', 'view'],
                'inventory.stock': ['add', 'change', 'view'],
                'inventory.service': ['add', 'change', 'view'],
                'inventory.stockmovement': ['add', 'change', 'view'],
                'inventory.supplier': ['add', 'change', 'view'],
                'inventory.importresult': ['view'],
                'inventory.importsession': ['view'],
                'inventory.importlog': ['view'],

                # Invoice Management
                'invoices.invoice': ['add', 'change', 'view'],
                'invoices.invoicepayment': ['add', 'change', 'view'],
                'invoices.fiscalizationaudit': ['view'],

                # Sales Operations
                'sales.sale': ['add', 'change', 'view'],
                'sales.saleitem': ['add', 'change', 'view'],
                'sales.receipt': ['add', 'change', 'view'],
                'sales.payment': ['add', 'change', 'view'],
                'sales.cart': ['add', 'change', 'view', 'delete'],
                'sales.cartitem': ['add', 'change', 'view', 'delete'],

                # Store Management
                'stores.store': ['change', 'view'],
                'stores.storeaccess': ['change', 'view', ],
                'stores.storeoperatinghours': ['add', 'change', 'view'],
                'stores.storedevice': ['change', 'view'],
                'stores.userdevicesession': ['view', 'change'],
                'stores.securityalert': ['view'],
                'stores.devicefingerprint': ['view','change','view'],

                'branches.companybranch': ['change','view'],

                # Reports
                'reports.savedreport': ['add', 'change', 'view'],
                'reports.reportschedule': ['add', 'change', 'view'],
                'reports.generatedreport': ['add', 'change', 'view'],
                'reports.reportaccesslog': ['view'],
                'reports.reportcomparison': ['view'],

                # Customer Management
                'customers.customer': ['add', 'change', 'view'],
                'customers.customergroup': ['add', 'change', 'view'],
                'customers.customernote': ['add', 'change', 'view'],
                'customers.efriscustomersync': ['add', 'change', 'view'],

                # Expense Management
                'expenses.expense': ['add', 'change', 'view'],
                'expenses.expensecategory': ['view','add','change'],
                'expenses.expenseattachment': ['view','add'],
                'expenses.expensecomment': ['add', 'change', 'view'],

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

                'company.company': ['view'],

                # Invoice & Payment Management
                'invoices.invoice': ['add', 'change', 'view'],
                'invoices.invoicepayment': ['add', 'change', 'view'],
                'invoices.fiscalizationaudit': ['add', 'change', 'view'],

                # Sales View & Payment
                'sales.sale': ['view'],
                'sales.saleitem': ['view'],
                'sales.receipt': ['view'],
                'sales.payment': ['add', 'change', 'view'],

                # Reports - Full Access
                'reports.savedreport': ['add', 'change', 'view'],
                'reports.generatedreport': ['view'],
                'reports.reportschedule': [ 'add','view'],
                'reports.reportcomparison': ['view'],

                # Expense Management - Full
                'expenses.expense': ['add', 'change', 'view', 'delete'],
                'expenses.expensecategory': ['add', 'change', 'view', 'delete'],
                'expenses.expenseattachment': ['add', 'change', 'view'],
                'expenses.expensecomment': ['add', 'change', 'view'],

                # Customer View
                'customers.customer': ['view'],
                'customers.customergroup': ['view'],

                # Inventory View Only
                'inventory.product': ['view'],
                'inventory.stock': ['view'],

                # Store View
                'stores.store': ['view'],
                'stores.storeaccess': [ 'view', ],

                'branches.companybranch': ['view'],

                # EFRIS
                'efris.efrisconfig': ['view'],
                'efris.efrisinvoice': ['view'],

                # Notifications
                'notifications.notification': ['view'],
            }
        },
        'Human Resource': {
            'description': 'Manages employee records, roles, permissions, and user administration.',
            'color_code': '#8B4513',  # Saddle Brown
            'priority': 60,
            'is_system_role': False,
            'custom_permissions': [
                'hr.can_manage_employees',
                'hr.can_assign_roles',
                'hr.can_view_attendance',
                'hr.can_manage_user_permissions',
            ],
            'permissions': {
                # Company Management (View only)
                'company.company': ['view'],

                # User Management (Full - HR focus)
                'accounts.customuser': ['add', 'change', 'view'],
                'accounts.role': ['add', 'change', 'view'],
                'accounts.rolehistory': ['view'],
                'accounts.auditlog': ['view'],

                # Inventory Management (Minimal - view only)
                'inventory.product': ['view'],
                'inventory.stock': ['view'],
                'inventory.service': ['view'],

                # Invoice & Payments (View only)
                'invoices.invoice': ['view'],

                # Sales Management (View only for performance tracking)
                'sales.sale': ['view'],
                'sales.receipt': ['view'],

                # Store Management (View employee-related)
                'stores.store': ['view'],
                'stores.storeaccess': [ 'view', ],
                'stores.storedevice': ['view'],
                'stores.userdevicesession': ['view'],

                # Reports (HR and performance reports)
                'reports.savedreport': ['add', 'change', 'view'],
                'reports.generatedreport': ['view'],

                # Customer Management (Minimal)
                'customers.customer': ['view'],

                # Branch Management (View only)
                'branches.companybranch': ['view'],

                # Expense Management (View employee expenses)
                'expenses.expense': ['view'],

                # Notifications (HR related)
                'notifications.notification': ['add', 'change', 'view'],
            }
        },
        'Cashier': {
            'description': 'Processes sales transactions, handles customer payments, and manages daily cash operations at the point of sale.',
            'color_code': '#FF8C00',  # Dark Orange
            'priority': 30,
            'is_system_role': False,
            'custom_permissions': [
                'pos.can_process_sales',
                'pos.can_handle_cash',
                'pos.can_print_receipts',
                'pos.can_view_own_sales',
                'pos.can_process_refunds',
            ],
            'permissions': {

                # User Management (Own profile only)
                'accounts.customuser': ['change', 'view'],  # Can edit own profile

                # Inventory Management (View for sales)
                'inventory.product': ['view'],
                'inventory.category': ['view'],
                'inventory.stock': ['view'],
                'inventory.service': ['view'],

                # Invoice & Payments (Limited - own transactions)
                'invoices.invoice': ['view'],  # Can view invoices they created
                'invoices.invoicepayment': ['view'],

                # Sales Management (Full for processing sales)
                'sales.sale': ['add', 'change', 'view'],  # Can create/edit own sales
                'sales.saleitem': ['add', 'change', 'view'],
                'sales.receipt': ['add', 'change', 'view'],
                'sales.payment': ['add', 'change', 'view'],
                'sales.cart': ['add', 'change', 'view', 'delete'],
                'sales.cartitem': ['add', 'change', 'view', 'delete'],

                # Store Management (Limited to assigned store)
                'stores.store': ['view'],
                'stores.storeaccess': [ 'view', ],
                'stores.storeoperatinghours': ['view'],
                'stores.storedevice': ['view'],  # For POS device management
                'stores.userdevicesession': ['add', 'change', 'view'],  # For login/logout tracking

                # Reports (Limited - own sales reports only)
                'reports.savedreport': ['view'],
                'reports.generatedreport': ['view'],  # Only for own sales

                # Customer Management (Can add/view customers)
                'customers.customer': ['add', 'view'],
                'customers.customergroup': ['view'],
                'customers.customernote': ['add', 'view'],

                # EFRIS Integration (View only for receipts)
                'efris.efrisinvoice': ['view'],

                # Notifications (View own notifications)
                'notifications.notification': ['view'],
            }
        },
        'Stock Manager': {
            'description': 'Manages inventory, stock levels, suppliers, and inventory movements.',
            'color_code': '#D2691E',  # Chocolate
            'priority': 50,
            'is_system_role': False,
            'custom_permissions': [
                'inventory.can_manage_stock',
                'inventory.can_process_orders',
                'inventory.can_manage_suppliers',
                'inventory.can_import_products',
            ],
            'permissions': {
                # Company Management (View only)
                'company.company': ['view'],

                # User Management (Minimal)
                'accounts.customuser': ['view'],

                # Inventory Management (Full)
                'inventory.product': ['add', 'change', 'view', 'delete'],
                'inventory.category': ['add', 'change', 'view', 'delete'],
                'inventory.stock': ['add', 'change', 'view', 'delete'],
                'inventory.service': ['add', 'change', 'view'],
                'inventory.stockmovement': ['add', 'change', 'view', 'delete'],
                'inventory.supplier': ['add', 'change', 'view', 'delete'],
                'inventory.importresult': ['add', 'change', 'view', 'delete'],
                'inventory.importsession': ['add', 'change', 'view', 'delete'],
                'inventory.importlog': ['add', 'change', 'view', 'delete'],

                # Invoice & Payments (Limited - related to inventory)
                'invoices.invoice': ['view'],

                # Sales Management (View for inventory planning)
                'sales.sale': ['view'],
                'sales.saleitem': ['view'],

                # Store Management (View inventory-related)
                'stores.store': ['view'],

                # Reports (Inventory reports only)
                'reports.savedreport': ['add', 'change', 'view'],
                'reports.generatedreport': ['view'],
                'reports.reportcomparison': ['view'],

                # Customer Management (Minimal)
                'customers.customer': ['view'],

                # Branch Management (View only)
                'branches.companybranch': ['view'],

                # Expense Management (Inventory-related expenses)
                'expenses.expense': ['view'],

                # Notifications (Inventory alerts)
                'notifications.notification': ['view'],
            }
        },
        'Sales Manager': {
            'description': 'Manages sales operations, customer relationships, and sales team performance.',
            'color_code': '#2E8B57',  # Sea Green
            'priority': 40,
            'is_system_role': False,
            'custom_permissions': [
                'sales.can_manage_sales_team',
                'sales.can_view_sales_reports',
                'sales.can_manage_customers',
                'sales.can_process_refunds',
            ],
            'permissions': {
                # Company Management (View only)
                'company.company': ['view'],

                # User Management (View sales team)
                'accounts.customuser': ['view'],

                # Inventory Management (View for sales)
                'inventory.product': ['view'],
                'inventory.category': ['view'],
                'inventory.stock': ['view'],
                'inventory.service': ['view'],

                # Invoice & Payments (Sales-related)
                'invoices.invoice': ['add', 'change', 'view'],
                'invoices.invoicepayment': ['add', 'change', 'view'],

                # Sales Management (Full)
                'sales.sale': ['add', 'change', 'view', 'delete'],
                'sales.saleitem': ['add', 'change', 'view', 'delete'],
                'sales.receipt': ['add', 'change', 'view', 'delete'],
                'sales.payment': ['add', 'change', 'view', 'delete'],
                'sales.cart': ['add', 'change', 'view', 'delete'],
                'sales.cartitem': ['add', 'change', 'view', 'delete'],

                # Store Management (Sales-focused)
                'stores.store': ['view'],
                'stores.storeaccess': ['view', ],
                'stores.storeoperatinghours': ['view'],

                # Reports (Sales reports full access)
                'reports.savedreport': ['add', 'change', 'view', 'delete'],
                'reports.reportschedule': ['add', 'change', 'view'],
                'reports.generatedreport': ['add', 'change', 'view'],
                'reports.reportcomparison': ['add', 'change', 'view'],

                # Customer Management (Full)
                'customers.customer': ['add', 'change', 'view', 'delete'],
                'customers.customergroup': ['add', 'change', 'view', 'delete'],
                'customers.customernote': ['add', 'change', 'view', 'delete'],
                'customers.efriscustomersync': ['view'],

                # Branch Management (View only)
                'branches.companybranch': ['view'],

                # Expense Management (Sales-related expenses)
                'expenses.expense': ['view'],

                # EFRIS Integration (Sales view)
                'efris.efrisinvoice': ['view'],

                # Notifications (Sales alerts)
                'notifications.notification': ['add', 'change', 'view'],
            }
        },
        'Data Entry Clerk': {
            'description': 'Responsible for entering product data, customer information, inventory updates, and basic data management without delete capabilities.',
            'color_code': '#696969',  # Dim Gray
            'priority': 25,
            'is_system_role': False,
            'custom_permissions': [
                'data.can_add_products',
                'data.can_update_inventory',
                'data.can_add_customers',
                'data.can_import_basic_data',
                'data.can_view_own_entries',
            ],
            'permissions': {
                # Company Management (View only)
                'company.company': ['view'],

                # User Management (Own profile only)
                'accounts.customuser': ['change', 'view'],

                # Inventory Management (Add and change, no delete)
                'inventory.product': ['add', 'change', 'view'],
                'inventory.category': ['add', 'change', 'view'],
                'inventory.stock': ['add', 'change', 'view'],
                'inventory.service': ['add', 'change', 'view'],
                'inventory.stockmovement': ['add', 'change', 'view'],
                'inventory.supplier': ['add', 'change', 'view'],
                'inventory.importresult': ['view'],
                'inventory.importsession': ['view'],
                'inventory.importlog': ['view'],

                # Invoice & Payments (View only - for reference)
                'invoices.invoice': ['view'],
                'invoices.invoicepayment': ['view'],

                # Sales Management (View only - for understanding sales data)
                'sales.sale': ['view'],
                'sales.saleitem': ['view'],
                'sales.receipt': ['view'],

                # Store Management (Minimal)
                'stores.store': ['view'],
                'stores.storeaccess': ['view', ],

                # Reports (Limited - data quality reports)
                'reports.savedreport': ['view'],
                'reports.generatedreport': ['view'],

                # Customer Management (Add and view only)
                'customers.customer': ['add', 'change', 'view'],
                'customers.customergroup': ['add', 'change', 'view'],
                'customers.customernote': ['add', 'change', 'view'],
                'customers.efriscustomersync': ['view'],

                # Branch Management (View only)
                'branches.companybranch': ['view'],

                # Expense Management (View only)
                'expenses.expense': ['view'],
                'expenses.expensecategory': ['view'],

                # EFRIS Integration (View only for data reference)
                'efris.efrisconfig': ['view'],
                'efris.efrisinvoice': ['view'],

                # Notifications (View only)
                'notifications.notification': ['view'],
            }
        },

        'Auditor': {
            'description': 'Can view all company data for auditing, compliance, and verification purposes but cannot make any changes.',
            'color_code': '#800080',  # Purple
            'priority': 85,
            'is_system_role': False,
            'custom_permissions': [
                'audit.can_view_all_data',
                'audit.can_export_reports',
                'audit.can_compare_financials',
                'audit.can_track_changes',
                'audit.can_generate_audit_trails',
            ],
            'permissions': {
                # Company Management (View only)
                'company.company': ['view'],
                'company.companysubscription': ['view'],

                # User Management (View only - all user activities)
                'accounts.customuser': ['view'],
                'accounts.role': ['view'],
                'accounts.rolehistory': ['view'],
                'accounts.auditlog': ['view'],

                # Inventory Management (View only - full visibility)
                'inventory.product': ['view'],
                'inventory.category': ['view'],
                'inventory.stock': ['view'],
                'inventory.service': ['view'],
                'inventory.stockmovement': ['view'],
                'inventory.supplier': ['view'],
                'inventory.importresult': ['view'],
                'inventory.importsession': ['view'],
                'inventory.importlog': ['view'],

                # Invoice & Payments (View only - complete financial visibility)
                'invoices.invoice': ['view'],
                'invoices.invoicepayment': ['view'],
                'invoices.fiscalizationaudit': ['view'],

                # Sales Management (View only - all sales data)
                'sales.sale': ['view'],
                'sales.saleitem': ['view'],
                'sales.receipt': ['view'],
                'sales.payment': ['view'],
                'sales.cart': ['view'],
                'sales.cartitem': ['view'],

                # Store Management (View only - all store operations)
                'stores.store': ['view'],
                'stores.storeaccess': ['view', ],
                'stores.storeoperatinghours': ['view'],
                'stores.storedevice': ['view'],
                'stores.userdevicesession': ['view'],
                'stores.securityalert': ['view'],
                'stores.devicefingerprint': ['view'],

                # Reports (Full view access - can analyze all reports)
                'reports.savedreport': ['view'],
                'reports.reportschedule': ['view'],
                'reports.generatedreport': ['view'],
                'reports.reportaccesslog': ['view'],
                'reports.reportcomparison': ['view'],

                # Customer Management (View only - all customer data)
                'customers.customer': ['view'],
                'customers.customergroup': ['view'],
                'customers.customernote': ['view'],
                'customers.efriscustomersync': ['view'],

                # Branch Management (View only - all branches)
                'branches.companybranch': ['view'],

                # Expense Management (View only - all expenses)
                'expenses.expense': ['view'],
                'expenses.expensecategory': ['view'],
                'expenses.expenseattachment': ['view'],
                'expenses.expensecomment': ['view'],

                # EFRIS Integration (View only - all EFRIS records)
                'efris.efrisconfig': ['view'],
                'efris.efrisinvoice': ['view'],

                # Notifications (View only - all notifications)
                'notifications.notification': ['view'],
            }
        },
    }


@receiver(post_save, sender=Company)
def create_default_roles_for_tenant(sender, instance, created, **kwargs):
    """
    Create default roles when a new company is created.

    Fixes applied:
    ✅ If auth tables aren't ready yet (happens during initial tenant schema
       creation), the role creation is deferred via a post_migrate signal
       registered dynamically — so roles are never silently dropped.
    ✅ should_suppress_signals() guard preserved.
    """
    if not created:
        return

    if instance.schema_name == 'public':
        return

    if should_suppress_signals():
        logger.info(f"Skipping role creation for {instance.schema_name} — signals suppressed")
        return

    from django_tenants.utils import schema_context

    with schema_context(instance.schema_name):
        try:
            tables_ready = table_exists('auth_group') and table_exists('accounts_role')

            if not tables_ready:
                # ── Deferred creation ─────────────────────────────────────────
                # Auth tables don't exist yet (schema still being migrated).
                # Register a one-shot post_migrate listener that will create
                # roles as soon as migrations finish for this tenant.
                logger.warning(
                    f"Auth tables not ready for {instance.schema_name} — "
                    f"deferring role creation to post_migrate"
                )
                _schedule_deferred_role_creation(instance)
                return

            _do_create_roles(instance)

        except Exception as e:
            logger.error(
                f"❌ Error creating default roles for tenant {instance.schema_name}: {e}",
                exc_info=True
            )


def _schedule_deferred_role_creation(company_instance):
    """
    Register a one-shot post_migrate signal handler that creates roles
    for `company_instance` once migrations have finished running.
    The handler disconnects itself after firing so it doesn't run again.
    """
    from django.db.models.signals import post_migrate

    def _deferred_handler(sender, **kwargs):
        from django_tenants.utils import schema_context
        try:
            with schema_context(company_instance.schema_name):
                if table_exists('auth_group') and table_exists('accounts_role'):
                    if not Role.objects.filter(is_system_role=True).exists():
                        logger.info(
                            f"🔄 Deferred role creation running for {company_instance.schema_name}"
                        )
                        _do_create_roles(company_instance)
        except Exception as e:
            logger.error(
                f"❌ Deferred role creation failed for {company_instance.schema_name}: {e}",
                exc_info=True
            )
        finally:
            # Disconnect so this only fires once
            post_migrate.disconnect(_deferred_handler)

    post_migrate.connect(_deferred_handler)


def _do_create_roles(instance):
    """
    Core role-creation logic, extracted so it can be called from both
    the signal handler and the deferred post_migrate path.
    """
    logger.info(f"Creating default roles for tenant: {instance.schema_name}")

    roles_config = get_default_roles_config()
    created_roles = []

    for role_name, config in roles_config.items():
        group, group_created = Group.objects.get_or_create(name=role_name)

        # System roles are schema-wide (company=None).
        # Only non-system roles are tied to the specific tenant company.
        is_system = config.get('is_system_role', True)
        role_company = None if is_system else instance

        role, role_created = Role.objects.get_or_create(
            group=group,
            company=role_company,
            defaults={
                'description': config['description'],
                'color_code': config['color_code'],
                'priority': config['priority'],
                'is_system_role': is_system,
                'is_active': True,
            }
        )

        if role_created:
            permissions_config = config.get('permissions', {})
            if permissions_config == 'all':
                group.permissions.set(Permission.objects.all())
            elif isinstance(permissions_config, dict):
                permissions_to_add = []
                for model_path, actions in permissions_config.items():
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
                                logger.debug(
                                    f"Permission {codename} not found for {app_label}.{model_name}"
                                )
                    except ContentType.DoesNotExist:
                        logger.debug(f"ContentType not found for {model_path}")

                if permissions_to_add:
                    group.permissions.add(*permissions_to_add)
            else:
                logger.warning(f"Role '{role_name}' has no permissions config — skipping permission assignment")

            created_roles.append(role_name)
            logger.info(f"✓ Created role: {role_name} (priority: {config['priority']})")

    if created_roles:
        logger.info(f"✅ Created {len(created_roles)} roles: {', '.join(created_roles)}")
    else:
        logger.info(f"ℹ️  All roles already exist for {instance.schema_name}")

    # Seed default notification templates so events like sale_completed work
    # immediately without requiring manual admin configuration.
    try:
        from notifications.services import NotificationService
        NotificationService.seed_default_templates(instance.schema_name)
    except Exception as e:
        logger.warning(f"Could not seed notification templates for {instance.schema_name}: {e}")



# ============================================================================
# STORE ACCESS AUTO-GRANT
# ============================================================================

# Roles whose holders should automatically get full access to ALL stores in
# their company — no manual StoreAccess rows required.
HIGH_ACCESS_ROLES = {'SaaS Admin', 'Company Admin', 'Super Admin', 'Manager'}

# Roles whose holders should automatically get view/staff access to all stores.
STANDARD_ACCESS_ROLES = {'Accountant', 'HR Manager', 'Auditor'}


def _get_access_level_for_role(role_name):
    """
    Return the StoreAccess level that a role warrants, or None if no
    automatic grant should be made.
    """
    if role_name in HIGH_ACCESS_ROLES:
        return 'admin' if role_name in ('SaaS Admin', 'Company Admin') else 'manager'
    if role_name in STANDARD_ACCESS_ROLES:
        return 'view'
    return None  # Cashier, Stock Manager, etc. need explicit store assignment


def _grant_store_access_for_user(user, stores, access_level, granted_by=None):
    """
    Ensure `user` has an active StoreAccess record at `access_level` for
    every store in `stores`. Creates missing records; reactivates soft-deleted
    ones; upgrades access level if the new level is higher.
    """
    from stores.models import StoreAccess

    LEVEL_RANK = {'view': 0, 'staff': 1, 'manager': 2, 'admin': 3}
    new_rank = LEVEL_RANK.get(access_level, 0)

    for store in stores:
        try:
            existing = StoreAccess.objects.filter(user=user, store=store).first()

            if existing:
                changed = False
                if not existing.is_active:
                    existing.is_active = True
                    existing.revoked_at = None
                    changed = True
                if LEVEL_RANK.get(existing.access_level, 0) < new_rank:
                    existing.access_level = access_level
                    changed = True
                if changed:
                    existing.save(update_fields=['is_active', 'revoked_at', 'access_level'])
            else:
                StoreAccess.objects.create(
                    user=user,
                    store=store,
                    access_level=access_level,
                    granted_by=granted_by,
                    can_view_sales=True,
                    can_create_sales=access_level in ('staff', 'manager', 'admin'),
                    can_view_inventory=True,
                    can_manage_inventory=access_level in ('manager', 'admin'),
                    can_view_reports=access_level in ('manager', 'admin', 'view'),
                    can_fiscalize=access_level in ('manager', 'admin'),
                    can_manage_staff=access_level == 'admin',
                )
        except Exception as e:
            logger.error(
                f"Could not grant store access to {user} for store {store}: {e}"
            )


def sync_store_access_for_user(user):
    """
    Called whenever a user's role changes or a new store is created.
    Resolves the correct store access from the user's current role and
    ensures StoreAccess rows exist accordingly.

    This is the bridge between the Django-permissions role system and the
    StoreAccess row-level access system.
    """
    if not table_exists('stores_storeaccess') or not table_exists('stores_store'):
        return

    try:
        from stores.models import Store, StoreAccess

        # SaaS admins bypass everything — they see all stores already
        if getattr(user, 'is_saas_admin', False):
            return

        company = getattr(user, 'company', None)
        if not company:
            return

        # Determine the highest-priority role this user has
        role_name = None
        if hasattr(user, 'role') and user.role:
            role_name = user.role.group.name if hasattr(user.role, 'group') else str(user.role)
        elif hasattr(user, 'groups') and user.groups.exists():
            # Fall back to Django groups if no explicit role FK
            role_name = user.groups.order_by().first().name

        if not role_name:
            return

        access_level = _get_access_level_for_role(role_name)

        if access_level is None:
            # Role doesn't get automatic access — leave explicit grants alone
            return

        # Sync access to every active store in the company
        company_stores = Store.objects.filter(company=company, is_active=True)
        _grant_store_access_for_user(user, company_stores, access_level)

        logger.info(
            f"Synced store access for {user} (role={role_name}, "
            f"level={access_level}, stores={company_stores.count()})"
        )

    except Exception as e:
        logger.error(f"sync_store_access_for_user failed for {user}: {e}", exc_info=True)


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
@safe_schema_context
def on_user_saved_sync_store_access(sender, instance, created, **kwargs):
    """
    Whenever a user is created or updated, make sure their store access
    reflects their current role.

    Triggers:
    - New user created with a role already set
    - Existing user's role changed (e.g. promoted to Company Admin)
    - User re-activated (is_active flipped back to True)

    NOTE: We only act if the role-relevant fields changed, to avoid
    hammering the DB on every profile update.
    """
    if not table_exists('stores_storeaccess'):
        return

    # Only sync when something role/access-relevant changed
    update_fields = kwargs.get('update_fields')
    role_fields = {'role', 'role_id', 'is_active', 'company', 'company_id',
                   'is_company_owner', 'company_admin'}

    if update_fields is not None and not role_fields.intersection(update_fields):
        # Explicit partial save that doesn't touch role fields — skip
        return

    if not instance.is_active:
        return

    sync_store_access_for_user(instance)


@receiver(post_save)
@safe_schema_context
def on_store_created_grant_access_to_admins(sender, instance, created, **kwargs):
    """
    When a new Store is created, immediately grant access to all users in
    the company whose role warrants automatic store access.

    Without this, existing Company Admins and Managers would have no access
    to a brand-new store until they manually added themselves.
    """
    if not created:
        return

    # Only react to Store saves
    if sender.__name__ != 'Store':
        return

    if not table_exists('stores_storeaccess') or not table_exists('accounts_customuser'):
        return

    try:
        from django.contrib.auth import get_user_model
        User = get_user_model()

        company = getattr(instance, 'company', None)
        if not company:
            return

        # Find all active users in this company who have an auto-grant role
        users = User.objects.filter(
            company=company,
            is_active=True
        ).select_related('role__group')

        for user in users:
            role_name = None
            if hasattr(user, 'role') and user.role:
                role_name = (
                    user.role.group.name
                    if hasattr(user.role, 'group')
                    else str(user.role)
                )
            elif user.groups.exists():
                role_name = user.groups.order_by().first().name

            if not role_name:
                continue

            access_level = _get_access_level_for_role(role_name)
            if access_level:
                _grant_store_access_for_user(user, [instance], access_level)

        logger.info(
            f"Granted store access for new store '{instance.name}' "
            f"to eligible users in company {company}"
        )

    except Exception as e:
        logger.error(
            f"on_store_created_grant_access_to_admins failed for store {instance}: {e}",
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
        _do_create_roles(tenant)


@receiver(user_logged_in)
@safe_schema_context
def log_user_login(sender, request, user, **kwargs):
    """Log successful user login"""
    # Check if tables exist
    if not table_exists('accounts_loginhistory') or not table_exists('accounts_auditlog'):
        return

    from .utils import get_location_from_ip

    ip_address = get_client_ip(request)
    user_agent = request.META.get('HTTP_USER_AGENT', '')
    browser_info = parse_user_agent(user_agent)

    try:
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
            pass

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
    except Exception as e:
        logger.error(f"Failed to log user login: {e}")


@receiver(user_login_failed)
@safe_schema_context
def log_failed_login(sender, credentials, request, **kwargs):
    """Log failed login attempt"""
    if not table_exists('accounts_loginhistory') or not table_exists('accounts_auditlog'):
        return

    from django.contrib.auth import get_user_model

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

    try:
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
    except Exception as e:
        logger.error(f"Failed to log failed login: {e}")


@receiver(user_logged_out)
@safe_schema_context
def log_user_logout(sender, request, user, **kwargs):
    """Log user logout"""
    if not table_exists('accounts_loginhistory') or not table_exists('accounts_auditlog'):
        return

    # user can be None for anonymous sessions — nothing to log
    if user is None:
        return

    ip_address = get_client_ip(request)

    try:
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
    except Exception as e:
        logger.error(f"Failed to log user logout: {e}")


# ================= GENERIC MODEL CHANGE TRACKING =================

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
    # Skip if AuditLog table doesn't exist yet
    if not table_exists('accounts_auditlog'):
        return

    if not should_audit_model(sender) or sender.__name__ == 'AuditLog':
        return

    action = f"{sender.__name__.lower()}_created" if created else f"{sender.__name__.lower()}_updated"
    description = f"{'Created' if created else 'Updated'} {sender._meta.verbose_name}: {str(instance)}"

    user = getattr(instance, 'created_by', None) or getattr(instance, 'updated_by', None)

    try:
        from django.db import transaction, connection

        # If the outer transaction is already broken, bail out immediately.
        # Attempting ANY query here would raise TransactionManagementError.
        if connection.needs_rollback:
            logger.warning(
                f"Skipping audit log for {sender.__name__} — "
                f"outer transaction is already broken"
            )
            return

        # Wrap in a savepoint so a failure here (e.g. duplicate PK from a
        # drifted sequence) rolls back ONLY this insert and never poisons
        # the caller's atomic block.
        with transaction.atomic():
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
        # The savepoint above was rolled back automatically.
        # The outer transaction is completely unaffected.
        logger.warning(f"Audit log skipped for {sender.__name__}: {e}")


@receiver(post_delete)
@safe_schema_context
def log_model_delete(sender, instance, **kwargs):
    """Log model deletion"""
    if not table_exists('accounts_auditlog'):
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

@receiver(user_logged_in)
@safe_schema_context
def sync_user_session_on_login(sender, request, user, **kwargs):
    if not table_exists('accounts_usersession'):
        return
    from .models import UserSession
    from .middleware import register_session
    try:
        session_key = request.session.session_key
        if not session_key:
            return

        # Mark all previous sessions as inactive
        UserSession.objects.filter(user=user, is_active=True).update(is_active=False)

        ip = get_client_ip(request)
        ua = request.META.get('HTTP_USER_AGENT', '')
        browser_info = parse_user_agent(ua)

        UserSession.objects.create(
            user=user,
            session_key=session_key,
            ip_address=ip,
            user_agent=ua,
            browser=browser_info.get('browser', ''),
            os=browser_info.get('os', ''),
            device_type=browser_info.get('device_type', ''),
            is_active=True,
        )
    except Exception as e:
        logger.warning(f"sync_user_session_on_login failed: {e}")


@receiver(user_logged_out)
@safe_schema_context
def sync_user_session_on_logout(sender, request, user, **kwargs):
    if user is None or not table_exists('accounts_usersession'):
        return
    from .models import UserSession
    from .middleware import clear_session_registry
    try:
        session_key = getattr(request.session, 'session_key', None)
        if session_key:
            UserSession.objects.filter(
                user=user, session_key=session_key
            ).update(is_active=False)
        clear_session_registry(user.pk)
    except Exception as e:
        logger.warning(f"sync_user_session_on_logout failed: {e}")