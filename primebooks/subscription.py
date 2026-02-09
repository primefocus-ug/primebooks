# primebooks/subscription.py
"""
Subscription Manager for Desktop App
✅ Validates subscription with online/offline support
✅ Grace period enforcement
✅ Cached subscription data
✅ Works with Company model
"""
import logging
import json
from datetime import datetime, timedelta
from pathlib import Path
from django.conf import settings
from django.utils import timezone
import requests

logger = logging.getLogger(__name__)


class SubscriptionManager:
    """
    Manage subscription validation with offline grace period
    ✅ Downloads subscription status when online
    ✅ Caches locally for grace period (7 days)
    ✅ Enforces limits when offline
    """

    # Configuration
    GRACE_PERIOD_DAYS = 7  # How long offline access is allowed
    HARD_LIMIT_DAYS = 30  # Must check online at least once per month
    CACHE_EXPIRY_DAYS = 1  # Refresh cache daily when online

    def __init__(self, company_id, schema_name):
        self.company_id = company_id
        self.schema_name = schema_name
        self.cache_file = settings.DESKTOP_DATA_DIR / f'.subscription_{company_id}'

        # Get server URL
        self.server_url = self._get_server_url()

    def _get_server_url(self):
        """Get server URL based on DEBUG mode"""
        if hasattr(settings, 'SYNC_SERVER_URL'):
            return settings.SYNC_SERVER_URL

        if settings.DEBUG:
            return f"http://{self.schema_name}.localhost:8000"
        else:
            return f"https://{self.schema_name}.primebooks.sale"

    def validate_subscription(self, force_online=False):
        """
        Validate subscription with smart online/offline handling

        Returns:
            (is_valid: bool, message: str, days_remaining: int, status_code: str)
        """
        logger.info("=" * 60)
        logger.info(f"SUBSCRIPTION VALIDATION")
        logger.info(f"  Company: {self.company_id}")
        logger.info(f"  Force online: {force_online}")
        logger.info("=" * 60)

        # Try online check first (if connected or forced)
        if force_online or self.is_online():
            return self.validate_online()

        # Fall back to cached validation
        logger.info("  Offline mode - using cached validation")
        return self.validate_cached()

    def validate_online(self):
        """
        Validate subscription with cloud server
        ✅ Real-time check
        ✅ Updates local cache
        """
        try:
            from primebooks.auth import DesktopAuthManager

            auth_manager = DesktopAuthManager()
            token = auth_manager.get_valid_token()  # Auto-refreshes if needed

            if not token:
                logger.warning("No auth token - falling back to cache")
                return self.validate_cached()

            logger.info(f"  Checking subscription online: {self.server_url}")

            # Get subscription status from cloud
            response = requests.get(
                f"{self.server_url}/api/desktop/subscription/status/",
                headers={'Authorization': f'Bearer {token}'},
                params={'company_id': self.company_id},
                timeout=10
            )

            if response.status_code != 200:
                logger.warning(f"Cloud check failed (HTTP {response.status_code}), using cache")
                return self.validate_cached()

            data = response.json()

            # Build subscription data
            subscription_data = {
                'company_id': self.company_id,
                'is_active': data.get('is_active'),
                'status': data.get('status'),  # ACTIVE, TRIAL, EXPIRED, SUSPENDED
                'is_trial': data.get('is_trial', False),
                'plan_name': data.get('plan', {}).get('name', 'Unknown'),
                'trial_ends_at': data.get('trial_ends_at'),
                'subscription_ends_at': data.get('subscription_ends_at'),
                'grace_period_ends_at': data.get('grace_period_ends_at'),
                'checked_at': datetime.now().isoformat(),
                'grace_period_days': self.GRACE_PERIOD_DAYS,
            }

            # Cache the subscription data
            self.save_cache(subscription_data)

            # Calculate days remaining
            if subscription_data['is_trial']:
                if subscription_data['trial_ends_at']:
                    expires_at = datetime.fromisoformat(subscription_data['trial_ends_at'].replace('Z', '+00:00'))
                    days_remaining = (expires_at - datetime.now(expires_at.tzinfo)).days
                else:
                    days_remaining = 999
            else:
                if subscription_data['subscription_ends_at']:
                    expires_at = datetime.fromisoformat(
                        subscription_data['subscription_ends_at'].replace('Z', '+00:00'))
                    days_remaining = (expires_at - datetime.now(expires_at.tzinfo)).days
                else:
                    days_remaining = 999

            # Validate
            if subscription_data['is_active']:
                status = subscription_data['status']

                if status == 'TRIAL':
                    message = f"✓ Trial active ({days_remaining} days remaining)"
                elif status == 'ACTIVE':
                    message = f"✓ Subscription active ({days_remaining} days remaining)"
                else:
                    message = f"✓ Access active"

                logger.info(f"  ✅ {message}")
                return True, message, days_remaining, status
            else:
                status = subscription_data['status']
                message = f"Subscription {status.lower()}"

                logger.warning(f"  ❌ {message}")
                return False, message, 0, status

        except Exception as e:
            logger.error(f"Online subscription check failed: {e}")
            return self.validate_cached()

    def validate_cached(self):
        """
        Validate subscription using cached data
        ✅ Works offline
        ✅ Enforces grace period
        """
        if not self.cache_file.exists():
            message = "No cached subscription data. Please connect to internet."
            logger.error(f"  ❌ {message}")
            return False, message, 0, 'UNKNOWN'

        try:
            # Load cached data
            cached_data = json.loads(self.cache_file.read_text())

            checked_at = datetime.fromisoformat(cached_data['checked_at'])
            cache_age_days = (datetime.now() - checked_at).days

            logger.info(f"  Using cache from {cache_age_days} days ago")

            # Check hard limit (30 days)
            if cache_age_days > self.HARD_LIMIT_DAYS:
                message = (
                    f"Subscription status expired {cache_age_days} days ago. "
                    f"Please connect to internet to verify subscription."
                )
                logger.error(f"  ❌ {message}")
                return False, message, 0, 'CACHE_EXPIRED'

            # Check if subscription itself was active when cached
            if not cached_data['is_active']:
                status = cached_data['status']
                message = f"Subscription {status.lower()}"
                logger.warning(f"  ❌ {message}")
                return False, message, 0, status

            # Calculate days remaining based on cached expiry dates
            is_trial = cached_data.get('is_trial', False)

            if is_trial:
                expires_at_str = cached_data.get('trial_ends_at')
            else:
                expires_at_str = cached_data.get('subscription_ends_at')

            if not expires_at_str:
                # No expiry date - assume active
                message = f"✓ Subscription active (checked {cache_age_days} days ago)"
                logger.info(f"  ✅ {message}")
                return True, message, 999, cached_data['status']

            # Parse expiry date
            expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
            now = datetime.now(expires_at.tzinfo)

            # Check if subscription has expired since cache
            if now > expires_at:
                # Subscription expired
                days_overdue = (now - expires_at).days

                # Check grace period
                if cache_age_days > self.GRACE_PERIOD_DAYS:
                    message = (
                        f"Subscription expired {days_overdue} days ago. "
                        f"Grace period ended. Please connect to internet."
                    )
                    logger.error(f"  ❌ {message}")
                    return False, message, 0, 'GRACE_EXPIRED'

                # Still in grace period
                days_remaining_in_grace = self.GRACE_PERIOD_DAYS - cache_age_days
                message = (
                    f"⚠️ Subscription expired. Working offline with "
                    f"{days_remaining_in_grace} days grace period remaining."
                )
                logger.warning(f"  ⚠️  {message}")
                return True, message, days_remaining_in_grace, 'GRACE_PERIOD'

            # Subscription is still active
            days_remaining = (expires_at - now).days

            if cache_age_days > 0:
                message = (
                    f"✓ Subscription active (checked {cache_age_days} days ago, "
                    f"{days_remaining} days remaining)"
                )
            else:
                message = f"✓ Subscription active ({days_remaining} days remaining)"

            logger.info(f"  ✅ {message}")
            return True, message, days_remaining, cached_data['status']

        except Exception as e:
            logger.error(f"Cached subscription validation failed: {e}", exc_info=True)
            message = "Subscription validation error. Please connect to internet."
            return False, message, 0, 'ERROR'

    def save_cache(self, data):
        """Save subscription data to cache"""
        try:
            self.cache_file.write_text(json.dumps(data, indent=2))
            logger.info(f"✅ Subscription cache updated for company {self.company_id}")

            # Also save backup (hidden)
            backup_file = self.cache_file.parent / f'.{self.cache_file.name}.bak'
            backup_file.write_text(json.dumps(data, indent=2))
        except Exception as e:
            logger.error(f"Failed to save subscription cache: {e}")

    def is_online(self):
        """Check if device has internet connectivity"""
        try:
            response = requests.get('https://www.google.com', timeout=3)
            return response.status_code == 200
        except:
            return False

    def force_refresh(self):
        """Force refresh subscription from server"""
        logger.info("Force refreshing subscription status...")
        return self.validate_online()

    def get_cached_status(self):
        """Get cached subscription status without validation"""
        if not self.cache_file.exists():
            return None

        try:
            return json.loads(self.cache_file.read_text())
        except:
            return None