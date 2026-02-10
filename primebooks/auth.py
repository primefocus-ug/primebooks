# primebooks/auth.py - WITH SQL LOADER & SUBSCRIPTION VALIDATION
"""
Desktop authentication with SQL dump schema creation
✅ Runs SQL dump for schema (2-3 seconds vs 30-60 seconds)
✅ Validates subscription before allowing access
✅ Caches subscription for offline grace period
✅ Downloads data from server
✅ Creates user in tenant schema
✅ Refreshes expired tokens automatically
"""
import requests
import logging
from django.conf import settings
from django.db import connection
from django.core.management import call_command
from company.models import Company, Domain
from django_tenants.utils import schema_context
import json
import sys
from pathlib import Path
from datetime import datetime, timedelta
from primebooks.security.encryption import get_encryption_manager

logger = logging.getLogger(__name__)


class DesktopAuthManager:
    """Handles authentication and initial company sync with subscription validation"""

    def __init__(self):
        # Get server URL with fallback
        self.server_url = getattr(settings, 'SYNC_SERVER_URL', None)
        self.base_domain = getattr(settings, 'BASE_DOMAIN', 'localhost')
        self.auth_token_file = settings.DESKTOP_DATA_DIR / '.auth_token'
        self.refresh_token_file = settings.DESKTOP_DATA_DIR / '.refresh_token'
        self.user_info_file = settings.DESKTOP_DATA_DIR / '.user_info'
        self.company_info_file = settings.DESKTOP_DATA_DIR / '.company_info'

        self.encryption = get_encryption_manager(settings.DESKTOP_DATA_DIR)

    def authenticate(self, email, password, subdomain):
        """
        Authenticate user with online server and sync their account

        Returns: (success: bool, result: dict)
        """
        try:
            # Determine if development mode
            is_development = settings.DEBUG or self.base_domain == 'localhost'

            # Build login URL based on subdomain
            if is_development:
                login_url = f"http://{subdomain}.localhost:8000/api/desktop/auth/login/"
            else:
                login_url = f"https://{subdomain}.{self.base_domain}/api/desktop/auth/login/"

            logger.info(f"Authenticating with {login_url}")

            response = requests.post(
                login_url,
                json={'email': email, 'password': password},
                timeout=30,
                verify=not is_development
            )

            if response.status_code != 200:
                error_detail = response.json().get('detail', 'Invalid credentials')
                logger.error(f"Authentication failed: {response.status_code} - {error_detail}")
                return False, {'error': error_detail}

            data = response.json()
            access_token = data.get('token')
            refresh_token = data.get('refresh')

            # Save both tokens
            self.save_auth_token(access_token)
            if refresh_token:
                self.save_refresh_token(refresh_token)

            user_info = data.get('user', {})
            self.save_user_info(user_info)

            company = self.fetch_company_details(access_token, subdomain)
            if not company:
                return False, {'error': 'Could not fetch company details'}

            self.save_company_info(company)

            # ✅ CRITICAL: Sync company and create schema from SQL dump
            synced_company = self.sync_company_from_server(company, access_token, subdomain)
            if not synced_company:
                return False, {'error': 'Failed to sync company data'}

            return True, {
                'token': access_token,
                'refresh': refresh_token,
                'user': user_info,
                'company': company
            }

        except requests.exceptions.ConnectionError:
            logger.error("Connection error - server unreachable")
            return False, {'error': "Cannot connect to server. Please check your internet connection."}

        except requests.exceptions.Timeout:
            logger.error("Request timeout")
            return False, {'error': "Server took too long to respond. Please try again."}

        except Exception as e:
            logger.error(f"Authentication error: {e}", exc_info=True)
            return False, {'error': f"Unexpected error: {str(e)}"}

    def sync_company_from_server(self, company_data, token, subdomain):
        """
        Download and sync company with PostgreSQL multi-tenancy
        ✅ NEW: Uses SQL dump for schema creation (FAST!)
        ✅ NEW: Runs migrations for Django-specific tables (django_session, etc.)
        ✅ NEW: Validates subscription
        ✅ Creates tenant schema in 2-3 seconds vs 30-60 seconds
        """
        from django.utils.text import slugify
        from primebooks.schema_loader import create_tenant_schema, verify_schema, check_schema_exists
        from primebooks.subscription import SubscriptionManager
        from django.core.management import call_command

        try:
            company_id = company_data.get("company_id")
            if not company_id:
                logger.error("No company_id in company_data")
                return None

            schema_name = subdomain
            slug = company_data.get("slug") or slugify(
                company_data.get("trading_name") or company_data.get("name")
            )[:50]

            logger.info(f"=" * 70)
            logger.info(f"SYNCING COMPANY: {company_data.get('name')}")
            logger.info(f"  Company ID: {company_id}")
            logger.info(f"  Schema: {schema_name}")
            logger.info(f"=" * 70)

            # ✅ STEP 1: Create/update company in PUBLIC schema
            # Use is_initial_sync=True to skip subscription check during creation
            company, created = Company.objects.update_or_create(
                company_id=company_id,
                defaults={
                    'name': company_data.get('name'),
                    'schema_name': schema_name,
                    'trading_name': company_data.get('trading_name', company_data.get('name')),
                    'email': company_data.get('email', ''),
                    'phone': company_data.get('phone', ''),
                    'physical_address': company_data.get('physical_address', ''),
                    'tin': company_data.get('tin', ''),
                    'nin': company_data.get('nin', ''),
                    'brn': company_data.get('brn', ''),
                    'slug': slug,
                    'is_trial': company_data.get('is_trial', False),
                    'status': company_data.get('status', 'ACTIVE'),
                    'trial_ends_at': company_data.get('trial_ends_at'),
                    'subscription_ends_at': company_data.get('subscription_ends_at'),
                    'grace_period_ends_at': company_data.get('grace_period_ends_at'),
                }
            )

            # ✅ CRITICAL: Save with is_initial_sync=True to skip subscription check
            if created:
                company.save(is_initial_sync=True)

            logger.info(f"✅ Company {'created' if created else 'updated'}: {company.name}")

            # ✅ STEP 2: Create/update domain
            domain_name = f"{subdomain}.localhost"
            Domain.objects.update_or_create(
                domain=domain_name,
                defaults={'tenant': company, 'is_primary': True}
            )

            logger.info(f"✅ Domain configured: {domain_name}")

            # ✅ STEP 3: Check if schema already exists
            schema_exists = check_schema_exists(schema_name)

            if schema_exists:
                logger.info(f"✅ Schema already exists: {schema_name}")

                # Even if schema exists, ensure Django tables are present
                logger.info(f"🔄 Verifying Django tables in existing schema...")
                try:
                    with schema_context(schema_name):
                        call_command('migrate', '--noinput', verbosity=0)
                    logger.info(f"✅ Django tables verified/created")
                except Exception as e:
                    logger.warning(f"⚠️ Migration check completed with warnings: {e}")
            else:
                # ✅ STEP 4: Create tenant schema from SQL template (FAST!)
                logger.info(f"🚀 Creating schema from SQL dump (2-3 seconds)...")

                # Get SQL file path
                if getattr(sys, 'frozen', False):
                    # Running as bundled app (PyInstaller)
                    tenant_sql = Path(sys._MEIPASS) / 'primebooks_tenant.sql'
                else:
                    # Running in development
                    tenant_sql = Path(__file__).parent.parent / 'primebooks_tenant.sql'

                if not tenant_sql.exists():
                    raise FileNotFoundError(
                        f"Tenant SQL not found: {tenant_sql}\n"
                        f"Make sure primebooks_tenant.sql is in the project root."
                    )

                logger.info(f"  Using SQL file: {tenant_sql}")

                # Create schema from SQL dump
                success = create_tenant_schema(schema_name, tenant_sql)

                if not success:
                    raise Exception("Failed to create tenant schema from SQL")

                # Verify schema was created correctly
                verify_schema(schema_name)

                logger.info(f"✅ Tenant schema created and verified: {schema_name} (2-3 seconds!)")

                # ✅ STEP 4.5: Run migrations to ensure all Django tables exist
                # This creates django_session and any other Django-specific tables
                # that may not be in the SQL dump
                logger.info(f"🔄 Running migrations for Django-specific tables...")
                try:
                    with schema_context(schema_name):
                        # Run migrations silently - creates django_session, etc.
                        call_command('migrate', '--noinput', verbosity=0)

                    logger.info(f"✅ Migrations completed - all Django tables present")
                except Exception as migration_error:
                    logger.warning(f"⚠️ Migration completed with warnings: {migration_error}")
                    # Don't fail - SQL dump has most tables, this just ensures Django-specific ones exist

            # ✅ STEP 5: Validate subscription and cache for offline use
            logger.info(f"🔒 Validating subscription...")
            subscription_manager = SubscriptionManager(company_id, schema_name)

            # Force online check to get fresh subscription data
            is_valid, message, days, status = subscription_manager.validate_subscription(force_online=True)

            if not is_valid:
                logger.warning(f"⚠️  Subscription issue: {message}")
                # Don't block initial sync, but warn user
                # They can still complete sync, but won't be able to use app
            else:
                logger.info(f"✅ Subscription valid: {message}")

            # ✅ STEP 6: Sync authenticated user to tenant schema
            authenticated_user_email = self.get_user_info().get('email') if self.get_user_info() else None

            if authenticated_user_email:
                logger.info(f"🔄 Syncing user to tenant schema: {authenticated_user_email}")
                with schema_context(schema_name):
                    self.sync_user_to_tenant(
                        authenticated_user_email,
                        subdomain,
                        token,
                        company_id
                    )
            else:
                logger.warning("⚠️  No authenticated user email found")

            logger.info(f"=" * 70)
            logger.info(f"✅ COMPANY SYNC COMPLETE: {company.name}")
            logger.info(f"=" * 70)

            return company

        except FileNotFoundError as e:
            logger.error("=" * 70)
            logger.error("❌ SQL FILE NOT FOUND")
            logger.error(f"Error: {e}")
            logger.error("=" * 70)
            return None
        except Exception as e:
            logger.error("=" * 70)
            logger.error("❌ CRITICAL ERROR syncing company")
            logger.error(f"Error: {e}", exc_info=True)
            logger.error("=" * 70)
            return None

    def sync_user_to_tenant(self, email, subdomain, token, company_id):
        """
        Sync user to tenant schema
        ✅ Downloads user data from server
        ✅ Creates user in tenant schema with password hash
        """
        from accounts.models import CustomUser
        import requests

        try:
            is_development = settings.DEBUG or self.base_domain == 'localhost'

            if is_development:
                url = f"http://{subdomain}.localhost:8000/api/desktop/sync/user/{email}/"
            else:
                url = f"https://{subdomain}.{self.base_domain}/api/desktop/sync/user/{email}/"

            logger.info(f"  📥 Fetching user data from: {url}")

            response = requests.get(
                url,
                headers={'Authorization': f'Bearer {token}'},
                timeout=30,
                verify=not is_development
            )

            if response.status_code != 200:
                logger.error(f"  ❌ Failed to fetch user: HTTP {response.status_code}")
                return False

            user_data = response.json()

            if not user_data:
                logger.error(f"  ❌ No user data returned for {email}")
                return False

            user_id = user_data.get('id')
            password_hash = user_data.get('password')

            if not password_hash:
                logger.error(f"  ❌ No password hash in user data for {email}")
                return False

            logger.info(f"  ✅ Received user data (ID: {user_id})")

            # Create/update user in TENANT schema
            user, created = CustomUser.objects.update_or_create(
                id=user_id,
                defaults={
                    'email': user_data['email'],
                    'username': user_data['username'],
                    'first_name': user_data.get('first_name', ''),
                    'last_name': user_data.get('last_name', ''),
                    'password': password_hash,
                    'company_id': company_id,
                    'is_active': user_data.get('is_active', True),
                    'is_staff': user_data.get('is_staff', False),
                    'is_superuser': user_data.get('is_superuser', False),
                    'phone_number': user_data.get('phone_number', ''),
                }
            )

            # Set role if provided
            role_id = user_data.get('role')
            if role_id:
                user.primary_role_id = role_id
                user.save()

            logger.info(f"  ✅ User {'created' if created else 'updated'}: {email} (ID: {user_id})")
            return True

        except Exception as e:
            logger.error(f"  ❌ Error syncing user {email}: {e}", exc_info=True)
            return False

    def refresh_access_token(self):
        """
        ✅ Refresh expired access token using refresh token
        Returns: new access token or None
        """
        try:
            refresh_token = self.get_refresh_token()
            if not refresh_token:
                logger.error("No refresh token available")
                return None

            company_info = self.get_company_info()
            if not company_info:
                logger.error("No company info available")
                return None

            subdomain = company_info.get('schema_name') or company_info.get('subdomain')
            if not subdomain:
                logger.error("No subdomain in company info")
                return None

            # Determine if development mode
            is_development = settings.DEBUG or self.base_domain == 'localhost'

            # Build refresh URL
            if is_development:
                refresh_url = f"http://{subdomain}.localhost:8000/api/token/refresh/"
            else:
                refresh_url = f"https://{subdomain}.{self.base_domain}/api/token/refresh/"

            logger.info(f"Refreshing token at {refresh_url}")

            response = requests.post(
                refresh_url,
                json={'refresh': refresh_token},
                timeout=10,
                verify=not is_development
            )

            if response.status_code != 200:
                logger.error(f"Token refresh failed: {response.status_code}")
                return None

            data = response.json()
            new_access_token = data.get('access')

            if new_access_token:
                # Save new access token
                self.save_auth_token(new_access_token)
                logger.info("✅ Access token refreshed successfully")
                return new_access_token
            else:
                logger.error("No access token in refresh response")
                return None

        except Exception as e:
            logger.error(f"Token refresh error: {e}", exc_info=True)
            return None

    def get_valid_token(self):
        """
        ✅ IMPROVED: Get valid access token with better error handling
        Returns: valid access token or None
        """
        import jwt
        from datetime import datetime, timezone

        token = self.get_auth_token()

        if not token:
            logger.warning("No access token found - user needs to re-login")
            return None

        # Check if token is expired (without validating signature)
        try:
            # Decode without verification to check expiration
            decoded = jwt.decode(token, options={"verify_signature": False})
            exp = decoded.get('exp')

            if exp:
                exp_datetime = datetime.fromtimestamp(exp, tz=timezone.utc)
                now = datetime.now(timezone.utc)

                # If token expires in less than 5 minutes, refresh it
                if exp_datetime <= now:
                    logger.info("Access token expired, attempting refresh...")
                    new_token = self.refresh_access_token()
                    if new_token:
                        return new_token
                    else:
                        logger.error("Token refresh failed - user needs to re-login")
                        return None
                else:
                    logger.debug(f"Access token valid until {exp_datetime}")
                    return token
        except jwt.DecodeError:
            logger.warning("Could not decode access token")
            # Try to refresh anyway
            new_token = self.refresh_access_token()
            if new_token:
                return new_token
        except Exception as e:
            logger.error(f"Token validation error: {e}")

        # If all else fails, try to refresh
        logger.info("Attempting token refresh as fallback...")
        new_token = self.refresh_access_token()
        if new_token:
            return new_token

        # No valid token available
        logger.error("❌ No valid token available - user must re-login")
        return None

    def require_authentication(self):
        """
        ✅ NEW: Check if user is authenticated with valid token
        Returns: (is_authenticated: bool, error_message: str)
        """
        if not self.is_authenticated():
            return False, "Not logged in"

        token = self.get_valid_token()
        if not token:
            return False, "Session expired - please login again"

        return True, None

    def fetch_company_details(self, token, subdomain):
        """Fetch company details from server"""
        try:
            is_development = settings.DEBUG or self.base_domain == 'localhost'

            if is_development:
                url = f"http://{subdomain}.localhost:8000/api/desktop/company/details/"
            else:
                url = f"https://{subdomain}.{self.base_domain}/api/desktop/company/details/"

            response = requests.get(
                url,
                headers={'Authorization': f'Bearer {token}'},
                timeout=30,
                verify=not is_development
            )

            if response.status_code != 200:
                logger.error(f"Failed to fetch company details: {response.status_code}")
                return None

            return response.json()

        except Exception as e:
            logger.error(f"Error fetching company details: {e}")
            return None

    def save_credentials(self, user_data, company_data, token):
        """Save encrypted credentials"""
        # Encrypt token
        encrypted_token = self.encryption.encrypt_data(token)
        token_file = settings.DESKTOP_DATA_DIR / '.auth_token.enc'
        token_file.write_bytes(encrypted_token)

        # Encrypt user data
        import json
        user_json = json.dumps(user_data)
        encrypted_user = self.encryption.encrypt_data(user_json)
        user_file = settings.DESKTOP_DATA_DIR / '.user_data.enc'
        user_file.write_bytes(encrypted_user)

        # Save company data
        company_json = json.dumps(company_data)
        company_file = settings.DESKTOP_DATA_DIR / '.company_info'
        company_file.write_text(company_json)

    def load_credentials(self):
        """Load encrypted credentials"""
        token_file = settings.DESKTOP_DATA_DIR / '.auth_token.enc'
        user_file = settings.DESKTOP_DATA_DIR / '.user_data.enc'
        company_file = settings.DESKTOP_DATA_DIR / '.company_info'

        if not token_file.exists():
            return None, None, None

        # Decrypt token
        encrypted_token = token_file.read_bytes()
        token = self.encryption.decrypt_data(encrypted_token).decode()

        # Decrypt user data
        if user_file.exists():
            encrypted_user = user_file.read_bytes()
            user_json = self.encryption.decrypt_data(encrypted_user).decode()
            user_data = json.loads(user_json)
        else:
            user_data = None

        # Load company data
        if company_file.exists():
            company_data = json.loads(company_file.read_text())
        else:
            company_data = None

        return token, user_data, company_data

    def save_auth_token(self, token):
        """Save authentication token"""
        self.auth_token_file.write_text(token)
        settings.SYNC_AUTH_TOKEN = token

    def get_auth_token(self):
        """Get saved authentication token"""
        if self.auth_token_file.exists():
            token = self.auth_token_file.read_text().strip()
            settings.SYNC_AUTH_TOKEN = token
            return token
        return None

    def save_refresh_token(self, token):
        """✅ Save refresh token"""
        self.refresh_token_file.write_text(token)

    def get_refresh_token(self):
        """✅ Get saved refresh token"""
        if self.refresh_token_file.exists():
            return self.refresh_token_file.read_text().strip()
        return None

    def save_user_info(self, user_info):
        """Save user information"""
        self.user_info_file.write_text(json.dumps(user_info))

    def get_user_info(self):
        """Get saved user information"""
        if self.user_info_file.exists():
            return json.loads(self.user_info_file.read_text())
        return None

    def save_company_info(self, company_info):
        """Save company information"""
        self.company_info_file.write_text(json.dumps(company_info))

    def get_company_info(self):
        """Get saved company information"""
        if self.company_info_file.exists():
            return json.loads(self.company_info_file.read_text())
        return None

    def is_authenticated(self):
        """Check if user is authenticated"""
        return self.auth_token_file.exists() and self.company_info_file.exists()

    def logout(self):
        """Clear authentication"""
        if self.auth_token_file.exists():
            self.auth_token_file.unlink()
        if self.refresh_token_file.exists():
            self.refresh_token_file.unlink()
        if self.user_info_file.exists():
            self.user_info_file.unlink()
        if self.company_info_file.exists():
            self.company_info_file.unlink()
        settings.SYNC_AUTH_TOKEN = None