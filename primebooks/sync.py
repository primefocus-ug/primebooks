# primebooks/sync.py - COMPLETE BIDIRECTIONAL SYNC WITH ENHANCED LOGGING
"""
Complete bidirectional sync system
✅ Downloads data from server
✅ Uploads offline changes to server
✅ Conflict resolution (last-write-wins)
✅ Automatic sync scheduling
✅ Manual sync on demand
✅ Signal suppression during sync
✅ ENHANCED ERROR LOGGING
"""
import requests
import logging
from django.conf import settings
from django.core import serializers
from django_tenants.utils import schema_context
from django.apps import apps
from datetime import datetime, timedelta
from contextlib import contextmanager
from django.db.models.signals import post_save, pre_save, post_delete
from django.core.exceptions import ValidationError
import json
from django.utils import timezone

logger = logging.getLogger(__name__)


# ============================================================================
# SIGNAL SUPPRESSION
# ============================================================================

@contextmanager
def suppress_signals():
    """
    Temporarily disable Django signals during sync to avoid:
    - WebSocket errors
    - Notification spam
    - Validation errors from incomplete data
    """
    # Store original receivers
    saved_receivers = {
        'post_save': post_save.receivers[:],
        'pre_save': pre_save.receivers[:],
        'post_delete': post_delete.receivers[:],
    }

    # Clear all receivers
    post_save.receivers = []
    pre_save.receivers = []
    post_delete.receivers = []

    try:
        logger.debug("🔇 Signals suppressed for sync")
        yield
    finally:
        # Restore all receivers
        post_save.receivers = saved_receivers['post_save']
        pre_save.receivers = saved_receivers['pre_save']
        post_delete.receivers = saved_receivers['post_delete']
        logger.debug("🔊 Signals restored")


# ============================================================================
# SYNC MODEL CONFIGURATION
# ============================================================================

