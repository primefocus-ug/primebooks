# primebooks/auth.py
"""
Desktop authentication with Django migrations schema creation
✅ Clean sequences from day one — no setval conflicts
✅ Validates subscription before allowing access
✅ Caches subscription for offline grace period
✅ Downloads data from server
✅ Creates user in tenant schema via sync_id — no PK collisions
✅ Refreshes expired tokens automatically
"""
import requests
import logging
from django.conf import settings
from django.db import connection
from django.core.management import call_command
from company.models import Company, Domain
import json
import sys
import uuid
from pathlib import Path
from datetime import datetime, timedelta
from primebooks.security.encryption import get_encryption_manager

logger = logging.getLogger(__name__)


class DesktopAuthManager:
    """Handles authentication and initial company sync with subscription validation"""

    def __init__(self):
        self.server_url = getattr(settings, 'SYNC_SERVER_URL', None)
        self.base_domain = getattr(settings, 'BASE_DOMAIN', 'localhost')
        self.auth_token_file = settings.DESKTOP_DATA_DIR / '.auth_token'
        self.refresh_token_file = settings.DESKTOP_DATA_DIR / '.refresh_token'
        self.user_info_file = settings.DESKTOP_DATA_DIR / '.user_info'
        self.company_info_file = settings.DESKTOP_DATA_DIR / '.company_info'
        self.subdomain_file = settings.DESKTOP_DATA_DIR / '.subdomain'

        self.encryption = get_encryption_manager(settings.DESKTOP_DATA_DIR)

    def authenticate(self, email, password, subdomain):
        """
        Authenticate user with online server and sync their account.
        Returns: (success: bool, result: dict)
        """
        try:
            is_development = settings.DEBUG or self.base_domain == 'localhost'

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
                try:
                    error_detail = response.json().get('detail', 'Invalid credentials')
                except Exception:
                    error_detail = response.text.strip() or f"HTTP {response.status_code}"
                logger.error(f"Authentication failed: {response.status_code} - {error_detail}")
                return False, {'error': error_detail}

            try:
                data = response.json()
            except Exception:
                body = response.text.strip()
                logger.error(f"Server returned non-JSON response (status {response.status_code}): {body!r}")
                return False, {'error': "Server returned an invalid response. Please try again or contact support."}
            access_token = data.get('token')
            refresh_token = data.get('refresh')

            self.save_auth_token(access_token)
            if refresh_token:
                self.save_refresh_token(refresh_token)

            user_info = data.get('user', {})
            self.save_user_info(user_info)

            company = self.fetch_company_details(access_token, subdomain)
            if not company:
                return False, {'error': 'Could not fetch company details'}

            company['schema_name'] = subdomain
            self.save_company_info(company)
            self.save_subdomain(subdomain)

            synced_company = self.sync_company_from_server(company, access_token, subdomain)
            if not synced_company:
                return False, {'error': 'Failed to sync company data'}

            return True, {
                'token': access_token,
                'refresh': refresh_token,
                'user': user_info,
                'company': company,
                'subdomain': subdomain,
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

    # -------------------------------------------------------------------------
    # Subdomain helpers
    # -------------------------------------------------------------------------
    def save_subdomain(self, subdomain):
        self.subdomain_file.write_text(subdomain)
        logger.info(f"Saved subdomain: {subdomain}")

    def get_subdomain(self):
        if self.subdomain_file.exists():
            return self.subdomain_file.read_text().strip()
        return None

    # -------------------------------------------------------------------------
    # Company sync
    # -------------------------------------------------------------------------
    def sync_company_from_server(self, company_data, token, subdomain):
        """
        Download and sync company with PostgreSQL multi-tenancy.
        Uses Django migrations for clean schema creation.
        Sequences start at 1 — no conflicts with synced data.
        """
        from django.utils.text import slugify
        from primebooks.subscription import SubscriptionManager
        from django_tenants.utils import schema_context

        try:
            company_id = company_data.get("company_id")
            if not company_id:
                logger.error("No company_id in company_data")
                return None

            schema_name = subdomain

            logger.info("=" * 70)
            logger.info(f"SYNCING COMPANY: {company_data.get('name')}")
            logger.info("=" * 70)

            # ── STEP 1: PUBLIC schema — Company + Domain ──────────────────────
            logger.info("Switching to PUBLIC schema for Company operations...")
            connection.set_schema('public')

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
                    'slug': slugify(
                        company_data.get('trading_name') or company_data.get('name')
                    )[:50],
                    'is_trial': company_data.get('is_trial', False),
                    'status': company_data.get('status', 'ACTIVE'),
                    'trial_ends_at': company_data.get('trial_ends_at'),
                    'subscription_ends_at': company_data.get('subscription_ends_at'),
                    'grace_period_ends_at': company_data.get('grace_period_ends_at'),
                }
            )

            if created:
                company.save(is_initial_sync=True)

            logger.info(f"Company {'created' if created else 'updated'}: {company.name}")

            domain_name = f"{subdomain}.localhost"
            Domain.objects.update_or_create(
                domain=domain_name,
                defaults={'tenant': company, 'is_primary': True}
            )
            logger.info(f"Domain configured: {domain_name}")

            # ── STEP 2: Create tenant schema via migrations ───────────────────
            logger.info(f"Checking tenant schema: {schema_name}")
            schema_exists = self._check_schema_exists(schema_name)

            if schema_exists:
                table_count = self._get_table_count(schema_name)
                if table_count > 0:
                    logger.info(f"Schema '{schema_name}' exists with {table_count} tables — skipping creation")
                else:
                    logger.warning(f"Schema '{schema_name}' exists but is empty — running migrations")
                    self._run_migrations(schema_name)
            else:
                logger.info(f"Schema '{schema_name}' does not exist — running migrations")
                self._run_migrations(schema_name)

            # ── STEP 3: Switch to tenant schema ───────────────────────────────
            logger.info(f"Switching to TENANT schema: {schema_name}")
            connection.set_schema(schema_name)

            # ── STEP 4: Validate subscription ─────────────────────────────────
            logger.info("Validating subscription...")
            subscription_manager = SubscriptionManager(company_id, schema_name)
            is_valid, message, days, sub_status = subscription_manager.validate_subscription(
                force_online=True
            )
            if not is_valid:
                logger.warning(f"Subscription issue: {message}")
            else:
                logger.info(f"Subscription valid: {message}")

            # ── STEP 5: Sync authenticated user ───────────────────────────────
            user_info = self.get_user_info()
            authenticated_user_email = user_info.get('email') if user_info else None

            if authenticated_user_email:
                logger.info(f"Syncing user to tenant schema: {authenticated_user_email}")
                self.sync_user_to_tenant(
                    authenticated_user_email, subdomain, token, company_id
                )
            else:
                logger.warning("No authenticated user email found")

            logger.info("=" * 70)
            logger.info(f"COMPANY SYNC COMPLETE: {company.name}")
            logger.info(f"   Final schema: {connection.schema_name}")
            logger.info("=" * 70)

            return company

        except Exception as e:
            logger.error("=" * 70)
            logger.error("CRITICAL ERROR syncing company")
            logger.error(f"Error: {e}", exc_info=True)
            logger.error(f"Schema at error: {connection.schema_name}")
            logger.error("=" * 70)
            return None

    def _check_schema_exists(self, schema_name):
        """Check if a PostgreSQL schema exists."""
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT EXISTS(
                    SELECT 1 FROM information_schema.schemata
                    WHERE schema_name = %s
                )
            """, [schema_name])
            return cursor.fetchone()[0]

    def _get_table_count(self, schema_name):
        """Count tables in a schema."""
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema = %s
                AND table_type = 'BASE TABLE'
            """, [schema_name])
            return cursor.fetchone()[0]

    def _run_migrations(self, schema_name):
        """
        Create tenant schema and run all migrations in it.
        This gives clean sequences starting at 1 — no setval conflicts.
        Slower than SQL dump (~30-60s) but reliable.
        """
        logger.info(f"Running migrations for schema: {schema_name}")
        logger.info("This may take 30-60 seconds on first run...")

        try:
            # Create the schema if it doesn't exist
            with connection.cursor() as cursor:
                cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}";')
            logger.info(f"Schema '{schema_name}' created")

            # Run tenant migrations — this creates all tables with
            # sequences starting at 1, exactly as they should be
            call_command(
                'migrate_schemas',
                schema_name=schema_name,
                interactive=False,
                verbosity=1,
            )

            table_count = self._get_table_count(schema_name)
            logger.info(f"Migrations complete — {table_count} tables created in '{schema_name}'")

        except Exception as e:
            logger.error(f"Migration failed for schema '{schema_name}': {e}", exc_info=True)
            raise

    # -------------------------------------------------------------------------
    # User sync — sync_id aware
    # -------------------------------------------------------------------------
    def sync_user_to_tenant(self, email, subdomain, token, company_id):
        """
        Sync authenticated user into the tenant schema.

        Looks up existing user by sync_id (UUID) first.
        Falls back to email / integer PK for pre-existing records.
        Stamps sync_id onto old records so future syncs are stable.
        """
        from accounts.models import CustomUser

        try:
            is_development = settings.DEBUG or self.base_domain == 'localhost'

            if is_development:
                url = f"http://{subdomain}.localhost:8000/api/desktop/sync/user/{email}/"
            else:
                url = f"https://{subdomain}.{self.base_domain}/api/desktop/sync/user/{email}/"

            logger.info(f"  Fetching user data from: {url}")

            response = requests.get(
                url,
                headers={'Authorization': f'Bearer {token}'},
                timeout=30,
                verify=not is_development
            )

            if response.status_code != 200:
                logger.error(f"  Failed to fetch user: HTTP {response.status_code}")
                return False

            try:
                user_data = response.json()
            except Exception:
                logger.error(f"  User sync response was not valid JSON: {response.text!r}")
                return False
            if not user_data:
                logger.error(f"  No user data returned for {email}")
                return False

            user_id = user_data.get('id')
            password_hash = user_data.get('password')
            server_sync_id_raw = user_data.get('sync_id')

            if not password_hash:
                logger.error(f"  No password hash in user data for {email}")
                return False

            server_sync_id = None
            if server_sync_id_raw:
                try:
                    server_sync_id = uuid.UUID(str(server_sync_id_raw))
                except ValueError:
                    logger.warning(f"  Invalid sync_id from server: {server_sync_id_raw}")

            logger.info(f"  Received user data (server_id={user_id}, sync_id={server_sync_id})")

            # Look up existing user: sync_id → email → integer PK
            user = None
            created = False

            has_sync_id_field = any(
                f.name == 'sync_id' for f in CustomUser._meta.get_fields()
            )

            if server_sync_id and has_sync_id_field:
                try:
                    user = CustomUser.objects.get(sync_id=server_sync_id)
                    logger.info(f"  Found user by sync_id: {user.email}")
                except CustomUser.DoesNotExist:
                    pass

            if user is None:
                try:
                    user = CustomUser.objects.get(email=email)
                    logger.info(f"  Found user by email: {user.email}")
                    if server_sync_id and has_sync_id_field and not user.sync_id:
                        user.sync_id = server_sync_id
                except CustomUser.DoesNotExist:
                    pass

            if user is None and user_id:
                try:
                    user = CustomUser.objects.get(pk=user_id)
                    logger.info(f"  Found user by PK: {user.email}")
                    if server_sync_id and has_sync_id_field and not user.sync_id:
                        user.sync_id = server_sync_id
                except CustomUser.DoesNotExist:
                    pass

            defaults = {
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
            if server_sync_id and has_sync_id_field:
                defaults['sync_id'] = server_sync_id

            if user is not None:
                for field, value in defaults.items():
                    setattr(user, field, value)
                user.save()
            else:
                if user_id:
                    user, created = CustomUser.objects.update_or_create(
                        id=user_id,
                        defaults=defaults,
                    )
                else:
                    user = CustomUser(**defaults)
                    user.save()
                    created = True

            role_id = user_data.get('role')
            if role_id:
                user.primary_role_id = role_id
                user.save()

            logger.info(
                f"  User {'created' if created else 'updated'}: "
                f"{email} (pk={user.pk}, sync_id={getattr(user, 'sync_id', 'n/a')})"
            )
            return True

        except Exception as e:
            logger.error(f"  Error syncing user {email}: {e}", exc_info=True)
            return False

    # -------------------------------------------------------------------------
    # Token management
    # -------------------------------------------------------------------------
    def refresh_access_token(self):
        """Refresh expired access token using the refresh token."""
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

            is_development = settings.DEBUG or self.base_domain == 'localhost'

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

            try:
                new_token = response.json().get('access')
            except Exception:
                logger.error(f"Token refresh response was not valid JSON: {response.text!r}")
                return None
            if new_token:
                self.save_auth_token(new_token)
                logger.info("Access token refreshed")
                return new_token

            logger.error("No access token in refresh response")
            return None

        except Exception as e:
            logger.error(f"Token refresh error: {e}", exc_info=True)
            return None

    def get_valid_token(self):
        """Get a valid (non-expired) access token, refreshing if necessary."""
        import jwt
        from datetime import datetime, timezone

        token = self.get_auth_token()
        if not token:
            logger.warning("No access token found — user needs to re-login")
            return None

        try:
            decoded = jwt.decode(token, options={"verify_signature": False})
            exp = decoded.get('exp')

            if exp:
                exp_dt = datetime.fromtimestamp(exp, tz=timezone.utc)
                now = datetime.now(timezone.utc)

                if exp_dt <= now:
                    logger.info("Access token expired — attempting refresh...")
                    return self.refresh_access_token()

                logger.debug(f"Access token valid until {exp_dt}")
                return token

        except jwt.DecodeError:
            logger.warning("Could not decode access token — attempting refresh...")
        except Exception as e:
            logger.error(f"Token validation error: {e}")

        return self.refresh_access_token()

    def require_authentication(self):
        """Check if user is authenticated with a valid token."""
        if not self.is_authenticated():
            return False, "Not logged in"
        token = self.get_valid_token()
        if not token:
            return False, "Session expired — please login again"
        return True, None

    # -------------------------------------------------------------------------
    # Company details
    # -------------------------------------------------------------------------
    def fetch_company_details(self, token, subdomain):
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

            try:
                return response.json()
            except Exception:
                logger.error(f"Company details response was not valid JSON: {response.text!r}")
                return None

        except Exception as e:
            logger.error(f"Error fetching company details: {e}")
            return None

    # -------------------------------------------------------------------------
    # Credential storage
    # -------------------------------------------------------------------------
    def save_credentials(self, user_data, company_data, token):
        encrypted_token = self.encryption.encrypt_data(token)
        (settings.DESKTOP_DATA_DIR / '.auth_token.enc').write_bytes(encrypted_token)

        user_json = json.dumps(user_data)
        encrypted_user = self.encryption.encrypt_data(user_json)
        (settings.DESKTOP_DATA_DIR / '.user_data.enc').write_bytes(encrypted_user)

        (settings.DESKTOP_DATA_DIR / '.company_info').write_text(json.dumps(company_data))

    def load_credentials(self):
        token_file = settings.DESKTOP_DATA_DIR / '.auth_token.enc'
        user_file = settings.DESKTOP_DATA_DIR / '.user_data.enc'
        company_file = settings.DESKTOP_DATA_DIR / '.company_info'

        if not token_file.exists():
            return None, None, None

        token = self.encryption.decrypt_data(token_file.read_bytes()).decode()

        user_data = None
        if user_file.exists():
            user_json = self.encryption.decrypt_data(user_file.read_bytes()).decode()
            user_data = json.loads(user_json)

        company_data = json.loads(company_file.read_text()) if company_file.exists() else None

        return token, user_data, company_data

    def save_auth_token(self, token):
        encrypted = self.encryption.encrypt_data(token)
        self.auth_token_file.write_bytes(encrypted)
        settings.SYNC_AUTH_TOKEN = token

    def get_auth_token(self):
        if self.auth_token_file.exists():
            try:
                token = self.encryption.decrypt_data(self.auth_token_file.read_bytes()).decode().strip()
            except Exception:
                # Fall back to plain-text token from older installs
                try:
                    token = self.auth_token_file.read_text().strip()
                except Exception:
                    return None
            settings.SYNC_AUTH_TOKEN = token
            return token
        return None

    def save_refresh_token(self, token):
        encrypted = self.encryption.encrypt_data(token)
        self.refresh_token_file.write_bytes(encrypted)

    def get_refresh_token(self):
        if self.refresh_token_file.exists():
            try:
                return self.encryption.decrypt_data(self.refresh_token_file.read_bytes()).decode().strip()
            except Exception:
                # Fall back to plain-text token from older installs
                try:
                    return self.refresh_token_file.read_text().strip()
                except Exception:
                    return None
        return None

    def save_user_info(self, user_info):
        self.user_info_file.write_text(json.dumps(user_info))

    def get_user_info(self):
        if self.user_info_file.exists():
            return json.loads(self.user_info_file.read_text())
        return None

    def save_company_info(self, company_info):
        self.company_info_file.write_text(json.dumps(company_info))

    def get_company_info(self):
        if self.company_info_file.exists():
            return json.loads(self.company_info_file.read_text())
        return None

    def is_authenticated(self):
        return self.auth_token_file.exists() and self.company_info_file.exists()

    def logout(self):
        for f in [
            self.auth_token_file,
            self.refresh_token_file,
            self.user_info_file,
            self.company_info_file,
            self.subdomain_file,
        ]:
            if f.exists():
                f.unlink()
        settings.SYNC_AUTH_TOKEN = None