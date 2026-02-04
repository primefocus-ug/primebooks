# primebooks/auth.py - FIXED VERSION
"""
Desktop authentication with PROPER tenant migration
✅ Runs migrations in tenant schema (pada)
✅ Downloads data from server
✅ Creates user in tenant schema
"""
import requests
import logging
from django.conf import settings
from django.db import connection
from django.core.management import call_command
from company.models import Company, Domain
from django_tenants.utils import schema_context
import json
from primebooks.security.encryption import get_encryption_manager
from pathlib import Path

logger = logging.getLogger(__name__)


class DesktopAuthManager:
    """Handles authentication and initial company sync"""

    def __init__(self):
        # Get server URL with fallback
        self.server_url = getattr(settings, 'SYNC_SERVER_URL', None)
        self.base_domain = getattr(settings, 'BASE_DOMAIN', 'localhost')
        self.auth_token_file = settings.DESKTOP_DATA_DIR / '.auth_token'
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
            token = data.get('token')
            self.save_auth_token(token)

            user_info = data.get('user', {})
            self.save_user_info(user_info)

            company = self.fetch_company_details(token, subdomain)
            if not company:
                return False, {'error': 'Could not fetch company details'}

            self.save_company_info(company)

            # ✅ CRITICAL: Sync company and run tenant migrations
            synced_company = self.sync_company_from_server(company, token, subdomain)
            if not synced_company:
                return False, {'error': 'Failed to sync company data'}

            return True, {
                'token': token,
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

    def sync_company_from_server(self, company_data, token, subdomain):
        """
        Download and sync company with PostgreSQL multi-tenancy
        ✅ FIXED: Runs migrations in TENANT schema (pada)
        ✅ Creates tenant tables
        ✅ Syncs user data
        """
        from django.utils.text import slugify

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

            # ─────────────────────────────────────────────
            # 1️⃣ Create/update company in PUBLIC schema
            # ─────────────────────────────────────────────
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
                    'slug': slug,
                    'is_trial': company_data.get('is_trial', False),
                    'status': company_data.get('status', 'ACTIVE'),
                }
            )

            logger.info(f"✅ Company {'created' if created else 'updated'}: {company.name}")

            # ─────────────────────────────────────────────
            # 2️⃣ Create/update domain
            # ─────────────────────────────────────────────
            domain_name = f"{subdomain}.localhost"  # For desktop, use localhost
            Domain.objects.update_or_create(
                domain=domain_name,
                defaults={'tenant': company, 'is_primary': True}
            )

            logger.info(f"✅ Domain configured: {domain_name}")

            # ─────────────────────────────────────────────
            # 3️⃣ Create PostgreSQL schema
            # ─────────────────────────────────────────────
            with connection.cursor() as cursor:
                cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"')

            logger.info(f"✅ Schema created: {schema_name}")

            # ─────────────────────────────────────────────
            # 4️⃣ RUN MIGRATIONS FOR TENANT SCHEMA ✅✅✅
            # ─────────────────────────────────────────────
            logger.info(f"🔄 Running migrations for tenant schema: {schema_name}")
            logger.info(f"   This will create all tables in [standard:{schema_name}]")

            try:
                # Run migrations specifically for this tenant
                call_command(
                    'migrate_schemas',
                    schema_name=schema_name,
                    interactive=False,
                    verbosity=2  # Show which migrations are running
                )

                logger.info(f"✅ Migrations complete for schema: {schema_name}")

            except Exception as e:
                logger.error(f"❌ Migration failed: {e}", exc_info=True)
                raise

            # ─────────────────────────────────────────────
            # 5️⃣ Sync authenticated user to tenant schema
            # ─────────────────────────────────────────────
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

            # ✅ Create/update user in TENANT schema
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
        if self.user_info_file.exists():
            self.user_info_file.unlink()
        if self.company_info_file.exists():
            self.company_info_file.unlink()
        settings.SYNC_AUTH_TOKEN = None