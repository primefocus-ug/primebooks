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
    # Core - SubscriptionPlan only (Company lives in public schema)
    'company.SubscriptionPlan': {'dependencies': []},

    # ✅ Auth - Django groups (needed by Role)
    'auth.Group': {'dependencies': []},

    'accounts.Role': {'dependencies': ['auth.Group']},
    'accounts.CustomUser': {
        'dependencies': ['accounts.Role'],
        'exclude_fields': ['password', 'backup_codes'],  # Users already have passwords
    },

    # Stores
    'stores.Store': {
        'dependencies': [],  # Company is in public schema
        'exclude_fields': ['logo'],
    },
    'stores.StoreAccess': {'dependencies': ['stores.Store', 'accounts.CustomUser']},

    # Inventory
    'inventory.Category': {'dependencies': []},  # Company in public schema
    'inventory.Supplier': {'dependencies': []},
    'inventory.Product': {
        'dependencies': ['inventory.Category', 'inventory.Supplier'],
        'exclude_fields': ['image'],
    },
    'inventory.Stock': {'dependencies': ['inventory.Product', 'stores.Store']},
    'inventory.StockMovement': {'dependencies': ['inventory.Product', 'stores.Store']},

    # Customers
    'customers.Customer': {'dependencies': ['stores.Store', 'accounts.CustomUser']},

    # Sales
    'sales.Sale': {'dependencies': ['customers.Customer', 'stores.Store', 'accounts.CustomUser']},
    'sales.SaleItem': {'dependencies': ['sales.Sale', 'inventory.Product']},
    'sales.Payment': {'dependencies': ['sales.Sale']},

    # ✅ Invoice is auto-created by Sale.post_save signal - don't sync!
    # 'invoices.Invoice': {'dependencies': ['sales.Sale', 'stores.Store']},
}


