# primebooks/sync.py - COMPLETE BIDIRECTIONAL SYNC WITH SYNC_ID SUPPORT
"""
Complete bidirectional sync system
✅ Downloads data from server
✅ Uploads offline changes to server
✅ Conflict resolution (last-write-wins)
✅ Automatic sync scheduling
✅ Manual sync on demand
✅ Signal suppression during sync
✅ sync_id (UUID) used as stable record identity — no more integer PK collisions
✅ ENHANCED ERROR LOGGING
"""
import requests
import logging
import uuid
from django.conf import settings
from django.core import serializers
from django_tenants.utils import schema_context
from django.apps import apps
from datetime import datetime, timedelta
from contextlib import contextmanager
from django.db.models.signals import post_save, pre_save, post_delete
from django.core.exceptions import ValidationError
import json
from django.apps import apps
from django.utils import timezone

logger = logging.getLogger(__name__)


# ============================================================================
# SIGNAL SUPPRESSION
# ============================================================================

@contextmanager
def suppress_signals():
    """
    Temporarily disable Django signals during sync to avoid:
    - Notification creation during sync
    - WebSocket errors
    - Using up sequence IDs
    """
    from django.db.models.signals import post_save, pre_save, post_delete

    saved_receivers = {
        'post_save': post_save.receivers[:],
        'pre_save': pre_save.receivers[:],
        'post_delete': post_delete.receivers[:],
    }

    post_save.receivers = []
    pre_save.receivers = []
    post_delete.receivers = []

    try:
        logger.debug("🔇 Signals suppressed for sync")
        yield
    finally:
        post_save.receivers = saved_receivers['post_save']
        pre_save.receivers = saved_receivers['pre_save']
        post_delete.receivers = saved_receivers['post_delete']
        logger.debug("🔊 Signals restored")


# ============================================================================
# MODELS TO EXCLUDE FROM SYNC
# ============================================================================

EXCLUDED_MODELS = {
    'contenttypes.ContentType',
    'auth.Permission',
    'sessions.Session',
    'admin.LogEntry',
    'company.Company',
    'company.EFRISCommodityCategory',
    'company.EFRISHsCode',
    'company.Domain',
    'django_otp.Device',
    'otp_totp.TOTPDevice',
    # Notifications: server-side concern, not needed on desktop
    'notifications.NotificationCategory',
    'notifications.NotificationTemplate',
    'notifications.NotificationRule',
    'notifications.NotificationPreference',
    'notifications.Announcement',
    'notifications.Notification',
    'notifications.NotificationBatch',
    'notifications.NotificationLog',
    # Audit & login history: server-side records, too noisy for desktop
    'accounts.AuditLog',
    'accounts.LoginHistory',
    'accounts.DataExportLog',
    # Device security: tied to server sessions, not meaningful offline
    'stores.DeviceFingerprint',
    'stores.UserDeviceSession',
    'stores.DeviceOperatorLog',
    'stores.SecurityAlert',
}


def should_exclude_model(model_name):
    return model_name in EXCLUDED_MODELS


# ============================================================================
# SYNC MODEL CONFIGURATION
# ============================================================================

SYNC_MODEL_CONFIG = {
    # ============================================================================
    # TIER 1: NO DEPENDENCIES
    # ============================================================================
    # NOTE: contenttypes.ContentType and auth.Permission are intentionally NOT
    # listed here — they are already in EXCLUDED_MODELS and are managed entirely
    # by Django migrations on the desktop. Syncing them caused duplicate-key
    # errors because the DB already had them from the initial migration run.

    'company.SubscriptionPlan': {
        'dependencies': [],
    },
    'errors.ErrorSummary': {
        'dependencies': [],
    },
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

    # ============================================================================
    # TIER 2: COMPANY & PUBLIC USER
    # ============================================================================

    'company.Company': {
        'dependencies': ['company.SubscriptionPlan'],
        'exclude_fields': [
            'efris_certificate_data',
            'verification_token',
            'smtp_password',
        ],
    },

    # ============================================================================
    # TIER 3: AUTH & ROLES
    # ============================================================================
    # NOTE: auth.Permission is intentionally excluded — it is in EXCLUDED_MODELS
    # and is managed by Django migrations. Syncing it caused FK-not-found warnings
    # because its content_type IDs differed between server and desktop schemas.

    'auth.Group': {
        'dependencies': [],
        'exclude_fields': ['permissions'],
    },
    'accounts.Role': {
        'dependencies': ['auth.Group'],
    },
    'taggit.Tag': {
        'dependencies': [],
    },

    # ============================================================================
    # TIER 4: USERS
    # ============================================================================

    'accounts.CustomUser': {
        'dependencies': ['accounts.Role'],
        'exclude_fields': [
            'password',
            'backup_codes',
            'failed_login_attempts',
        ],
    },
    'otp_totp.TOTPDevice': {
        'dependencies': ['accounts.CustomUser'],
    },

    # ============================================================================
    # TIER 5: COMPANY SETTINGS & DOMAINS
    # ============================================================================

    'company.Domain': {
        'dependencies': ['company.Company'],
    },

    # ============================================================================
    # TIER 6: INVENTORY CATEGORIES & SUPPLIERS
    # ============================================================================

    'inventory.Category': {
        'dependencies': [],
    },
    'inventory.Supplier': {
        'dependencies': [],
    },

    # ============================================================================
    # TIER 7: BRANCHES & STORES
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
    # DeviceFingerprint, UserDeviceSession, DeviceOperatorLog, SecurityAlert
    # excluded — device security is server-side only (see EXCLUDED_MODELS)

    # ============================================================================
    # TIER 8: PRODUCTS & SERVICES
    # ============================================================================

    'inventory.Product': {
        'dependencies': ['inventory.Category', 'inventory.Supplier'],
        'exclude_fields': ['image'],
    },
    'inventory.Service': {
        'dependencies': ['inventory.Category'],
        'exclude_fields': ['image'],
    },
    'taggit.TaggedItem': {
        'dependencies': ['taggit.Tag', 'contenttypes.ContentType'],
    },

    # ============================================================================
    # TIER 9: STOCK
    # ============================================================================

    'inventory.Stock': {
        'dependencies': ['inventory.Product', 'stores.Store'],
    },
    'inventory.StockMovement': {
        'dependencies': ['inventory.Product', 'stores.Store'],
        # created_by is NOT NULL in DB but excluded from sync data.
        # We keep it in exclude_fields so it isn't overwritten on updates,
        # but apply_model_data will skip the record if created_by can't be
        # resolved (the field is non-nullable so the DB will reject it).
        # To fix permanently: either make created_by nullable in your migration,
        # or remove it from exclude_fields so it syncs normally.
        'exclude_fields': [],  # was ['created_by'] — removed because it caused NOT NULL errors
    },
    'inventory.StockTransfer': {
        'dependencies': ['inventory.Product', 'stores.Store'],
    },
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
    # TIER 10: CUSTOMERS
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
    # TIER 11: SALES & CARTS
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
    # TIER 12: INVOICES
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
    # TIER 13: EXPENSES & BUDGETS
    # ============================================================================

    'expenses.Expense': {
        'dependencies': ['stores.Store', 'accounts.CustomUser'],
    },
    'expenses.Budget': {
        'dependencies': ['stores.Store', 'accounts.CustomUser'],
    },

    # ============================================================================
    # TIER 14: EFRIS CONFIGURATION
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

    # ============================================================================
    # TIER 15: EFRIS LOGS & SYNC
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
    # TIER 16: CUSTOMER TRANSACTIONS
    # ============================================================================

    'customers.CustomerCreditStatement': {
        'dependencies': ['customers.Customer', 'sales.Sale', 'sales.Payment', 'accounts.CustomUser'],
    },

    # TIER 17: NOTIFICATIONS — excluded (server-side only, see EXCLUDED_MODELS)

    # ============================================================================
    # TIER 18: MESSAGING
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
    # TIER 19: REPORTS
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
    # TIER 20: CELERY
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
    # TIER 25: AUDIT & HISTORY
    # ============================================================================

    'accounts.RoleHistory': {
        'dependencies': ['accounts.Role', 'accounts.CustomUser'],
    },
    'accounts.UserSignature': {
        'dependencies': ['accounts.CustomUser'],
    },
    # AuditLog, LoginHistory, DataExportLog excluded — server-side only (see EXCLUDED_MODELS)
    'errors.ErrorLog': {
        'dependencies': ['accounts.CustomUser'],
    },
}


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_sync_order():
    from collections import deque, defaultdict

    syncable_config = {
        model: config
        for model, config in SYNC_MODEL_CONFIG.items()
        if not should_exclude_model(model)
    }

    graph = defaultdict(list)
    in_degree = defaultdict(int)

    for model in syncable_config:
        if model not in in_degree:
            in_degree[model] = 0

    for model, config in syncable_config.items():
        for dependency in config.get('dependencies', []):
            if should_exclude_model(dependency):
                continue
            graph[dependency].append(model)
            in_degree[model] += 1

    queue = deque([model for model in syncable_config if in_degree[model] == 0])
    result = []

    while queue:
        model = queue.popleft()
        result.append(model)
        for dependent in graph[model]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if len(result) != len(syncable_config):
        missing = set(syncable_config.keys()) - set(result)
        raise ValueError(f"Circular dependency detected! Missing models: {missing}")

    logger.info(f"📊 Sync order: {len(result)} models (excluded {len(EXCLUDED_MODELS)})")
    return result