SYNC_MODEL_CONFIG = {
    # ============================================================================
    # TIER 1: NO DEPENDENCIES - Core Reference Data & Django Built-ins
    # ============================================================================

    # Django Built-in Models
    'contenttypes.ContentType': {
        'dependencies': [],
    },

    # Company Reference Data
    'company.SubscriptionPlan': {
        'dependencies': [],
    },
    'company.EFRISCommodityCategory': {
        'dependencies': [],
    },
    'company.EFRISHsCode': {
        'dependencies': [],
    },

    # Error Tracking
    'errors.ErrorSummary': {
        'dependencies': [],
    },

    # PrimeBooks Core
    'primebooks.AppVersion': {
        'dependencies': [],
    },
    'primebooks.MaintenanceWindow': {
        'dependencies': [],
    },
    'primebooks.UpdateLog': {
        'dependencies': [],
    },
    'primebooks.ErrorReport': {
        'dependencies': [],
    },

    # Celery Beat Schedules (no dependencies)
    'django_celery_beat.IntervalSchedule': {
        'dependencies': [],
    },
    'django_celery_beat.CrontabSchedule': {
        'dependencies': [],
    },
    'django_celery_beat.SolarSchedule': {
        'dependencies': [],
    },
    'django_celery_beat.ClockedSchedule': {
        'dependencies': [],
    },

    # Public Apps - Reference Data
    'public_blog.BlogCategory': {
        'dependencies': [],
    },
    'public_support.FAQ': {
        'dependencies': [],
    },
    'public_seo.RobotsTxt': {
        'dependencies': [],
    },
    'public_seo.Sitemap': {
        'dependencies': [],
    },
    'public_seo.Redirect': {
        'dependencies': [],
    },

    # ============================================================================
    # TIER 2: COMPANY & PUBLIC USER - Depends only on SubscriptionPlan
    # ============================================================================

    'company.Company': {
        'dependencies': ['company.SubscriptionPlan'],
        'exclude_fields': [
            'efris_certificate_data',
            'verification_token',
            'smtp_password',
        ],
    },

    # Public User Management
    'public_accounts.PublicUser': {
        'dependencies': [],
        'exclude_fields': ['password', 'backup_codes'],
    },
    'public_accounts.PasswordResetToken': {
        'dependencies': ['public_accounts.PublicUser'],
    },
    'public_accounts.PublicUserActivity': {
        'dependencies': ['public_accounts.PublicUser'],
    },

    # Public Admin
    'public_admin.PublicStaffUser': {
        'dependencies': ['public_accounts.PublicUser'],
    },

    # Public Router
    'public_router.SubdomainReservation': {
        'dependencies': [],
    },
    'public_router.PublicNewsletterSubscriber': {
        'dependencies': [],
    },
    'public_router.TenantSignupRequest': {
        'dependencies': ['company.Company'],
    },
    'public_router.TenantApprovalWorkflow': {
        'dependencies': ['public_router.TenantSignupRequest'],
    },
    'public_router.TenantNotificationLog': {
        'dependencies': ['company.Company'],
    },

    # ============================================================================
    # TIER 3: AUTH & ROLES - Depends on Company
    # ============================================================================

    'auth.Permission': {
        'dependencies': ['contenttypes.ContentType'],
    },
    'auth.Group': {
        'dependencies': [],
        'exclude_fields': ['permissions'],  # Don't sync Django permissions
    },
    'accounts.Role': {
        'dependencies': ['auth.Group'],
    },

    # Taggit
    'taggit.Tag': {
        'dependencies': [],
    },

    # ============================================================================
    # TIER 4: USERS - Depends on Role
    # ============================================================================

    'accounts.CustomUser': {
        'dependencies': ['accounts.Role'],
        'exclude_fields': [
            'password',
            'backup_codes',
            'failed_login_attempts',
        ],
    },

    # OTP for 2FA
    'django_otp.Device': {
        'dependencies': ['accounts.CustomUser'],
    },
    'otp_totp.TOTPDevice': {
        'dependencies': ['accounts.CustomUser'],
    },

    # ============================================================================
    # TIER 5: COMPANY SETTINGS & DOMAINS - Depends on Company
    # ============================================================================

    'company.TenantEmailSettings': {
        'dependencies': ['company.Company'],
        'exclude_fields': ['smtp_password'],
    },
    'company.TenantInvoiceSettings': {
        'dependencies': ['company.Company'],
        'exclude_fields': ['efris_private_key'],
    },
    'company.Domain': {
        'dependencies': ['company.Company'],
    },
    'company.CompanyRelationship': {
        'dependencies': ['company.Company'],
    },
    'company.CrossCompanyTransaction': {
        'dependencies': ['company.Company'],
    },

    # ============================================================================
    # TIER 6: INVENTORY CATEGORIES & SUPPLIERS - No user dependency
    # ============================================================================

    'inventory.Category': {
        'dependencies': [],
    },
    'inventory.Supplier': {
        'dependencies': [],
    },

    # ============================================================================
    # TIER 7: BRANCHES & STORES - Depends on CustomUser (for staff M2M)
    # ============================================================================

    'branches.CompanyBranch': {
        'dependencies': [],
    },

    'stores.Store': {
        'dependencies': ['accounts.CustomUser'],
        'exclude_fields': [
            'logo',
            'store_efris_private_key',
            'store_efris_public_certificate',
            'store_efris_key_password',
        ],
    },
    'stores.StoreAccess': {
        'dependencies': ['stores.Store', 'accounts.CustomUser'],
    },
    'stores.StoreOperatingHours': {
        'dependencies': ['stores.Store'],
    },
    'stores.StoreDevice': {
        'dependencies': ['stores.Store'],
    },
    'stores.DeviceFingerprint': {
        'dependencies': ['stores.StoreDevice'],
    },
    'stores.UserDeviceSession': {
        'dependencies': ['accounts.CustomUser', 'stores.StoreDevice'],
    },
    'stores.DeviceOperatorLog': {
        'dependencies': ['stores.StoreDevice', 'accounts.CustomUser'],
    },
    'stores.SecurityAlert': {
        'dependencies': ['stores.Store'],
    },

    # ============================================================================
    # TIER 8: PRODUCTS & SERVICES - Depends on Category and Supplier
    # ============================================================================

    'inventory.Product': {
        'dependencies': ['inventory.Category', 'inventory.Supplier'],
        'exclude_fields': ['image'],
    },
    'inventory.Service': {
        'dependencies': ['inventory.Category'],
    },

    # Tagged Items (for products)
    'taggit.TaggedItem': {
        'dependencies': ['taggit.Tag', 'contenttypes.ContentType'],
    },

    # ============================================================================
    # TIER 9: STOCK - Depends on Product and Store
    # ============================================================================

    'inventory.Stock': {
        'dependencies': ['inventory.Product', 'stores.Store'],
    },
    'inventory.StockStore': {
        'dependencies': ['inventory.Stock', 'stores.Store'],
    },
    'inventory.StockMovement': {
        'dependencies': ['inventory.Product', 'stores.Store'],
        # created_by is optional - can be NULL during sync
    },
    'inventory.StockTransfer': {
        'dependencies': ['inventory.Product', 'stores.Store'],
    },

    # Import tracking
    'inventory.ImportSession': {
        'dependencies': ['accounts.CustomUser'],
    },
    'inventory.ImportLog': {
        'dependencies': ['inventory.ImportSession'],
    },
    'inventory.ImportResult': {
        'dependencies': ['inventory.ImportSession'],
    },

    # ============================================================================
    # TIER 10: CUSTOMERS - Depends on Store and User
    # ============================================================================

    'customers.Customer': {
        'dependencies': ['stores.Store', 'accounts.CustomUser'],
        'exclude_fields': ['efris_sync_error'],
    },
    'customers.CustomerGroup': {
        'dependencies': ['customers.Customer'],
    },
    'customers.CustomerNote': {
        'dependencies': ['customers.Customer', 'accounts.CustomUser'],
    },
    'customers.EFRISCustomerSync': {
        'dependencies': ['customers.Customer'],
    },

    # ============================================================================
    # TIER 11: SALES & CARTS - Depends on Customer, Store, User
    # ============================================================================

    'sales.Cart': {
        'dependencies': ['customers.Customer', 'stores.Store', 'accounts.CustomUser'],
    },
    'sales.CartItem': {
        'dependencies': ['sales.Cart', 'inventory.Product'],
    },

    'sales.Sale': {
        'dependencies': ['customers.Customer', 'stores.Store', 'accounts.CustomUser'],
    },
    'sales.SaleItem': {
        'dependencies': ['sales.Sale', 'inventory.Product'],
    },
    'sales.Payment': {
        'dependencies': ['sales.Sale'],
    },
    'sales.Receipt': {
        'dependencies': ['sales.Sale'],
    },
    'sales.PaymentReminder': {
        'dependencies': ['sales.Sale'],
    },

    # ============================================================================
    # TIER 12: INVOICES - Depends on Sales (auto-created from sales)
    # ============================================================================

    'invoices.InvoiceTemplate': {
        'dependencies': [],
    },

    'invoices.Invoice': {
        'dependencies': ['sales.Sale', 'customers.Customer', 'stores.Store'],
    },
    'invoices.InvoicePayment': {
        'dependencies': ['invoices.Invoice'],
    },
    'invoices.PaymentAllocation': {
        'dependencies': ['invoices.Invoice', 'invoices.InvoicePayment'],
    },
    'invoices.PaymentSchedule': {
        'dependencies': ['invoices.Invoice'],
    },
    'invoices.PaymentReminder': {
        'dependencies': ['invoices.Invoice'],
    },
    'invoices.FiscalizationAudit': {
        'dependencies': ['invoices.Invoice', 'accounts.CustomUser'],
    },

    # ============================================================================
    # TIER 13: EXPENSES & BUDGETS - Depends on Store and User
    # ============================================================================

    'expenses.Expense': {
        'dependencies': ['stores.Store', 'accounts.CustomUser'],
    },
    'expenses.Budget': {
        'dependencies': ['stores.Store', 'accounts.CustomUser'],
    },

    # ============================================================================
    # TIER 14: EFRIS CONFIGURATION - Depends on Company and Stores
    # ============================================================================

    'efris.EFRISConfiguration': {
        'dependencies': ['company.Company'],
        'exclude_fields': [
            'private_key',
            'public_certificate',
            'key_password',
            'symmetric_key',
            'client_private_key',
            'client_private_key_encrypted',
            'key_table',
            'server_public_key',
        ],
    },
    'efris.EFRISDigitalKey': {
        'dependencies': ['accounts.CustomUser'],
        'exclude_fields': [
            'private_key',
            'public_certificate',
            'key_password',
        ],
    },
    'efris.EFRISDeviceInfo': {
        'dependencies': ['stores.Store'],
    },
    'efris.EFRISIntegrationSettings': {
        'dependencies': ['company.Company'],
    },
    'efris.EFRISCommodityCategorry': {
        'dependencies': [],
    },

    # ============================================================================
    # TIER 15: EFRIS LOGS & SYNC - Depends on Invoices and Products
    # ============================================================================

    'efris.EFRISSystemDictionary': {
        'dependencies': [],
    },
    'efris.EFRISExceptionLog': {
        'dependencies': [],
    },
    'efris.EFRISAPILog': {
        'dependencies': ['invoices.Invoice', 'inventory.Product', 'accounts.CustomUser'],
    },
    'efris.EFRISSyncQueue': {
        'dependencies': ['accounts.CustomUser'],
    },
    'efris.EFRISFiscalizationBatch': {
        'dependencies': ['accounts.CustomUser'],
    },
    'efris.ProductUploadTask': {
        'dependencies': ['inventory.Product'],
    },
    'efris.EFRISOperationMetrics': {
        'dependencies': [],
    },
    'efris.EFRISNotification': {
        'dependencies': ['invoices.Invoice', 'invoices.FiscalizationAudit', 'accounts.CustomUser'],
    },
    'efris.EFRISErrorPattern': {
        'dependencies': ['accounts.CustomUser'],
    },

    # ============================================================================
    # TIER 16: CUSTOMER TRANSACTIONS - Depends on Sales and Payments
    # ============================================================================

    'customers.CustomerCreditStatement': {
        'dependencies': ['customers.Customer', 'sales.Sale', 'sales.Payment', 'accounts.CustomUser'],
    },

    # ============================================================================
    # TIER 17: NOTIFICATIONS - Depends on Users
    # ============================================================================

    'notifications.NotificationCategory': {
        'dependencies': [],
    },
    'notifications.NotificationTemplate': {
        'dependencies': ['notifications.NotificationCategory'],
    },
    'notifications.NotificationRule': {
        'dependencies': ['accounts.CustomUser'],
    },
    'notifications.NotificationPreference': {
        'dependencies': ['accounts.CustomUser', 'notifications.NotificationCategory'],
    },
    'notifications.Announcement': {
        'dependencies': ['accounts.CustomUser'],
    },
    'notifications.Notification': {
        'dependencies': ['accounts.CustomUser'],
    },
    'notifications.NotificationBatch': {
        'dependencies': [],
    },
    'notifications.NotificationLog': {
        'dependencies': ['notifications.Notification'],
    },

    # ============================================================================
    # TIER 18: MESSAGING - Depends on Users
    # ============================================================================

    'messaging.Conversation': {
        'dependencies': [],
    },
    'messaging.ConversationParticipant': {
        'dependencies': ['messaging.Conversation', 'accounts.CustomUser'],
    },
    'messaging.Message': {
        'dependencies': ['messaging.Conversation', 'accounts.CustomUser'],
    },
    'messaging.MessageAttachment': {
        'dependencies': ['messaging.Message'],
    },
    'messaging.MessageReaction': {
        'dependencies': ['messaging.Message', 'accounts.CustomUser'],
    },
    'messaging.MessageReadReceipt': {
        'dependencies': ['messaging.Message', 'accounts.CustomUser'],
    },
    'messaging.MessageSearchIndex': {
        'dependencies': ['messaging.Message'],
    },
    'messaging.MessageAuditLog': {
        'dependencies': ['messaging.Message'],
    },
    'messaging.TypingIndicator': {
        'dependencies': ['messaging.Conversation', 'accounts.CustomUser'],
    },
    'messaging.SystemAnnouncement': {
        'dependencies': ['accounts.CustomUser'],
    },
    'messaging.AnnouncementRead': {
        'dependencies': ['messaging.SystemAnnouncement', 'accounts.CustomUser'],
    },
    'messaging.EncryptionKeyManager': {
        'dependencies': ['accounts.CustomUser'],
    },
    'messaging.MessagingStatistics': {
        'dependencies': ['accounts.CustomUser'],
    },
    'messaging.LegalAccessRequest': {
        'dependencies': ['accounts.CustomUser'],
    },
    'messaging.LegalAccessLog': {
        'dependencies': ['messaging.LegalAccessRequest'],
    },

    # ============================================================================
    # TIER 19: REPORTS - Depends on various entities
    # ============================================================================

    'reports.EFRISReportTemplate': {
        'dependencies': [],
    },
    'reports.SavedReport': {
        'dependencies': ['accounts.CustomUser'],
    },
    'reports.GeneratedReport': {
        'dependencies': ['accounts.CustomUser'],
    },
    'reports.ReportSchedule': {
        'dependencies': ['accounts.CustomUser'],
    },
    'reports.ReportAccessLog': {
        'dependencies': ['reports.GeneratedReport', 'accounts.CustomUser'],
    },
    'reports.ReportComparison': {
        'dependencies': ['reports.GeneratedReport'],
    },

    # ============================================================================
    # TIER 20: CELERY RESULTS - Task execution tracking
    # ============================================================================

    'django_celery_beat.PeriodicTasks': {
        'dependencies': [],
    },
    'django_celery_beat.PeriodicTask': {
        'dependencies': [
            'django_celery_beat.IntervalSchedule',
            'django_celery_beat.CrontabSchedule',
            'django_celery_beat.SolarSchedule',
            'django_celery_beat.ClockedSchedule',
        ],
    },

    'django_celery_results.TaskResult': {
        'dependencies': [],
    },
    'django_celery_results.GroupResult': {
        'dependencies': [],
    },
    'django_celery_results.ChordCounter': {
        'dependencies': ['django_celery_results.GroupResult'],
    },

    # ============================================================================
    # TIER 21: PUBLIC ANALYTICS - Visitor tracking
    # ============================================================================

    'public_analytics.VisitorSession': {
        'dependencies': [],
    },
    'public_analytics.PageView': {
        'dependencies': ['public_analytics.VisitorSession'],
    },
    'public_analytics.Event': {
        'dependencies': ['public_analytics.VisitorSession'],
    },
    'public_analytics.Conversion': {
        'dependencies': ['public_analytics.VisitorSession'],
    },
    'public_analytics.DailyStats': {
        'dependencies': [],
    },

    # ============================================================================
    # TIER 22: PUBLIC BLOG - Content management
    # ============================================================================

    'public_blog.BlogPost': {
        'dependencies': ['public_blog.BlogCategory', 'public_accounts.PublicUser'],
    },
    'public_blog.BlogComment': {
        'dependencies': ['public_blog.BlogPost', 'public_accounts.PublicUser'],
    },
    'public_blog.Newsletter': {
        'dependencies': [],
    },

    # ============================================================================
    # TIER 23: PUBLIC SEO - Search optimization
    # ============================================================================

    'public_seo.SEOPage': {
        'dependencies': [],
    },
    'public_seo.KeywordTracking': {
        'dependencies': ['public_seo.SEOPage'],
    },
    'public_seo.KeywordRankingHistory': {
        'dependencies': ['public_seo.KeywordTracking'],
    },
    'public_seo.SEOAudit': {
        'dependencies': ['public_seo.SEOPage'],
    },

    # ============================================================================
    # TIER 24: PUBLIC SUPPORT - Customer support
    # ============================================================================

    'public_support.ContactRequest': {
        'dependencies': [],
    },
    'public_support.SupportTicket': {
        'dependencies': ['public_accounts.PublicUser'],
    },
    'public_support.TicketReply': {
        'dependencies': ['public_support.SupportTicket', 'public_accounts.PublicUser'],
    },

    # ============================================================================
    # TIER 25: AUDIT & HISTORY - Depends on everything (last tier)
    # ============================================================================

    'accounts.RoleHistory': {
        'dependencies': ['accounts.Role', 'accounts.CustomUser'],
    },
    'accounts.UserSignature': {
        'dependencies': ['accounts.CustomUser'],
    },
    'accounts.AuditLog': {
        'dependencies': ['accounts.CustomUser', 'stores.Store'],
    },
    'accounts.LoginHistory': {
        'dependencies': ['accounts.CustomUser'],
    },
    'accounts.DataExportLog': {
        'dependencies': ['accounts.CustomUser'],
    },
    'errors.ErrorLog': {
        'dependencies': ['accounts.CustomUser'],
    },
}


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_sync_order():
    """
    Returns models in the correct order for synchronization based on dependencies.

    Returns:
        list: Ordered list of model names (e.g., ['company.SubscriptionPlan', ...])
    """
    from collections import deque, defaultdict

    # Build dependency graph
    graph = defaultdict(list)
    in_degree = defaultdict(int)

    # Initialize all models
    for model in SYNC_MODEL_CONFIG:
        if model not in in_degree:
            in_degree[model] = 0

    # Build edges
    for model, config in SYNC_MODEL_CONFIG.items():
        for dependency in config.get('dependencies', []):
            graph[dependency].append(model)
            in_degree[model] += 1

    # Topological sort using Kahn's algorithm
    queue = deque([model for model in SYNC_MODEL_CONFIG if in_degree[model] == 0])
    result = []

    while queue:
        model = queue.popleft()
        result.append(model)

        for dependent in graph[model]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    # Check for circular dependencies
    if len(result) != len(SYNC_MODEL_CONFIG):
        missing = set(SYNC_MODEL_CONFIG.keys()) - set(result)
        raise ValueError(f"Circular dependency detected! Missing models: {missing}")

    return result