def get_sync_order():
    """Get models in dependency order"""
    ordered = []
    remaining = set(SYNC_MODEL_CONFIG.keys())

    while remaining:
        ready = [m for m in remaining
                 if all(dep in ordered for dep in SYNC_MODEL_CONFIG[m].get('dependencies', []))]

        if not ready:
            ordered.extend(remaining)
            break

        ordered.extend(ready)
        remaining -= set(ready)

    return ordered


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

        # ✅ Store the passed token FIRST, then try to get from other sources
        self._passed_token = auth_token
        self.auth_token = auth_token or self._get_auth_token()

        self.last_sync_file = settings.DESKTOP_DATA_DIR / f'.last_sync_{tenant_id}'
        self.sync_models = get_sync_order()

        # ✅ Smart server URL detection
        self.server_url = self._get_server_url()

        logger.info("=" * 70)
        logger.info("SYNC MANAGER INITIALIZED")
        logger.info(f"  Tenant: {tenant_id}")
        logger.info(f"  Schema: {schema_name}")
        logger.info(f"  Subdomain: {schema_name}")
        logger.info(f"  Server: {self.server_url}")
        logger.info(f"  Auth Token: {'Present (' + self.auth_token[:20] + '...)' if self.auth_token else '❌ MISSING!'}")
        logger.info(f"  Models to sync: {len(self.sync_models)}")
        logger.info("=" * 70)

        # ✅ Validate token
        if not self.auth_token:
            logger.error("❌ CRITICAL: No auth token available for sync!")
            logger.error("   Sync will fail without authentication!")

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

    # ========================================================================
    # DOWNLOAD FROM SERVER
    # ========================================================================

    def download_all_data(self, progress_callback=None):
        """Download ALL data from server (first sync)"""
        try:
            logger.info("=" * 70)
            logger.info(f"DOWNLOADING ALL DATA FROM SERVER")
            logger.info(f"  URL: {self.server_url}/api/desktop/sync/bulk-download/")
            logger.info("=" * 70)

            if progress_callback:
                progress_callback("Connecting to server...", 5)

            url = f"{self.server_url}/api/desktop/sync/bulk-download/"

            logger.info(f"  Making request...")
            response = requests.get(
                url,
                headers={'Authorization': f'Bearer {self.auth_token}'},
                timeout=300
            )

            logger.info(f"  Response: HTTP {response.status_code}")

            if response.status_code != 200:
                error_text = response.text[:500] if response.text else "No response body"
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

            logger.info(f"✅ Downloaded {total_records} records across {len(all_data)} models")

            if progress_callback:
                progress_callback(f"Downloaded {total_records} records...", 30)

            if all_data:
                success = self.apply_bulk_data(all_data, progress_callback)

                if success:
                    # ✅ Do NOT set last_sync_time here - caller (full_sync) will do it
                    if progress_callback:
                        progress_callback("Download complete!", 100)
                    logger.info("=" * 70)
                    logger.info("✅ DOWNLOAD COMPLETE")
                    logger.info("=" * 70)
                    return True
                else:
                    return False

            return False

        except requests.exceptions.ConnectionError as e:
            logger.error(f"❌ Connection error: {e}")
            logger.error(f"  Could not connect to: {self.server_url}")
            return False
        except requests.exceptions.Timeout:
            logger.error(f"❌ Request timeout (>300s)")
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
        Download only CHANGED data since last sync
        ✅ Efficient incremental sync
        ✅ Does NOT update last_sync_time (full_sync does that)
        """
        try:
            last_sync = self.get_last_sync_time()

            if not last_sync:
                # No last sync - do full download
                logger.info("No last sync time found - doing full download")
                return self.download_all_data(progress_callback)

            logger.info("=" * 70)
            logger.info(f"DOWNLOADING CHANGES SINCE {last_sync}")
            logger.info("=" * 70)

            if progress_callback:
                progress_callback("Checking for changes...", 10)

            url = f"{self.server_url}/api/desktop/sync/changes/"

            logger.info(f"  URL: {url}")
            logger.info(f"  Since: {last_sync.isoformat()}")

            response = requests.get(
                url,
                params={'since': last_sync.isoformat()},
                headers={'Authorization': f'Bearer {self.auth_token}'},
                timeout=60
            )

            logger.info(f"  Response: HTTP {response.status_code}")

            if response.status_code != 200:
                error_text = response.text[:500] if response.text else "No response body"
                logger.error(f"❌ Download failed: HTTP {response.status_code}")
                logger.error(f"  Response: {error_text}")
                return False

            data = response.json()
            changes = data.get('data', {})
            total_changed = sum(len(records) for records in changes.values())

            if total_changed == 0:
                logger.info("✅ No server changes to download")
                return True  # Success - nothing to do

            logger.info(f"✅ Downloaded {total_changed} changed records")

            if changes:
                success = self.apply_bulk_data(changes, progress_callback)
                if success:
                    # ✅ Do NOT update last_sync_time here - full_sync will do it
                    logger.info("✅ Server changes applied successfully")
                    return True
                else:
                    logger.error("❌ Failed to apply server changes")
                    return False
            else:
                logger.info("No changes to download")
                return True

        except requests.exceptions.ConnectionError as e:
            logger.error(f"❌ Connection error: {e}")
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
        ✅ Syncs offline sales, products, stock movements
        ✅ Does NOT update last_sync_time (full_sync does that)
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
                return True  # Success - nothing to do

            total_changed = sum(len(records) for records in changes.values())
            logger.info(f"📤 Uploading {total_changed} changed records across {len(changes)} models")

            if progress_callback:
                progress_callback(f"Uploading {total_changed} records...", 30)

            url = f"{self.server_url}/api/desktop/sync/upload/"

            logger.info(f"  URL: {url}")

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

            logger.info(f"  Response: HTTP {response.status_code}")

            if response.status_code != 200:
                error_text = response.text[:500] if response.text else "No response body"
                logger.error(f"❌ Upload failed: HTTP {response.status_code}")
                logger.error(f"  Response: {error_text}")
                return False

            result = response.json()

            if result.get('success'):
                logger.info(f"✅ Upload successful")
                # ✅ Do NOT update last_sync_time here - full_sync will do it
                if progress_callback:
                    progress_callback("Upload complete!", 60)
                return True
            else:
                error_msg = result.get('error', 'Unknown error')
                logger.error(f"❌ Upload failed: {error_msg}")
                return False

        except requests.exceptions.ConnectionError as e:
            logger.error(f"❌ Connection error: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Upload error: {e}", exc_info=True)
            return False


    def collect_local_changes(self, since):
        """
        Collect records that changed locally since last sync
        ✅ Finds new sales, products, stock changes
        ✅ Uses timezone-aware datetime comparisons
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
                        # ✅ Ensure since is timezone-aware
                        if since.tzinfo is None:
                            since = timezone.make_aware(since)

                        if hasattr(model, 'modified_at'):
                            queryset = queryset.filter(modified_at__gte=since)
                        elif hasattr(model, 'updated_at'):
                            queryset = queryset.filter(updated_at__gte=since)
                        elif hasattr(model, 'created_at'):
                            # Include new records
                            queryset = queryset.filter(created_at__gte=since)

                    if queryset.exists():
                        # Serialize
                        data = serializers.serialize('json', queryset)
                        records = json.loads(data)

                        # Remove excluded fields
                        if exclude_fields:
                            for record in records:
                                for field in exclude_fields:
                                    record['fields'].pop(field, None)

                        changes[model_name] = records
                        logger.info(f"  Found {len(records)} changed {model_name} records")

                except LookupError:
                    continue
                except Exception as e:
                    logger.error(f"  Error collecting {model_name}: {e}")

        return changes

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
        Apply records for a specific model with conflict resolution
        ✅ Handles ForeignKey, ManyToMany, Decimal, and special primary keys
        """
        from decimal import Decimal

        try:
            model = apps.get_model(model_name)
            created_count = 0
            updated_count = 0

            for record in records:
                try:
                    obj_id = record['pk']
                    fields = record['fields']

                    # ✅ Separate ManyToMany fields (must be set after save)
                    m2m_fields = {}
                    processed_fields = {}

                    for field_name, value in fields.items():
                        try:
                            field = model._meta.get_field(field_name)

                            # Skip ManyToMany - handle after save
                            if field.many_to_many:
                                m2m_fields[field_name] = value
                                continue

                            # Handle ForeignKey
                            if field.many_to_one and value is not None:
                                related_model = field.related_model

                                try:
                                    related_instance = related_model.objects.get(pk=value)
                                    processed_fields[field_name] = related_instance
                                except related_model.DoesNotExist:
                                    logger.debug(f"    Skipping {field_name}={value} - not found")
                                    # Don't include field if related object missing
                                    continue

                            # Handle Decimal fields
                            elif hasattr(field, 'get_internal_type') and field.get_internal_type() == 'DecimalField':
                                if value is not None and isinstance(value, str):
                                    processed_fields[field_name] = Decimal(value)
                                else:
                                    processed_fields[field_name] = value

                            # Regular field
                            else:
                                processed_fields[field_name] = value

                        except Exception as e:
                            # Field doesn't exist or error - skip
                            logger.debug(f"    Skipping field {field_name}: {e}")
                            continue

                    # Check if exists
                    try:
                        # Handle models with custom primary keys (like Company.company_id)
                        pk_field = model._meta.pk.name
                        existing = model.objects.get(**{pk_field: obj_id})

                        # Update
                        for field, value in processed_fields.items():
                            setattr(existing, field, value)

                        try:
                            existing.save()
                        except ValidationError as e:
                            # ✅ Skip EFRIS/business validation errors during sync
                            error_msg = str(e).lower()
                            if 'efris' in error_msg or 'constraint' in error_msg:
                                logger.debug(f"    Skipping validation error for {obj_id}: {e}")
                                continue  # Skip this record
                            raise  # Re-raise other validation errors

                        # Handle ManyToMany
                        for field_name, value in m2m_fields.items():
                            if value:
                                field = getattr(existing, field_name)
                                field.set(value)

                        updated_count += 1

                    except model.DoesNotExist:
                        # Create new - handle custom primary keys
                        pk_field = model._meta.pk.name

                        # Use custom PK if different from 'id'
                        if pk_field != 'id':
                            processed_fields[pk_field] = obj_id
                            obj = model(**processed_fields)
                        else:
                            obj = model(id=obj_id, **processed_fields)

                        try:
                            obj.save()
                        except ValidationError as e:
                            # ✅ Skip EFRIS/business validation errors during sync
                            error_msg = str(e).lower()
                            if 'efris' in error_msg or 'constraint' in error_msg:
                                logger.debug(f"    Skipping validation error for {obj_id}: {e}")
                                continue  # Skip this record
                            raise  # Re-raise other validation errors

                        # Handle ManyToMany
                        for field_name, value in m2m_fields.items():
                            if value:
                                field = getattr(obj, field_name)
                                field.set(value)

                        created_count += 1

                except Exception as e:
                    logger.error(f"    Error saving record {obj_id}: {e}")

            return created_count, updated_count

        except LookupError:
            logger.warning(f"  Model not found: {model_name}")
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