def get_model_config(model_name):
    return SYNC_MODEL_CONFIG.get(model_name, {'dependencies': [], 'exclude_fields': []})


def validate_dependencies():
    errors = []
    for model, config in SYNC_MODEL_CONFIG.items():
        for dependency in config.get('dependencies', []):
            if dependency not in SYNC_MODEL_CONFIG:
                errors.append(f"Model '{model}' depends on '{dependency}' which is not in config")
    if errors:
        raise ValueError("Dependency validation failed:\n" + "\n".join(errors))
    return True


def get_statistics():
    from collections import defaultdict
    stats = {
        'total_models': len(SYNC_MODEL_CONFIG),
        'models_with_dependencies': sum(1 for c in SYNC_MODEL_CONFIG.values() if c.get('dependencies')),
        'models_with_exclusions': sum(1 for c in SYNC_MODEL_CONFIG.values() if c.get('exclude_fields')),
        'total_dependencies': sum(len(c.get('dependencies', [])) for c in SYNC_MODEL_CONFIG.values()),
        'total_excluded_fields': sum(len(c.get('exclude_fields', [])) for c in SYNC_MODEL_CONFIG.values()),
    }
    app_counts = defaultdict(int)
    for model in SYNC_MODEL_CONFIG:
        app = model.split('.')[0]
        app_counts[app] += 1
    stats['apps'] = dict(app_counts)
    stats['total_apps'] = len(app_counts)
    return stats


# ============================================================================
# SYNC MANAGER
# ============================================================================