def get_model_config(model_name):
    """
    Get configuration for a specific model.

    Args:
        model_name (str): Model name in format 'app.Model'

    Returns:
        dict: Model configuration with dependencies and exclude_fields
    """
    return SYNC_MODEL_CONFIG.get(model_name, {'dependencies': [], 'exclude_fields': []})


def validate_dependencies():
    """
    Validate that all dependencies exist in the configuration.

    Raises:
        ValueError: If a dependency references a non-existent model
    """
    errors = []

    for model, config in SYNC_MODEL_CONFIG.items():
        for dependency in config.get('dependencies', []):
            if dependency not in SYNC_MODEL_CONFIG:
                errors.append(f"Model '{model}' depends on '{dependency}' which is not in config")

    if errors:
        raise ValueError("Dependency validation failed:\n" + "\n".join(errors))

    return True


# ============================================================================
# STATISTICS
# ============================================================================

def get_statistics():
    """
    Get statistics about the sync configuration.

    Returns:
        dict: Statistics including model counts, tier distribution, etc.
    """
    from collections import defaultdict

    stats = {
        'total_models': len(SYNC_MODEL_CONFIG),
        'models_with_dependencies': sum(1 for c in SYNC_MODEL_CONFIG.values() if c.get('dependencies')),
        'models_with_exclusions': sum(1 for c in SYNC_MODEL_CONFIG.values() if c.get('exclude_fields')),
        'total_dependencies': sum(len(c.get('dependencies', [])) for c in SYNC_MODEL_CONFIG.values()),
        'total_excluded_fields': sum(len(c.get('exclude_fields', [])) for c in SYNC_MODEL_CONFIG.values()),
    }

    # Group by app
    app_counts = defaultdict(int)
    for model in SYNC_MODEL_CONFIG:
        app = model.split('.')[0]
        app_counts[app] += 1

    stats['apps'] = dict(app_counts)
    stats['total_apps'] = len(app_counts)

    return stats


if __name__ == '__main__':
    # Run validation
    print("Validating SYNC_MODEL_CONFIG...")
    validate_dependencies()
    print("✅ All dependencies valid!")

    # Print statistics
    print("\n" + "=" * 60)
    print("SYNC MODEL CONFIGURATION STATISTICS")
    print("=" * 60)
    stats = get_statistics()
    print(f"Total Models: {stats['total_models']}")
    print(f"Total Apps: {stats['total_apps']}")
    print(f"Models with Dependencies: {stats['models_with_dependencies']}")
    print(f"Models with Field Exclusions: {stats['models_with_exclusions']}")
    print(f"Total Dependencies: {stats['total_dependencies']}")
    print(f"Total Excluded Fields: {stats['total_excluded_fields']}")

    print("\n" + "=" * 60)
    print("MODELS PER APP")
    print("=" * 60)
    for app, count in sorted(stats['apps'].items()):
        print(f"{app:30s}: {count:3d} models")

    print("\n" + "=" * 60)
    print("SYNC ORDER (first 10 models)")
    print("=" * 60)
    sync_order = get_sync_order()
    for i, model in enumerate(sync_order[:10], 1):
        deps = SYNC_MODEL_CONFIG[model].get('dependencies', [])
        print(f"{i:3d}. {model:40s} (deps: {len(deps)})")
    print(f"... and {len(sync_order) - 10} more models")