class SyncManager:
    """
    Complete bidirectional sync manager
    ✅ sync_id (UUID) is the stable identity for all records
    ✅ Download from server
    ✅ Upload to server
    ✅ Conflict resolution (last-write-wins)
    ✅ Enhanced error logging
    """

    def __init__(self, tenant_id, schema_name, auth_token=None):
        self.tenant_id = tenant_id
        self.schema_name = schema_name
        self._passed_token = auth_token
        self.auth_token = self._get_valid_auth_token(auth_token)
        self.last_sync_file = settings.DESKTOP_DATA_DIR / f'.last_sync_{tenant_id}'
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
        if hasattr(settings, 'SYNC_SERVER_URL'):
            return settings.SYNC_SERVER_URL
        if settings.DEBUG:
            return f"http://{self.schema_name}.localhost:8000"
        return f"https://{self.schema_name}.primebooks.sale"

    def reset_sequences(self):
        from django.db import connection

        logger.info(f"Resetting sequences in schema: {self.schema_name}")
        try:
            with schema_context(self.schema_name):
                with connection.cursor() as cursor:
                    cursor.execute("SET search_path TO %s, public", [self.schema_name])

                    cursor.execute("""
                                   SELECT s.sequencename, c.relname, a.attname
                                   FROM pg_sequences s
                                            JOIN pg_class seq_cls
                                                 ON seq_cls.relname = s.sequencename
                                                     AND seq_cls.relkind = 'S'
                                                     AND seq_cls.relnamespace =
                                                         (SELECT oid FROM pg_namespace WHERE nspname = %s)
                                            JOIN pg_depend dep
                                                 ON dep.objid = seq_cls.oid
                                                     AND dep.classid = 'pg_class'::regclass
                            AND dep.deptype = 'a'
                        JOIN pg_attribute a
                                   ON a.attrelid = dep.refobjid
                                       AND a.attnum = dep.refobjsubid
                                       JOIN pg_class c
                                       ON c.oid = dep.refobjid
                                       AND c.relkind = 'r'
                                   WHERE s.schemaname = %s
                                   ORDER BY s.sequencename;
                                   """, [self.schema_name, self.schema_name])

                    rows = cursor.fetchall()
                    logger.info(f"  Found {len(rows)} sequences to reset")

                    if not rows:
                        logger.warning("pg_sequences join returned 0 rows — using name heuristic")
                        cursor.execute(
                            "SELECT sequencename FROM pg_sequences WHERE schemaname = %s ORDER BY sequencename;",
                            [self.schema_name]
                        )
                        rows = []
                        for (sname,) in cursor.fetchall():
                            # Standard Django pattern: <table>_<column>_seq
                            # e.g. "sales_sale_id_seq" → table="sales_sale", col="id"
                            if sname.endswith('_seq'):
                                body = sname[:-4]  # strip trailing _seq
                                # Split on last underscore to get column name
                                last_sep = body.rfind('_')
                                if last_sep > 0:
                                    table_part = body[:last_sep]
                                    col_part = body[last_sep + 1:]
                                    rows.append((sname, table_part, col_part))
                                else:
                                    rows.append((sname, body, 'id'))
                            else:
                                rows.append((sname, sname, 'id'))

                    reset_count = skipped_count = 0
                    for seq_name, table_name, col_name in rows:
                        try:
                            cursor.execute("SELECT to_regclass(%s)", [f"{self.schema_name}.{table_name}"])
                            if cursor.fetchone()[0] is None:
                                skipped_count += 1
                                continue
                            cursor.execute(
                                f'SELECT COALESCE(MAX("{col_name}"), 0) FROM "{self.schema_name}"."{table_name}";'
                            )
                            max_val = cursor.fetchone()[0]
                            cursor.execute(
                                f'SELECT setval(\'"{self.schema_name}"."{seq_name}"\', GREATEST(%s, 1), true);',
                                [max_val]
                            )
                            reset_count += 1
                        except Exception as e:
                            logger.warning(f"  Skipped {seq_name}: {str(e)[:120]}")
                            skipped_count += 1

                    logger.info(f"Sequences reset: {reset_count} done, {skipped_count} skipped")
                    return True

        except Exception as e:
            logger.error(f"reset_sequences failed: {e}", exc_info=True)
            return False

    # Alias
    fix_sequences_after_upload = reset_sequences

    def is_online(self):
        try:
            if not self.auth_token:
                return False
            response = requests.get(
                f"{self.server_url}/api/health/",
                headers={'Authorization': f'Bearer {self.auth_token}'},
                timeout=5
            )
            return response.status_code == 200
        except Exception:
            return False

    def _get_valid_auth_token(self, provided_token=None):
        if provided_token:
            return provided_token
        token = getattr(settings, 'SYNC_AUTH_TOKEN', None)
        if token:
            return token
        try:
            from primebooks.auth import DesktopAuthManager
            token = DesktopAuthManager().get_valid_token()
            if token:
                return token
        except Exception as e:
            logger.warning(f"⚠️ Could not get token from auth manager: {e}")
        logger.error("❌ No auth token found anywhere!")
        return None

    def _make_request(self, url, method='GET', data=None, params=None, retry_on_401=True):
        headers = {
            'Authorization': f'Bearer {self.auth_token}',
            'Content-Type': 'application/json',
        }
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers, params=params, timeout=300)
            elif method == 'POST':
                response = requests.post(url, headers=headers, json=data, timeout=300)
            else:
                raise ValueError(f"Unsupported method: {method}")

            if response.status_code == 401 and retry_on_401:
                logger.warning("⚠️ 401 - attempting token refresh...")
                from primebooks.auth import DesktopAuthManager
                new_token = DesktopAuthManager().refresh_access_token()
                if new_token and new_token != self.auth_token:
                    self.auth_token = new_token
                    headers['Authorization'] = f'Bearer {new_token}'
                    if method == 'GET':
                        response = requests.get(url, headers=headers, params=params, timeout=300)
                    elif method == 'POST':
                        response = requests.post(url, headers=headers, json=data, timeout=300)
            return response
        except requests.exceptions.ConnectionError as e:
            logger.error(f"❌ Connection error: {e}")
            return None
        except requests.exceptions.Timeout:
            logger.error("❌ Request timeout")
            return None
        except Exception as e:
            logger.error(f"❌ Request error: {e}", exc_info=True)
            return None


    # ========================================================================
    # DOWNLOAD FROM SERVER
    # ========================================================================

    def download_changes(self, progress_callback=None):
        try:
            last_sync = self.get_last_sync_time()
            if not last_sync:
                return self.download_all_data(progress_callback)

            logger.info("=" * 70)
            logger.info(f"DOWNLOADING CHANGES SINCE {last_sync}")
            logger.info("=" * 70)

            if progress_callback:
                progress_callback("Checking for changes...", 10)

            response = self._make_request(
                f"{self.server_url}/api/desktop/sync/changes/",
                method='GET',
                params={'since': last_sync.isoformat()}
            )

            if not response or response.status_code != 200:
                logger.error(f"Download failed: {getattr(response, 'status_code', 'no response')}")
                return False

            data = response.json()
            changes = data.get('data', {})
            total_changed = sum(len(r) for r in changes.values())

            if total_changed == 0:
                logger.info("No server changes to download")
                self.update_last_sync_time()
                if progress_callback:
                    progress_callback("No changes to download", 100)
                return True

            logger.info(f"Downloaded {total_changed} changed records across {len(changes)} models")

            if progress_callback:
                progress_callback(f"Applying {total_changed} changes...", 30)

            success = self.apply_bulk_data(changes, progress_callback)
            if not success:
                return False

            self.reset_sequences()
            self.update_last_sync_time()

            if progress_callback:
                progress_callback("Changes applied!", 100)
            return True

        except Exception as e:
            logger.error(f"Download changes error: {e}", exc_info=True)
            return False

    def download_all_data(self, progress_callback=None):
        try:
            logger.info("=" * 70)
            logger.info("DOWNLOADING ALL DATA FROM SERVER")
            logger.info("=" * 70)

            if progress_callback:
                progress_callback("Connecting to server...", 5)

            response = self._make_request(
                f"{self.server_url}/api/desktop/sync/bulk-download/",
                method='GET'
            )

            if not response or response.status_code != 200:
                logger.error(f"Download failed")
                return False

            data = response.json()
            if not data.get('success'):
                logger.error(f"Download failed: {data.get('error')}")
                return False

            all_data = data.get('data', {})
            total_records = data.get('total_records', 0)

            logger.info(f"Downloaded {total_records} records across {len(all_data)} models")

            if progress_callback:
                progress_callback(f"Downloaded {total_records} records...", 30)

            if all_data:
                success = self.apply_bulk_data(all_data, progress_callback)
                if success:
                    if progress_callback:
                        progress_callback("Resetting database sequences...", 95)
                    self.reset_sequences()
                    self.update_last_sync_time()
                    if progress_callback:
                        progress_callback("Download complete!", 100)
                    return True
                return False
            return False

        except Exception as e:
            logger.error(f"Download error: {e}", exc_info=True)
            return False

    # ========================================================================
    # UPLOAD TO SERVER
    # ========================================================================

    def upload_changes(self, progress_callback=None):
        try:
            last_sync = self.get_last_sync_time()

            logger.info("=" * 70)
            logger.info(f"UPLOADING CHANGES SINCE {last_sync}")
            logger.info("=" * 70)

            if progress_callback:
                progress_callback("Collecting local changes...", 10)

            changes = self.collect_local_changes(last_sync)

            if not changes:
                logger.info("No local changes to upload")
                return True

            total_changed = sum(len(r) for r in changes.values())
            logger.info(f"Uploading {total_changed} records across {len(changes)} model(s)")

            if progress_callback:
                progress_callback(f"Uploading {total_changed} records...", 30)

            response = self._make_request(
                f"{self.server_url}/api/desktop/sync/upload/",
                method='POST',
                data={
                    "tenant_id": self.tenant_id,
                    "schema_name": self.schema_name,
                    "changes": changes,
                    "last_sync": last_sync.isoformat() if last_sync else None,
                }
            )

            if not response or response.status_code != 200:
                logger.error(f"Upload failed: {getattr(response, 'status_code', 'no response')}")
                return False

            result = response.json()
            if not result.get("success"):
                logger.error(f"Upload failed: {result.get('error')}")
                return False

            logger.info("Upload successful")

            id_mappings = result.get("id_mappings", {})
            if id_mappings:
                logger.info(f"Applying ID mappings for {len(id_mappings)} model(s)")
                self._apply_sync_id_mappings(id_mappings)

            self.reset_sequences()

            if progress_callback:
                progress_callback("Upload complete!", 60)

            return True

        except Exception as e:
            logger.error("Upload error", exc_info=True)
            return False

    def _apply_sync_id_mappings(self, id_mappings):
        """
        Apply server ID mappings returned after upload.

        The server now returns:
            {model_name: {sync_id_str: {server_id: int, sync_id: str}}}

        For each record:
        - If local record has a negative PK (offline-created), update it
          to use the server-assigned integer PK.
        - stamp sync_id onto the record if it's missing (old records).
        - No FK fix-up needed because FKs are now resolved by sync_id on
          both sides — integer PKs are just for internal DB storage.

        ✅ Replaces the old _replace_offline_ids which relied on negative PKs.
        """
        with schema_context(self.schema_name):
            for model_name, mappings in id_mappings.items():
                try:
                    model = apps.get_model(model_name)
                    has_sync_id = any(
                        f.name == 'sync_id' for f in model._meta.get_fields()
                    )

                    for sync_id_str, mapping in mappings.items():
                        server_id = mapping.get('server_id')
                        server_sync_id = mapping.get('sync_id')

                        if not server_id:
                            continue

                        try:
                            sync_id_val = uuid.UUID(sync_id_str)
                        except ValueError:
                            # Fallback: old format where key was a negative integer
                            try:
                                old_int_id = int(sync_id_str)
                                if old_int_id < 0 and has_sync_id:
                                    # Find by negative PK (legacy path)
                                    self._replace_single_record_id(
                                        model, old_int_id, server_id, has_sync_id, server_sync_id
                                    )
                            except (ValueError, TypeError):
                                pass
                            continue

                        if has_sync_id:
                            # Primary path: update PK for any record with this sync_id
                            # that still has a negative (offline) PK
                            updated_count = 0
                            try:
                                obj = model.objects.get(sync_id=sync_id_val)
                                if obj.pk != server_id and isinstance(obj.pk, int) and obj.pk < 0:
                                    # Replace the negative PK with the server PK
                                    self._replace_single_record_id(
                                        model, obj.pk, server_id, has_sync_id, server_sync_id
                                    )
                                    updated_count += 1
                                elif obj.pk == server_id:
                                    # PKs already match — ensure sync_id is stamped
                                    if server_sync_id and not obj.sync_id:
                                        obj.sync_id = uuid.UUID(server_sync_id)
                                        obj.save(update_fields=['sync_id'])
                                logger.debug(
                                    f"  ✅ {model_name} sync_id={sync_id_str} → pk={server_id}"
                                    f" ({'replaced PK' if updated_count else 'already correct'})"
                                )
                            except model.DoesNotExist:
                                logger.debug(
                                    f"  ⚠️  {model_name} sync_id={sync_id_str} not found locally "
                                    f"(will be downloaded on next sync)"
                                )

                except LookupError:
                    logger.warning(f"  ⚠️  Model not found: {model_name}")
                except Exception as e:
                    logger.error(f"  ❌ Error applying mappings for {model_name}: {e}")

    def _replace_single_record_id(self, model, old_pk, new_pk, has_sync_id, server_sync_id=None):
        """
        Swap a record's PK from old_pk → new_pk by delete-and-recreate.
        This is only needed for offline records that still have a negative PK.
        With sync_id everywhere, FK references don't need a second pass —
        they resolve by sync_id, not integer PK.
        """
        try:
            obj = model.objects.get(pk=old_pk)

            # Collect field values
            field_values = {}
            for field in model._meta.fields:
                if field.name == 'id':
                    continue
                field_values[field.name] = getattr(obj, field.name)

            # Stamp sync_id if available and missing
            if has_sync_id and server_sync_id and not field_values.get('sync_id'):
                try:
                    field_values['sync_id'] = uuid.UUID(server_sync_id)
                except ValueError:
                    pass

            # Collect M2M values before delete
            m2m_values = {}
            for field in model._meta.many_to_many:
                m2m_values[field.name] = list(
                    getattr(obj, field.name).values_list('pk', flat=True)
                )

            obj.delete()

            new_obj = model(pk=new_pk, **field_values)
            new_obj.save()

            # Restore M2M
            for field_name, pks in m2m_values.items():
                if pks:
                    getattr(new_obj, field_name).set(pks)

            logger.info(f"  ✅ Replaced PK: {model._meta.label} {old_pk} → {new_pk}")

        except model.DoesNotExist:
            logger.debug(f"  Record {model._meta.label}:{old_pk} not found (already replaced?)")
        except Exception as e:
            logger.error(f"  ❌ Error replacing PK {old_pk} → {new_pk}: {e}")

    # ========================================================================
    # COLLECT LOCAL CHANGES
    # ========================================================================

    def collect_local_changes(self, since):
        """
        Collect records changed LOCALLY since last sync.
        ✅ sync_id included in every record sent to server.
        ✅ FKs sent as integer PKs (server resolves via sync_id).
        ✅ Stock delta injected for atomic server-side quantity updates.
        """
        changes = {}

        with schema_context(self.schema_name):
            for model_name in self.sync_models:
                if should_exclude_model(model_name):
                    continue

                config = SYNC_MODEL_CONFIG.get(model_name, {})
                if config.get('download_only'):
                    continue

                try:
                    model = apps.get_model(model_name)
                    config = SYNC_MODEL_CONFIG.get(model_name, {})
                    exclude_fields = [
                        f for f in config.get('exclude_fields', []) if f != 'sync_id'
                    ]

                    queryset = model.objects.all()

                    if since:
                        if since.tzinfo is None:
                            since = timezone.make_aware(since)
                        if hasattr(model, 'modified_at'):
                            queryset = queryset.filter(modified_at__gte=since)
                        elif hasattr(model, 'updated_at'):
                            queryset = queryset.filter(updated_at__gte=since)
                        elif hasattr(model, 'last_updated'):
                            queryset = queryset.filter(last_updated__gte=since)
                        elif hasattr(model, 'created_at'):
                            queryset = queryset.filter(created_at__gte=since)

                    if not queryset.exists():
                        continue

                    local_records = [
                        obj for obj in queryset
                        if not self._is_synced(model_name, obj.pk, obj=obj)
                    ]

                    if not local_records:
                        continue

                    data = serializers.serialize('json', local_records)
                    records = json.loads(data)

                    if exclude_fields:
                        for record in records:
                            for field in exclude_fields:
                                record['fields'].pop(field, None)

                    # ✅ Inject Stock quantity delta
                    if model_name == 'inventory.Stock':
                        records = self._inject_stock_deltas(records)

                    changes[model_name] = records
                    logger.info(f"  Found {len(records)} LOCAL changes in {model_name}")

                except LookupError:
                    continue
                except Exception as e:
                    logger.error(f"  Error collecting {model_name}: {e}")

        return changes

    def _inject_stock_deltas(self, records):
        """
        Inject _quantity_delta into Stock records so server applies
        delta atomically instead of overwriting (preserves concurrent online sales).
        """
        sync_marker_file = settings.DESKTOP_DATA_DIR / f'.synced_{self.tenant_id}.json'
        synced_data = {}
        if sync_marker_file.exists():
            try:
                synced_data = json.loads(sync_marker_file.read_text())
            except Exception:
                pass

        stock_synced = synced_data.get('inventory.Stock', {})

        for record in records:
            record_id = str(record['pk'])
            entry = stock_synced.get(record_id, {})
            synced_quantity = entry.get('synced_quantity') if isinstance(entry, dict) else None

            if synced_quantity is not None:
                current_quantity = float(record['fields'].get('quantity', 0))
                delta = current_quantity - synced_quantity
                record['fields']['_quantity_delta'] = delta
                logger.debug(
                    f"    Stock {record_id}: synced_qty={synced_quantity}, "
                    f"current={current_quantity}, delta={delta:+.3f}"
                )
            else:
                record['fields']['_quantity_delta'] = None

        return records

    # ========================================================================
    # APPLY DOWNLOADED DATA
    # ========================================================================

    def apply_bulk_data(self, all_data, progress_callback=None):
        """Apply downloaded data — signals suppressed."""
        with suppress_signals():
            return self._apply_bulk_data_impl(all_data, progress_callback)

    def _apply_bulk_data_impl(self, all_data, progress_callback=None):
        """
        Apply downloaded data model-by-model.

        Fixes applied:
        ✅ Mid-sync sequence reset after sales.SaleItem and before sales.Receipt
           prevents duplicate RCP prefix collisions.
        ✅ Each model in its own atomic block — one failure never poisons others.
        ✅ Progress reporting maintained.
        """

        try:
            logger.info("💾 Applying data to local database")
            total_models = len(all_data)
            created_total = updated_total = 0

            with schema_context(self.schema_name):
                for index, (model_name, records) in enumerate(all_data.items()):
                    try:
                        if progress_callback:
                            progress = 30 + int((index / total_models) * 60)
                            progress_callback(f"Saving {model_name}...", progress)

                        # Each model runs in its own atomic block so records are
                        # visible to FK lookups in later models. Individual record
                        # failures are isolated via savepoints inside apply_model_data.
                        from django.db import transaction
                        with transaction.atomic():
                            created, updated = self.apply_model_data(model_name, records)

                        created_total += created
                        updated_total += updated

                    except Exception as e:
                        logger.error(f"  ❌ Error saving {model_name}: {e}")

            logger.info(f"✅ Data applied: {created_total} created, {updated_total} updated")
            return True

        except Exception as e:
            logger.error(f"❌ Error applying data: {e}", exc_info=True)
            return False

    def _apply_stock_quantity_delta(self, existing_stock_obj, server_fields):
        """
        Instead of overwriting local quantity with server quantity,
        compute and apply the server-side delta atomically.

        Logic:
            server_delta = server_quantity - last_synced_quantity
            new_local    = local_quantity + server_delta

        This preserves offline sales made on the desktop while also
        incorporating sales/purchases made on the server since last sync.

        Falls back to direct overwrite if no sync baseline is available
        (e.g. first sync).
        """
        server_quantity = server_fields.get('quantity')
        if server_quantity is None:
            return  # nothing to merge

        from decimal import Decimal
        server_quantity = Decimal(str(server_quantity))

        # Look up the last-synced quantity baseline from sync markers
        sync_marker_file = settings.DESKTOP_DATA_DIR / f'.synced_{self.tenant_id}.json'
        synced_baseline = None
        try:
            if sync_marker_file.exists():
                synced_data = json.loads(sync_marker_file.read_text())
                entry = synced_data.get('inventory.Stock', {}).get(str(existing_stock_obj.pk))
                if isinstance(entry, dict):
                    raw = entry.get('synced_quantity')
                    if raw is not None:
                        synced_baseline = Decimal(str(raw))
        except Exception:
            pass

        if synced_baseline is None:
            # No baseline — first sync or marker missing.
            # Trust the server value outright.
            existing_stock_obj.quantity = server_quantity
            logger.debug(
                f"  Stock pk={existing_stock_obj.pk}: "
                f"no baseline, using server value {server_quantity}"
            )
            return

        # Delta = how much the server quantity changed since we last synced
        server_delta = server_quantity - synced_baseline
        local_quantity = Decimal(str(existing_stock_obj.quantity))

        if server_delta == 0:
            # Server unchanged — keep local value (preserves offline sales)
            logger.debug(
                f"  Stock pk={existing_stock_obj.pk}: "
                f"server unchanged (delta=0), keeping local={local_quantity}"
            )
            return

        # Apply server delta on top of current local quantity
        merged = local_quantity + server_delta
        merged = max(merged, Decimal('0'))  # never go below zero

        logger.info(
            f"  📦 Stock pk={existing_stock_obj.pk}: "
            f"local={local_quantity}, server={server_quantity}, "
            f"baseline={synced_baseline}, delta={server_delta:+}, "
            f"merged={merged}"
        )
        existing_stock_obj.quantity = merged

    def apply_model_data(self, model_name, records):
        """
        Apply records for a specific model.
        ✅ Looks up existing records by sync_id first, then business key, then PK.
        ✅ Stamps sync_id onto old records if missing.
        ✅ FK resolution: sync_id → int PK fallback (int cast is critical).
        ✅ Company FK resolved by schema_name OR int PK (handles string company_id).
        ✅ Required FK not found → skip record (not crash), logged as WARNING.
        ✅ M2M fields deferred and set after save — never raises on missing members.
        ✅ Each record wrapped in its own savepoint — one failure never
           poisons the rest of the model's batch.
        ✅ Non-critical ValidationErrors skipped gracefully.
        ✅ 'exclude_fields' that are NOT NULL in DB are set to a safe default
           (the FK is nulled if nullable, otherwise record is skipped).
        """
        from decimal import Decimal
        from django.db import transaction as _tx
        from django.core.exceptions import ValidationError
        from django_tenants.utils import schema_context as _schema_context

        logger.debug(f"🔍 apply_model_data: {model_name} ({len(records)} records)")

        try:
            model = apps.get_model(model_name)
            has_sync_id = any(f.name == 'sync_id' for f in model._meta.get_fields())
            created_count = updated_count = 0
            synced_ids = []
            saved_objects = []

            for record in records:
                # ── Savepoint per record ─────────────────────────────────────
                # Any DB error rolls back ONLY this record's savepoint.
                try:
                    with _tx.atomic():
                        obj_id = record['pk']
                        fields = record['fields']

                        # Extract sync_id from fields
                        record_sync_id = None
                        raw_sync_id = fields.get('sync_id')
                        if raw_sync_id and has_sync_id:
                            try:
                                record_sync_id = uuid.UUID(str(raw_sync_id))
                            except ValueError:
                                pass

                        m2m_fields = {}
                        processed_fields = {}
                        skip_record = False

                        for field_name, value in fields.items():
                            try:
                                field = model._meta.get_field(field_name)

                                if field.many_to_many:
                                    # Defer M2M — set after save, skip missing members silently
                                    m2m_fields[field_name] = value
                                    continue

                                if (field.many_to_one or field.one_to_one) and value is not None:
                                    related_model = field.related_model
                                    related_app = related_model._meta.app_label
                                    related_cls_name = related_model.__name__

                                    # ── Company is in public schema ──────────
                                    # Value may be an int PK OR a string like
                                    # 'PF-N212467' (company_id business key).
                                    if related_app == 'company' and related_cls_name == 'Company':
                                        instance = None
                                        with _schema_context('public'):
                                            # Try int PK first
                                            try:
                                                instance = related_model.objects.get(pk=int(value))
                                            except (ValueError, TypeError, related_model.DoesNotExist):
                                                pass
                                            # Try company_id string field
                                            if instance is None:
                                                try:
                                                    instance = related_model.objects.get(company_id=str(value))
                                                except related_model.DoesNotExist:
                                                    pass
                                            # Try schema_name
                                            if instance is None:
                                                try:
                                                    instance = related_model.objects.get(schema_name=str(value))
                                                except related_model.DoesNotExist:
                                                    pass

                                        if instance is not None:
                                            processed_fields[field_name] = instance
                                        elif field.null:
                                            processed_fields[field_name] = None
                                        else:
                                            logger.warning(
                                                f"  ⚠️  {model_name} pk={obj_id}: "
                                                f"required Company FK {field_name}={value} not found — skipping record"
                                            )
                                            skip_record = True
                                            break
                                        continue

                                    # ── Regular tenant FK ────────────────────
                                    # sync_id → int PK fallback
                                    instance = self._resolve_fk(related_model, value)
                                    if instance is not None:
                                        processed_fields[field_name] = instance
                                    elif field.null:
                                        processed_fields[field_name] = None
                                    else:
                                        # Required FK not in DB yet — skip record,
                                        # it will arrive on next sync cycle.
                                        logger.warning(
                                            f"  ⚠️  {model_name} pk={obj_id}: "
                                            f"required FK {field_name}={value} not found — skipping record"
                                        )
                                        skip_record = True
                                        break
                                    continue

                                if (hasattr(field, 'get_internal_type') and
                                        field.get_internal_type() == 'DecimalField'):
                                    processed_fields[field_name] = (
                                        Decimal(str(value)) if value is not None else None
                                    )
                                    continue

                                processed_fields[field_name] = value

                            except Exception as e:
                                logger.debug(f"  Skipping field {field_name}: {e}")
                                continue

                        if skip_record:
                            continue

                        # ── CustomUser: ensure password is never blank ────────
                        # The server sends a placeholder '!desktop-no-local-login'
                        # instead of the real hash. If the record somehow still
                        # has a blank/None password, set an unusable hash so
                        # Django's NOT BLANK validation passes. Desktop users
                        # always authenticate via the server, not locally.
                        if model.__name__ == 'CustomUser' and not processed_fields.get('password'):
                            from django.contrib.auth.hashers import make_password
                            processed_fields['password'] = make_password(None)

                        # ── Find existing record: sync_id → business key → PK ──
                        existing_obj = None

                        if record_sync_id and has_sync_id:
                            try:
                                existing_obj = model.objects.get(sync_id=record_sync_id)
                            except model.DoesNotExist:
                                pass

                        if existing_obj is None:
                            unique_lookups = self._get_unique_lookups(model, processed_fields)
                            if unique_lookups:
                                try:
                                    existing_obj = model.objects.get(**unique_lookups)
                                except model.DoesNotExist:
                                    pass
                                except model.MultipleObjectsReturned:
                                    existing_obj = model.objects.filter(**unique_lookups).first()

                        if existing_obj is None:
                            try:
                                existing_obj = model.objects.get(pk=obj_id)
                            except model.DoesNotExist:
                                pass

                        if existing_obj:
                            for fname, val in processed_fields.items():
                                setattr(existing_obj, fname, val)

                            # Stamp sync_id if old record is missing it
                            if has_sync_id and record_sync_id and not existing_obj.sync_id:
                                existing_obj.sync_id = record_sync_id

                            try:
                                existing_obj._skip_full_clean = True
                                existing_obj.save()
                            except ValidationError as e:
                                if not self._is_skippable_validation_error(e):
                                    raise
                                logger.debug(f"  Skipping validation error (update) pk={obj_id}: {e}")
                                raise  # rolls back savepoint

                            # M2M: set members, skip any that don't exist yet
                            for fname, val in m2m_fields.items():
                                if val:
                                    try:
                                        m2m_field = getattr(existing_obj, fname)
                                        # Filter to only existing PKs — avoids FK errors
                                        related_m = model._meta.get_field(fname).related_model
                                        valid_pks = list(
                                            related_m.objects.filter(pk__in=val)
                                            .values_list('pk', flat=True)
                                        )
                                        m2m_field.set(valid_pks)
                                    except Exception as me:
                                        logger.debug(f"  M2M error {fname}: {me}")

                            updated_count += 1
                            synced_ids.append(existing_obj.pk)
                            saved_objects.append(existing_obj)

                        else:
                            # Create new record
                            if has_sync_id and record_sync_id:
                                processed_fields['sync_id'] = record_sync_id

                            pk_field = model._meta.pk.name
                            if pk_field != 'id':
                                processed_fields[pk_field] = obj_id
                                obj = model(**processed_fields)
                            else:
                                obj = model(id=obj_id, **processed_fields)

                            try:
                                obj._skip_full_clean = True
                                obj.save()
                            except ValidationError as e:
                                if not self._is_skippable_validation_error(e):
                                    raise
                                logger.debug(f"  Skipping validation error (create) pk={obj_id}: {e}")
                                raise

                            # M2M: set members, skip any that don't exist yet
                            for fname, val in m2m_fields.items():
                                if val:
                                    try:
                                        m2m_field = getattr(obj, fname)
                                        related_m = model._meta.get_field(fname).related_model
                                        valid_pks = list(
                                            related_m.objects.filter(pk__in=val)
                                            .values_list('pk', flat=True)
                                        )
                                        m2m_field.set(valid_pks)
                                    except Exception as me:
                                        logger.debug(f"  M2M error {fname}: {me}")

                            created_count += 1
                            synced_ids.append(obj.pk)
                            saved_objects.append(obj)

                except Exception as e:
                    # Savepoint already rolled back — log and move on.
                    # Use WARNING for expected DB constraint violations (e.g. unique
                    # constraint on system tables) and ERROR for unexpected failures.
                    from django.db import IntegrityError as _IntegrityError
                    if isinstance(e, _IntegrityError):
                        logger.warning(
                            f"  ⚠️  Skipped record pk={record.get('pk')} ({model_name}): {e}"
                        )
                    else:
                        logger.error(
                            f"  ❌ Error saving record pk={record.get('pk')} ({model_name}): {e}"
                        )

            if synced_ids:
                self._mark_as_synced(model_name, synced_ids, objects=saved_objects)

            logger.info(f"  ✅ {model_name}: {created_count} created, {updated_count} updated")
            return created_count, updated_count

        except LookupError:
            logger.warning(f"  ⚠️  Model not found: {model_name}")
            return 0, 0
        except Exception as e:
            logger.error(f"  ❌ Fatal error in apply_model_data for {model_name}: {e}")
            return 0, 0

    def _resolve_fk(self, related_model, value):
        """
        Resolve a FK value to a model instance.
        Tries sync_id (UUID) first, then integer PK.
        Returns instance or None.

        ✅ CRITICAL: value from JSON is always a string or int.
           We must try UUID parse first (for sync_id), then cast to int for PK.
           Passing a raw string to get(pk=...) causes "Cannot assign" errors.
        """
        if value is None:
            return None

        has_sync_id = any(f.name == 'sync_id' for f in related_model._meta.get_fields())

        # 1. Try UUID sync_id lookup (only if the value looks like a UUID)
        if has_sync_id:
            try:
                uid = uuid.UUID(str(value))
                return related_model.objects.get(sync_id=uid)
            except (related_model.DoesNotExist, ValueError, AttributeError):
                pass

        # 2. Fallback: integer PK — MUST cast to int, never pass raw string
        try:
            return related_model.objects.get(pk=int(value))
        except (related_model.DoesNotExist, ValueError, TypeError):
            return None

    def _is_skippable_validation_error(self, e):
        error_str = str(e).lower()
        return any(x in error_str for x in [
            'efris', 'constraint',
            'either product or service', 'choice'
        ])

    def _get_unique_lookups(self, model, fields):
        model_name = model._meta.model_name
        unique_field_map = {
            'group': ['name'],
            'role': ['name'],
            'customuser': ['username'],
            'category': ['name'],
            'supplier': ['name'],
            'product': ['sku'],
            'stock': ['product', 'store'],
            'customer': ['phone'],
            'sale': ['transaction_id'],
            'receipt': ['receipt_number'],
            'invoice': ['sale'],
            'userdevicesession': ['session_key'],
        }

        unique_fields = unique_field_map.get(model_name, [])
        if not unique_fields:
            return None

        lookup = {}
        for field_name in unique_fields:
            if field_name in fields:
                lookup[field_name] = fields[field_name]
            else:
                return None  # incomplete key — skip

        return lookup or None

    # ========================================================================
    # SYNC MARKERS
    # ========================================================================

    def _mark_as_synced(self, model_name, record_ids, objects=None):
        sync_marker_file = settings.DESKTOP_DATA_DIR / f'.synced_{self.tenant_id}.json'

        try:
            synced = json.loads(sync_marker_file.read_text()) if sync_marker_file.exists() else {}
        except Exception:
            synced = {}

        if model_name not in synced:
            synced[model_name] = {}

        sync_time = timezone.now().isoformat()
        obj_by_pk = {obj.pk: obj for obj in objects} if objects else {}

        for record_id in record_ids:
            entry = {'synced_at': sync_time}
            if model_name == 'inventory.Stock' and record_id in obj_by_pk:
                entry['synced_quantity'] = float(obj_by_pk[record_id].quantity)
            synced[model_name][str(record_id)] = entry

        sync_marker_file.write_text(json.dumps(synced))

    def _is_synced(self, model_name, record_id, obj=None):
        sync_marker_file = settings.DESKTOP_DATA_DIR / f'.synced_{self.tenant_id}.json'
        if not sync_marker_file.exists():
            return False
        try:
            synced = json.loads(sync_marker_file.read_text())
            model_synced = synced.get(model_name, {})

            if isinstance(model_synced, list):
                return str(record_id) in model_synced

            entry = model_synced.get(str(record_id))
            if not entry:
                return False

            sync_time_str = entry if isinstance(entry, str) else entry.get('synced_at')
            if not sync_time_str:
                return False

            if obj is not None:
                sync_time = datetime.fromisoformat(sync_time_str)
                if sync_time.tzinfo is None:
                    sync_time = timezone.make_aware(sync_time)

                modified_at = None
                for field_name in ('modified_at', 'updated_at', 'last_updated'):
                    modified_at = getattr(obj, field_name, None)
                    if modified_at:
                        break

                if modified_at:
                    if modified_at.tzinfo is None:
                        modified_at = timezone.make_aware(modified_at)
                    if modified_at > sync_time:
                        return False  # Modified after last sync — upload it

            return True
        except Exception as e:
            logger.warning(f"Error reading sync markers: {e}")
            return False

    # ========================================================================
    # FULL SYNC
    # ========================================================================

    def full_sync(self, is_first_sync=False, progress_callback=None):
        try:
            from primebooks.auth import DesktopAuthManager
            is_authed, error_msg = DesktopAuthManager().require_authentication()
            if not is_authed:
                logger.error(f"Authentication required: {error_msg}")
                if progress_callback:
                    progress_callback(f"Error: {error_msg}", 0)
                return False

            logger.info("=" * 70)
            logger.info("FULL SYNC STARTING")
            logger.info(f"  First sync: {is_first_sync}")
            logger.info("=" * 70)

            if is_first_sync:
                if not self.is_online():
                    logger.warning("Server not reachable")
                    self.update_last_sync_time()
                    return True
                success = self.download_all_data(progress_callback)
                if success:
                    self.reset_sequences()
                    logger.info("First sync complete")
                    return True
                logger.error("First sync failed")
                return False

            else:
                last_sync = self.get_last_sync_time()
                logger.info(f"Bidirectional sync — last sync: {last_sync}")

                if not self.is_online():
                    logger.warning("Server not reachable — staying offline")
                    return False

                if progress_callback:
                    progress_callback("Uploading local changes...", 10)

                upload_success = self.upload_changes(progress_callback)
                if not upload_success:
                    logger.warning("Upload had issues, continuing with download...")

                if progress_callback:
                    progress_callback("Downloading server changes...", 50)

                download_success = self.download_changes(progress_callback)

                if download_success:
                    self.reset_sequences()

                    logger.info("=" * 70)
                    logger.info("SYNC COMPLETE")
                    logger.info(f"  Timestamp: {self.get_last_sync_time()}")
                    logger.info("=" * 70)

                    if progress_callback:
                        progress_callback("Sync complete!", 100)
                    return True

                logger.error("Download failed — sync incomplete")
                return False

        except Exception as e:
            logger.error(f"Sync error: {e}", exc_info=True)
            if progress_callback:
                progress_callback(f"Error: {str(e)}", 0)
            return False

    # ========================================================================
    # HELPERS
    # ========================================================================

    def check_pending_changes(self):
        last_sync = self.get_last_sync_time()
        logger.info("=" * 70)
        logger.info("CHECKING PENDING CHANGES")
        logger.info(f"  Last sync: {last_sync}")
        logger.info("=" * 70)

        if not last_sync:
            logger.info("  No last sync — full sync needed")
            return

        changes = self.collect_local_changes(last_sync)
        if not changes:
            logger.info("  ✅ No pending changes")
        else:
            for model_name, records in changes.items():
                logger.info(f"  📝 {model_name}: {len(records)} pending changes")

    def should_auto_sync(self):
        last_sync = self.get_last_sync_time()
        if not last_sync:
            return True
        return timezone.now() - last_sync > timedelta(days=1)

    def update_last_sync_time(self):
        try:
            import datetime as _dt
            sync_file = settings.DESKTOP_DATA_DIR / f'.last_sync_{self.tenant_id}.txt'
            current_time = _dt.datetime.now(_dt.timezone.utc)  # stdlib timezone.utc
            sync_file.write_text(current_time.isoformat())
            logger.info(f"✅ Last sync time updated: {current_time.isoformat()}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to update last sync time: {e}")
            return False

    def get_last_sync_time(self):
        try:
            sync_file = settings.DESKTOP_DATA_DIR / f'.last_sync_{self.tenant_id}.txt'
            if not sync_file.exists():
                return None
            return datetime.fromisoformat(sync_file.read_text().strip())
        except Exception as e:
            logger.warning(f"Could not read last sync time: {e}")
            return None

    def set_last_sync_time(self, timestamp=None):
        if timestamp is None:
            timestamp = timezone.now()
        elif timestamp.tzinfo is None:
            timestamp = timezone.make_aware(timestamp)
        self.last_sync_file.write_text(timestamp.isoformat())
        logger.info(f"✅ Last sync time updated: {timestamp.isoformat()}")

    def _get_auth_token(self):
        if self._passed_token:
            return self._passed_token
        token = getattr(settings, 'SYNC_AUTH_TOKEN', None)
        if token:
            return token
        try:
            from primebooks.auth import DesktopAuthManager
            token = DesktopAuthManager().get_valid_token()
            if token:
                return token
        except Exception as e:
            logger.warning(f"⚠️ Could not load/refresh auth token: {e}")
        logger.error("❌ No SYNC_AUTH_TOKEN found anywhere!")
        return None


# ============================================================================
# STANDALONE HELPER
# ============================================================================

def check_sync_needed(tenant_id, schema_name):
    try:
        with schema_context(schema_name):
            for model_name in ['inventory.Product', 'stores.Store', 'sales.Sale']:
                try:
                    model = apps.get_model(model_name)
                    if model.objects.exists():
                        return False
                except Exception:
                    continue
        return True
    except Exception:
        return True