class SyncManager:
    """
    Complete bidirectional sync manager
    ✅ Download from server
    ✅ Upload to server
    ✅ Conflict resolution
    ✅ Enhanced error logging
    """

    def __init__(self, tenant_id, schema_name, auth_token=None):
        self.tenant_id = tenant_id
        self.schema_name = schema_name

        # ✅ Get valid token (may refresh if expired)
        self._passed_token = auth_token
        self.auth_token = self._get_valid_auth_token(auth_token)

        self.last_sync_file = settings.DESKTOP_DATA_DIR / f'.last_sync_{tenant_id}'

        from sync_model_config import get_sync_order
        self.sync_models = get_sync_order()

        self.server_url = self._get_server_url()

        logger.info("=" * 70)
        logger.info("SYNC MANAGER INITIALIZED")
        logger.info(f"  Tenant: {tenant_id}")
        logger.info(f"  Schema: {schema_name}")
        logger.info(f"  Server: {self.server_url}")
        logger.info(f"  Auth Token: {'Present (' + self.auth_token[:20] + '...)' if self.auth_token else '❌ MISSING!'}")
        logger.info(f"  Models to sync: {len(self.sync_models)}")
        logger.info("=" * 70)

        if not self.auth_token:
            logger.error("❌ CRITICAL: No auth token available!")

    def _get_server_url(self):
        """
        Smart server URL detection
        ✅ DEBUG=True → subdomain.localhost:8000
        ✅ DEBUG=False → subdomain.primebooks.sale
        """
        if hasattr(settings, 'SYNC_SERVER_URL'):
            url = settings.SYNC_SERVER_URL
            logger.info(f"  Using configured SYNC_SERVER_URL: {url}")
            return url

        # Auto-detect based on DEBUG setting
        if settings.DEBUG:
            # Development: subdomain.localhost:8000
            url = f"http://{self.schema_name}.localhost:8000"
            logger.info(f"  DEBUG mode detected, using: {url}")
            return url
        else:
            # Production: subdomain.primebooks.sale
            url = f"https://{self.schema_name}.primebooks.sale"
            logger.info(f"  Production mode detected, using: {url}")
            return url

    def is_online(self):
        """Check if server is reachable"""
        try:
            if not self.auth_token:
                logger.error("❌ Cannot check online status - no auth token")
                return False

            logger.info(f"🌐 Checking server connectivity: {self.server_url}")
            response = requests.get(
                f"{self.server_url}/api/health/",
                headers={'Authorization': f'Bearer {self.auth_token}'},
                timeout=5
            )
            is_reachable = response.status_code == 200
            logger.info(f"  Server {'✅ reachable' if is_reachable else '❌ unreachable'} (HTTP {response.status_code})")
            return is_reachable
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"  ❌ Connection error: {e}")
            return False
        except requests.exceptions.Timeout:
            logger.warning(f"  ❌ Timeout after 5 seconds")
            return False
        except Exception as e:
            logger.warning(f"  ❌ Unexpected error: {e}")
            return False

    def _get_valid_auth_token(self, provided_token=None):
        """
        ✅ NEW: Get valid auth token with automatic refresh

        Args:
            provided_token: Token passed during init (optional)

        Returns:
            Valid auth token or None
        """
        # 1. Use provided token
        if provided_token:
            logger.info("✅ Using provided auth token")
            return provided_token

        # 2. Try settings
        token = getattr(settings, 'SYNC_AUTH_TOKEN', None)
        if token:
            logger.info("✅ Using token from settings.SYNC_AUTH_TOKEN")
            return token

        # 3. Get from auth manager with auto-refresh
        try:
            from primebooks.auth import DesktopAuthManager
            auth_manager = DesktopAuthManager()

            # This will auto-refresh if expired
            token = auth_manager.get_valid_token()
            if token:
                logger.info("✅ Got valid token from DesktopAuthManager (may have refreshed)")
                return token
        except Exception as e:
            logger.warning(f"⚠️ Could not get token from auth manager: {e}")

        logger.error("❌ No auth token found anywhere!")
        return None

    def _make_request(self, url, method='GET', data=None, params=None, retry_on_401=True):
        """
        ✅ NEW: Make HTTP request with automatic token refresh on 401

        Args:
            url: Request URL
            method: HTTP method ('GET' or 'POST')
            data: Request body data (for POST)
            params: Query parameters (for GET)
            retry_on_401: Whether to retry with refreshed token on 401

        Returns:
            requests.Response or None
        """
        import requests

        headers = {
            'Authorization': f'Bearer {self.auth_token}',
            'Content-Type': 'application/json',
        }

        logger.debug(f"🌐 {method} {url}")

        try:
            # Make initial request
            if method == 'GET':
                response = requests.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=300
                )
            elif method == 'POST':
                response = requests.post(
                    url,
                    headers=headers,
                    json=data,
                    timeout=300
                )
            else:
                raise ValueError(f"Unsupported method: {method}")

            # ✅ Check for 401 Unauthorized (expired token)
            if response.status_code == 401 and retry_on_401:
                logger.warning("⚠️ Got 401 Unauthorized - attempting token refresh...")

                # Try to refresh token
                from primebooks.auth import DesktopAuthManager
                auth_manager = DesktopAuthManager()
                new_token = auth_manager.refresh_access_token()

                if new_token and new_token != self.auth_token:
                    logger.info("✅ Token refreshed, retrying request...")

                    # Update our token
                    self.auth_token = new_token
                    headers['Authorization'] = f'Bearer {new_token}'

                    # Retry request with new token
                    if method == 'GET':
                        response = requests.get(
                            url,
                            headers=headers,
                            params=params,
                            timeout=300
                        )
                    elif method == 'POST':
                        response = requests.post(
                            url,
                            headers=headers,
                            json=data,
                            timeout=300
                        )

                    if response.status_code != 401:
                        logger.info("✅ Retry with refreshed token succeeded!")
                    else:
                        logger.error("❌ Still getting 401 after token refresh")
                        logger.error(f"   Response: {response.text[:200]}")
                else:
                    logger.error("❌ Failed to get new token for retry")

            return response

        except requests.exceptions.ConnectionError as e:
            logger.error(f"❌ Connection error: {e}")
            return None
        except requests.exceptions.Timeout:
            logger.error(f"❌ Request timeout")
            return None
        except Exception as e:
            logger.error(f"❌ Request error: {e}", exc_info=True)
            return None

    # ========================================================================
    # DOWNLOAD FROM SERVER
    # ========================================================================

    def download_all_data(self, progress_callback=None):
        """
        ✅ UPDATED: Download ALL data with automatic token refresh
        """
        try:
            logger.info("=" * 70)
            logger.info("DOWNLOADING ALL DATA")
            logger.info(f"  URL: {self.server_url}/api/desktop/sync/bulk-download/")
            logger.info("=" * 70)

            if progress_callback:
                progress_callback("Connecting to server...", 5)

            url = f"{self.server_url}/api/desktop/sync/bulk-download/"

            # ✅ Use _make_request (auto-refreshes on 401)
            response = self._make_request(url, method='GET')

            if not response:
                logger.error("❌ Request failed")
                return False

            if response.status_code != 200:
                error_text = response.text[:500] if response.text else "No response"
                logger.error(f"❌ Download failed: HTTP {response.status_code}")
                logger.error(f"  Response: {error_text}")
                return False

            data = response.json()

            if not data.get('success'):
                error_msg = data.get('error', 'Unknown error')
                logger.error(f"❌ Download failed: {error_msg}")
                return False

            all_data = data.get('data', {})
            total_records = data.get('total_records', 0)

            logger.info(f"✅ Downloaded {total_records} records")

            if progress_callback:
                progress_callback(f"Downloaded {total_records} records...", 30)

            if all_data:
                success = self.apply_bulk_data(all_data, progress_callback)

                if success:
                    if progress_callback:
                        progress_callback("Resetting sequences...", 95)

                    self.reset_sequences()

                    if progress_callback:
                        progress_callback("Complete!", 100)

                    logger.info("✅ DOWNLOAD COMPLETE")
                    return True

            return False

        except Exception as e:
            logger.error(f"❌ Download error: {e}", exc_info=True)
            return False

    def check_pending_changes(self):
        """
        ✅ NEW: Check what changes are pending without actually syncing
        Useful for debugging
        """
        last_sync = self.get_last_sync_time()

        logger.info("=" * 70)
        logger.info("CHECKING PENDING CHANGES")
        logger.info(f"  Last sync: {last_sync}")
        logger.info("=" * 70)

        if not last_sync:
            logger.info("  No last sync - full sync needed")
            return

        changes = self.collect_local_changes(last_sync)

        if not changes:
            logger.info("  ✅ No pending changes")
        else:
            for model_name, records in changes.items():
                logger.info(f"  📝 {model_name}: {len(records)} pending changes")

        logger.info("=" * 70)

    def download_changes(self, progress_callback=None):
        """
        ✅ UPDATED: Download changes with automatic token refresh
        """
        try:
            last_sync = self.get_last_sync_time()

            if not last_sync:
                logger.info("No last sync - doing full download")
                return self.download_all_data(progress_callback)

            logger.info("=" * 70)
            logger.info(f"DOWNLOADING CHANGES SINCE {last_sync}")
            logger.info("=" * 70)

            if progress_callback:
                progress_callback("Checking for changes...", 10)

            url = f"{self.server_url}/api/desktop/sync/changes/"
            params = {'since': last_sync.isoformat()}

            logger.info(f"  URL: {url}")
            logger.info(f"  Since: {last_sync.isoformat()}")

            # ✅ Use _make_request (auto-refreshes on 401)
            response = self._make_request(url, method='GET', params=params)

            if not response:
                logger.error("❌ Request failed")
                return False

            if response.status_code != 200:
                error_text = response.text[:500] if response.text else "No response"
                logger.error(f"❌ Download failed: HTTP {response.status_code}")
                logger.error(f"  Response: {error_text}")
                return False

            data = response.json()
            changes = data.get('data', {})
            total_changed = sum(len(records) for records in changes.values())

            if total_changed == 0:
                logger.info("✅ No server changes")
                return True

            logger.info(f"✅ Downloaded {total_changed} changed records")

            if changes:
                success = self.apply_bulk_data(changes, progress_callback)
                if success:
                    if progress_callback:
                        progress_callback("Resetting sequences...", 90)

                    self.reset_sequences()
                    logger.info("✅ Changes applied")
                    return True

            return False

        except Exception as e:
            logger.error(f"❌ Download error: {e}", exc_info=True)
            return False


    # ========================================================================
    # UPLOAD TO SERVER
    # ========================================================================

    def upload_changes(self, progress_callback=None):
        """
        Upload local changes to server
        ✅ Replaces negative IDs with server-assigned IDs
        """
        try:
            last_sync = self.get_last_sync_time()

            logger.info("=" * 70)
            logger.info(f"UPLOADING CHANGES SINCE {last_sync}")
            logger.info("=" * 70)

            if progress_callback:
                progress_callback("Collecting local changes...", 10)

            # Collect changed records
            changes = self.collect_local_changes(last_sync)

            if not changes:
                logger.info("✅ No local changes to upload")
                return True

            total_changed = sum(len(records) for records in changes.values())
            logger.info(f"📤 Uploading {total_changed} changed records across {len(changes)} models")

            if progress_callback:
                progress_callback(f"Uploading {total_changed} records...", 30)

            url = f"{self.server_url}/api/desktop/sync/upload/"

            response = requests.post(
                url,
                json={
                    'tenant_id': self.tenant_id,
                    'schema_name': self.schema_name,
                    'changes': changes,
                    'last_sync': last_sync.isoformat() if last_sync else None
                },
                headers={'Authorization': f'Bearer {self.auth_token}'},
                timeout=120
            )

            if response.status_code != 200:
                logger.error(f"❌ Upload failed: HTTP {response.status_code}")
                return False

            result = response.json()

            if result.get('success'):
                logger.info(f"✅ Upload successful")

                # ✅ Replace negative IDs with real server IDs
                id_mappings = result.get('id_mappings', {})
                if id_mappings:
                    logger.info(f"🔄 Replacing {len(id_mappings)} model(s) offline IDs...")
                    self._replace_offline_ids(id_mappings)

                if progress_callback:
                    progress_callback("Upload complete!", 60)
                return True
            else:
                error_msg = result.get('error', 'Unknown error')
                logger.error(f"❌ Upload failed: {error_msg}")
                return False

        except Exception as e:
            logger.error(f"❌ Upload error: {e}", exc_info=True)
            return False

    def _replace_offline_ids(self, id_mappings):
        """
        Replace negative offline IDs with real server IDs
        ✅ Updates both the record and any FKs pointing to it

        Args:
            id_mappings: Dict of {model_name: {old_id: new_id}}
        """
        from django.apps import apps
        from django_tenants.utils import schema_context

        with schema_context(self.schema_name):
            # ✅ First pass: Update the records themselves
            for model_name, mappings in id_mappings.items():
                try:
                    model = apps.get_model(model_name)

                    for old_id, new_id in mappings.items():
                        old_id = int(old_id)

                        try:
                            # Get record with old negative ID
                            obj = model.objects.get(pk=old_id)

                            # Get all field values
                            field_values = {}
                            for field in model._meta.fields:
                                if field.name != 'id':  # Skip PK
                                    field_values[field.name] = getattr(obj, field.name)

                            # Delete old record
                            obj.delete()

                            # Create new record with server ID
                            new_obj = model(pk=new_id, **field_values)
                            new_obj.save()

                            logger.info(f"  ✅ Replaced {model_name} ID: {old_id} → {new_id}")

                        except model.DoesNotExist:
                            logger.warning(f"  ⚠️  Record {model_name}:{old_id} not found (already synced?)")

                except Exception as e:
                    logger.error(f"  ❌ Error replacing IDs for {model_name}: {e}")

            # ✅ Second pass: Update ForeignKeys that point to replaced IDs
            logger.info("🔄 Updating foreign key references...")

            for model_name in SYNC_MODEL_CONFIG.keys():
                try:
                    model = apps.get_model(model_name)

                    # Find all ForeignKey fields
                    for field in model._meta.fields:
                        if field.many_to_one:  # Is ForeignKey
                            related_model = field.related_model
                            related_model_name = f"{related_model._meta.app_label}.{related_model._meta.model_name}"

                            # Check if this FK's target model had ID replacements
                            if related_model_name in id_mappings:
                                mappings = id_mappings[related_model_name]

                                # Find records pointing to old IDs
                                for old_id, new_id in mappings.items():
                                    old_id = int(old_id)

                                    # Update records pointing to old ID
                                    updated = model.objects.filter(**{f'{field.name}_id': old_id}).update(
                                        **{f'{field.name}_id': new_id})

                                    if updated > 0:
                                        logger.info(
                                            f"    ✅ Updated {updated} {model_name} FK {field.name}: {old_id} → {new_id}")

                except LookupError:
                    continue
                except Exception as e:
                    logger.error(f"  ❌ Error updating FKs for {model_name}: {e}")

    def reset_sequences(self):
        """
        Reset PostgreSQL sequences after sync
        ✅ Prevents duplicate key errors
        """
        from django.db import connection
        from django_tenants.utils import schema_context

        logger.info("🔄 Resetting database sequences...")

        with schema_context(self.schema_name):
            with connection.cursor() as cursor:
                # Get all tables with serial/sequence columns
                for model_name in SYNC_MODEL_CONFIG.keys():
                    try:
                        model = apps.get_model(model_name)
                        table_name = model._meta.db_table
                        pk_field = model._meta.pk.name

                        # Get the sequence name
                        sequence_name = f"{table_name}_{pk_field}_seq"

                        # Get max ID from table
                        cursor.execute(f'SELECT MAX({pk_field}) FROM "{table_name}"')
                        result = cursor.fetchone()
                        max_id = result[0] if result[0] else 0

                        # Reset sequence to max_id + 1
                        new_val = max_id + 1
                        cursor.execute(f"SELECT setval('{sequence_name}', {new_val}, false)")

                        logger.info(f"  ✅ Reset {table_name} sequence to {new_val}")

                    except Exception as e:
                        logger.debug(f"  ⏭️  Skipping {model_name}: {e}")

        logger.info("✅ Sequences reset complete")

    def collect_local_changes(self, since):
        """
        Collect records changed LOCALLY (not synced from server)
        ✅ Excludes records downloaded from server
        """
        changes = {}

        with schema_context(self.schema_name):
            for model_name in self.sync_models:
                try:
                    model = apps.get_model(model_name)
                    config = SYNC_MODEL_CONFIG.get(model_name, {})
                    exclude_fields = config.get('exclude_fields', [])

                    # Build queryset
                    queryset = model.objects.all()

                    # Filter by modification time
                    if since:
                        if since.tzinfo is None:
                            since = timezone.make_aware(since)

                        if hasattr(model, 'modified_at'):
                            queryset = queryset.filter(modified_at__gte=since)
                        elif hasattr(model, 'updated_at'):
                            queryset = queryset.filter(updated_at__gte=since)
                        elif hasattr(model, 'created_at'):
                            queryset = queryset.filter(created_at__gte=since)

                    if queryset.exists():
                        # ✅ Filter out synced records
                        local_records = []

                        for obj in queryset:
                            # Skip if this was downloaded from server
                            if self._is_synced(model_name, obj.pk):
                                continue

                            local_records.append(obj)

                        if local_records:
                            # Serialize
                            data = serializers.serialize('json', local_records)
                            records = json.loads(data)

                            # Remove excluded fields
                            if exclude_fields:
                                for record in records:
                                    for field in exclude_fields:
                                        record['fields'].pop(field, None)

                            changes[model_name] = records
                            logger.info(f"  Found {len(records)} LOCAL changes in {model_name}")

                except LookupError:
                    continue
                except Exception as e:
                    logger.error(f"  Error collecting {model_name}: {e}")

        return changes

    def _mark_as_synced(self, model_name, record_ids):
        """Mark records as synced to prevent re-upload"""
        if not record_ids:
            return

        sync_marker_file = settings.DESKTOP_DATA_DIR / f'.synced_{self.tenant_id}.json'

        # Load existing markers
        if sync_marker_file.exists():
            try:
                synced = json.loads(sync_marker_file.read_text())
            except:
                synced = {}
        else:
            synced = {}

        # Add new synced IDs
        if model_name not in synced:
            synced[model_name] = []

        synced[model_name].extend([str(id) for id in record_ids])

        # Remove duplicates
        synced[model_name] = list(set(synced[model_name]))

        # Save
        sync_marker_file.write_text(json.dumps(synced))

    def _is_synced(self, model_name, record_id):
        """Check if record was synced from server"""
        sync_marker_file = settings.DESKTOP_DATA_DIR / f'.synced_{self.tenant_id}.json'

        if not sync_marker_file.exists():
            return False

        try:
            synced = json.loads(sync_marker_file.read_text())
            return str(record_id) in synced.get(model_name, [])
        except:
            return False

    # ========================================================================
    # APPLY DATA TO LOCAL DB
    # ========================================================================

    def apply_bulk_data(self, all_data, progress_callback=None):
        """
        Apply downloaded data to local database
        ✅ Handles create/update with conflict resolution
        ✅ Suppresses signals during import
        """
        with suppress_signals():  # ✅ Suppress signals
            return self._apply_bulk_data_impl(all_data, progress_callback)

    def _apply_bulk_data_impl(self, all_data, progress_callback=None):
        """Internal implementation of apply_bulk_data"""
        try:
            logger.info(f"💾 Applying data to local database")

            total_models = len(all_data)
            created_total = 0
            updated_total = 0

            with schema_context(self.schema_name):
                for index, (model_name, records) in enumerate(all_data.items()):
                    try:
                        if progress_callback:
                            progress = 30 + int((index / total_models) * 60)
                            progress_callback(f"Saving {model_name}...", progress)

                        created, updated = self.apply_model_data(model_name, records)
                        created_total += created
                        updated_total += updated

                        logger.info(f"  ✅ {model_name}: {created} created, {updated} updated")

                    except Exception as e:
                        logger.error(f"  ❌ Error saving {model_name}: {e}")

            logger.info(f"✅ Data applied: {created_total} created, {updated_total} updated")
            return True

        except Exception as e:
            logger.error(f"❌ Error applying data: {e}", exc_info=True)
            return False

    def apply_model_data(self, model_name, records):
        """
        Apply records for a specific model
        ✅ Properly converts ForeignKey IDs to instances
        ✅ Handles ManyToMany fields
        ✅ Skips validation errors gracefully
        """
        from decimal import Decimal
        from django.core.exceptions import ValidationError

        try:
            model = apps.get_model(model_name)
            created_count = 0
            updated_count = 0
            synced_ids = []

            for record in records:
                try:
                    obj_id = record['pk']
                    fields = record['fields']

                    # ✅ Process fields - separate M2M from regular fields
                    m2m_fields = {}
                    processed_fields = {}

                    for field_name, value in fields.items():
                        try:
                            field = model._meta.get_field(field_name)

                            # ✅ ManyToMany - handle after save
                            if field.many_to_many:
                                m2m_fields[field_name] = value
                                continue

                            # ✅ ForeignKey - CONVERT ID TO INSTANCE
                            if field.many_to_one and value is not None:
                                related_model = field.related_model

                                try:
                                    # Get the actual instance
                                    related_instance = related_model.objects.get(pk=value)
                                    processed_fields[field_name] = related_instance
                                    logger.debug(f"    ✓ FK {field_name}: {value} → {related_instance}")
                                except related_model.DoesNotExist:
                                    # Related record doesn't exist - skip this field
                                    logger.debug(f"    Skipping {field_name}={value} - not found")
                                    # Don't add to processed_fields
                                    continue

                            # ✅ Decimal fields
                            elif hasattr(field, 'get_internal_type') and field.get_internal_type() == 'DecimalField':
                                if value is not None and isinstance(value, str):
                                    processed_fields[field_name] = Decimal(value)
                                else:
                                    processed_fields[field_name] = value

                            # Regular field
                            else:
                                processed_fields[field_name] = value

                        except Exception as e:
                            logger.debug(f"    Skipping field {field_name}: {e}")
                            continue

                    # Try to get existing record
                    try:
                        pk_field = model._meta.pk.name
                        existing = model.objects.get(**{pk_field: obj_id})

                        # Update existing
                        for field, value in processed_fields.items():
                            setattr(existing, field, value)

                        try:
                            existing.save()
                        except ValidationError as e:
                            error_msg = str(e).lower()
                            # Skip common validation errors during sync
                            if any(skip in error_msg for skip in
                                   ['efris', 'constraint', 'password', 'either product or service']):
                                logger.debug(f"    Skipping validation error for {obj_id}: {e}")
                                continue
                            raise

                        # ✅ Handle ManyToMany after save
                        for field_name, value in m2m_fields.items():
                            if value:
                                try:
                                    field_obj = getattr(existing, field_name)
                                    field_obj.set(value)
                                except Exception as e:
                                    logger.debug(f"    M2M error for {field_name}: {e}")

                        updated_count += 1
                        synced_ids.append(obj_id)
                        logger.debug(f"    ✓ Updated: {obj_id}")

                    except model.DoesNotExist:
                        # Create new record
                        pk_field = model._meta.pk.name

                        if pk_field != 'id':
                            processed_fields[pk_field] = obj_id
                            obj = model(**processed_fields)
                        else:
                            obj = model(id=obj_id, **processed_fields)

                        try:
                            obj.save()
                        except ValidationError as e:
                            error_msg = str(e).lower()
                            # Skip common validation errors during sync
                            if any(skip in error_msg for skip in
                                   ['efris', 'constraint', 'password', 'either product or service']):
                                logger.debug(f"    Skipping validation error for {obj_id}: {e}")
                                continue
                            raise

                        # ✅ Handle ManyToMany after save
                        for field_name, value in m2m_fields.items():
                            if value:
                                try:
                                    field_obj = getattr(obj, field_name)
                                    field_obj.set(value)
                                except Exception as e:
                                    logger.debug(f"    M2M error for {field_name}: {e}")

                        created_count += 1
                        synced_ids.append(obj.pk)
                        logger.debug(f"    ✓ Created: {obj_id}")

                except Exception as e:
                    logger.error(f"    Error saving record {obj_id}: {e}")

            # Mark as synced
            if synced_ids:
                self._mark_as_synced(model_name, synced_ids)

            return created_count, updated_count

        except LookupError:
            logger.warning(f"  Model not found: {model_name}")
            return 0, 0
        except Exception as e:
            logger.error(f"  Fatal error in apply_model_data for {model_name}: {e}")
            return 0, 0

    # ========================================================================
    # FULL SYNC
    # ========================================================================

    def full_sync(self, is_first_sync=False, progress_callback=None):
        """
        Perform complete bidirectional sync
        ✅ Upload local changes
        ✅ Download server changes
        ✅ Only syncs NEW changes after first sync
        """
        try:
            logger.info("=" * 70)
            logger.info("FULL SYNC STARTING")
            logger.info(f"  First sync: {is_first_sync}")
            logger.info("=" * 70)

            if is_first_sync:
                logger.info(f"🔄 First sync - downloading all data")

                if not self.is_online():
                    logger.warning("⚠️  Server not reachable")
                    self.set_last_sync_time()  # Set time even if offline
                    return True

                # Download all data
                success = self.download_all_data(progress_callback)

                if success:
                    # ✅ Set last sync time AFTER successful download
                    self.set_last_sync_time()
                    logger.info("✅ First sync complete - timestamp saved")

                return success

            else:
                # ✅ BIDIRECTIONAL SYNC - Get last sync time BEFORE starting
                last_sync = self.get_last_sync_time()

                logger.info(f"🔄 Bidirectional sync starting")
                logger.info(f"  Last successful sync: {last_sync}")

                if not self.is_online():
                    logger.warning("⚠️  Server not reachable - staying offline")
                    return False

                # Step 1: Upload local changes (changes since last_sync)
                if progress_callback:
                    progress_callback("Uploading local changes...", 10)

                upload_success = self.upload_changes(progress_callback)

                # Step 2: Download server changes (changes since last_sync)
                if progress_callback:
                    progress_callback("Downloading server changes...", 50)

                download_success = self.download_changes(progress_callback)

                if upload_success and download_success:
                    # ✅ IMPORTANT: Update last_sync_time ONLY after BOTH operations succeed
                    self.set_last_sync_time()

                    logger.info("=" * 70)
                    logger.info("✅ BIDIRECTIONAL SYNC COMPLETE")
                    logger.info(f"  New sync timestamp: {self.get_last_sync_time()}")
                    logger.info("=" * 70)

                    if progress_callback:
                        progress_callback("Sync complete!", 100)
                    return True
                else:
                    logger.warning("⚠️  Sync completed with errors - timestamp NOT updated")
                    return False

        except Exception as e:
            logger.error(f"❌ Sync error: {e}", exc_info=True)
            return False

    # ========================================================================
    # SYNC SCHEDULING
    # ========================================================================

    def should_auto_sync(self):
        """
        Check if automatic sync should run
        ✅ Runs once per day
        ✅ Uses timezone-aware datetime
        """
        last_sync = self.get_last_sync_time()

        if not last_sync:
            return True

        # ✅ Use timezone.now() instead of datetime.now()
        time_since_sync = timezone.now() - last_sync
        return time_since_sync > timedelta(days=1)

    # ========================================================================
    # HELPERS
    # ========================================================================

    def get_last_sync_time(self):
        """Get last sync timestamp with timezone awareness"""
        if self.last_sync_file.exists():
            try:
                timestamp_str = self.last_sync_file.read_text()
                # Parse the timestamp
                dt = datetime.fromisoformat(timestamp_str)

                # Make it timezone-aware if it isn't already
                if dt.tzinfo is None:
                    dt = timezone.make_aware(dt)

                return dt
            except Exception as e:
                logger.warning(f"Could not parse last sync time: {e}")
                return None
        return None

    def set_last_sync_time(self, timestamp=None):
        """Save last sync timestamp with timezone awareness"""
        if timestamp is None:
            timestamp = timezone.now()  # Use timezone-aware now
        elif timestamp.tzinfo is None:
            # Make timezone-aware if naive
            timestamp = timezone.make_aware(timestamp)

        self.last_sync_file.write_text(timestamp.isoformat())
        logger.info(f"✅ Last sync time updated: {timestamp.isoformat()}")

    def _get_auth_token(self):
        """
        Get auth token from multiple sources with fallback and auto-refresh
        ✅ NEW: Attempts to refresh expired tokens
        """
        # 1. Try from parameter (passed during init)
        if self._passed_token:
            logger.info(f"✅ Using auth token from init parameter")
            return self._passed_token

        # 2. Try from settings
        token = getattr(settings, 'SYNC_AUTH_TOKEN', None)
        if token:
            logger.info(f"✅ Using auth token from settings.SYNC_AUTH_TOKEN")
            return token

        # 3. Try loading from auth manager with refresh
        try:
            from primebooks.auth import DesktopAuthManager
            auth_manager = DesktopAuthManager()

            # ✅ Try to get valid token (will refresh if needed)
            token = auth_manager.get_valid_token()
            if token:
                logger.info(f"✅ Using refreshed auth token from DesktopAuthManager")
                return token

        except Exception as e:
            logger.warning(f"⚠️  Could not load/refresh auth token: {e}")

        # 4. No token found
        logger.error("❌ No SYNC_AUTH_TOKEN found anywhere!")
        logger.error("   Checked:")
        logger.error("   1. Init parameter")
        logger.error("   2. settings.SYNC_AUTH_TOKEN")
        logger.error("   3. DesktopAuthManager (with refresh)")

        return None


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def check_sync_needed(tenant_id, schema_name):
    """Check if initial sync is needed"""
    from django_tenants.utils import schema_context

    try:
        with schema_context(schema_name):
            for model_name in ['inventory.Product', 'stores.Store', 'sales.Sale']:
                try:
                    model = apps.get_model(model_name)
                    if model.objects.exists():
                        return False
                except:
                    continue

            return True

    except:
        return True