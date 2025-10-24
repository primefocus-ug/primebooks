from django.core.management.base import BaseCommand
from django_tenants.utils import schema_context
from company.models import Company
from efris.models import EFRISConfiguration
from efris.services import EnhancedEFRISAPIClient
from django.core.management.base import BaseCommand, CommandError
import os
import base64
import hashlib
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from django.utils import timezone


class Command(BaseCommand):
    help = 'Sync EFRIS system dictionaries for a company'

    def add_arguments(self, parser):
        parser.add_argument('--company-id', type=str, required=True)
        parser.add_argument('--force', action='store_true', help='Force sync even if recently updated')
        parser.add_argument('--private-key-path', type=str, help='Path to private key file')
        parser.add_argument('--public-cert-path', type=str, help='Path to public certificate file')
        parser.add_argument('--public-key-path', type=str, help='Path to public key file (alternative to certificate)')
        parser.add_argument('--key-password', type=str, help='Password for encrypted private key')
        parser.add_argument('--validate-only', action='store_true', help='Only validate configuration, do not sync')
        parser.add_argument('--inspect-keys', action='store_true', help='Inspect and debug key formats')

    def handle(self, *args, **options):
        company_id = options['company_id']
        force = options['force']
        private_key_path = options.get('private_key_path')
        public_cert_path = options.get('public_cert_path')
        public_key_path = options.get('public_key_path')
        key_password = options.get('key_password')
        validate_only = options['validate_only']
        inspect_keys = options['inspect_keys']
        show_config = options['show_config']

        try:
            company = Company.objects.get(company_id=company_id)
            schema_name = company.schema_name

            self.stdout.write(f"Processing EFRIS configuration for: {company.display_name} (schema: {schema_name})")

            with schema_context(schema_name):
                # Get or create EFRIS configuration
                config, created = EFRISConfiguration.objects.get_or_create(company=company)

                if created:
                    self.stdout.write("Created new EFRIS configuration")

                # Show configuration summary if requested
                if show_config:
                    self.display_configuration_summary(config)
                    if not (private_key_path or public_cert_path or public_key_path or validate_only or inspect_keys):
                        return

                # Update certificate data if files are provided
                if private_key_path or public_cert_path or public_key_path:
                    self.update_key_data(config, private_key_path, public_cert_path, public_key_path, key_password)

                # Inspect keys if requested
                if inspect_keys:
                    self.stdout.write(self.style.HTTP_INFO("=== KEY INSPECTION ==="))
                    config.inspect_all_keys()
                    if validate_only or not force:
                        return

                # Validate configuration before proceeding
                validation_errors = self.validate_efris_config(config, company)
                if validation_errors:
                    self.stdout.write(
                        self.style.ERROR(f"Configuration validation failed:")
                    )
                    for error in validation_errors:
                        self.stdout.write(self.style.ERROR(f"  - {error}"))
                    return

                if validate_only:
                    self.stdout.write(self.style.SUCCESS("✓ Configuration validation successful"))
                    self.display_configuration_summary(config)
                    return

                # Now try to sync dictionaries
                try:
                    self.stdout.write("Initializing EFRIS API client...")

                    with EnhancedEFRISAPIClient(company) as client:
                        # First, let's validate the client configuration
                        is_config_valid, config_errors = client.validate_configuration()
                        if not is_config_valid:
                            self.stdout.write(self.style.ERROR("✗ Client configuration validation failed:"))
                            for error in config_errors:
                                self.stdout.write(self.style.ERROR(f"  - {error}"))
                            return

                        self.stdout.write("✓ Client configuration is valid")

                        # STEP 1: Test basic connectivity (T101 - no authentication required)
                        self.stdout.write("Step 1: Testing server connectivity (T101)...")
                        time_response = client.get_server_time()
                        if time_response.success:
                            if time_response.data:
                                server_time = time_response.data.get('serverTime', 'Unknown')
                                self.stdout.write(f"✓ Server connectivity OK (Server time: {server_time})")
                            else:
                                self.stdout.write("✓ Server connectivity OK")
                        else:
                            self.stdout.write(
                                self.style.WARNING(f"⚠ Server time check failed: {time_response.error_message}"))
                            # Continue anyway as this might not be critical

                        # STEP 2: Initialize/Register device (T102)
                        self.stdout.write("Step 2: Initializing device registration (T102)...")

                        # Always attempt device initialization for EFRIS
                        # This is required before T104 (AES key request)
                        self.stdout.write("Attempting device initialization...")
                        init_response = client.client_initialization()
                        if not init_response.success:
                            self.stdout.write(
                                self.style.ERROR(f"✗ Device initialization failed: {init_response.error_message}")
                            )

                            # Provide specific guidance for initialization failures
                            if "already registered" in str(init_response.error_message).lower():
                                self.stdout.write(self.style.WARNING(
                                    "Hint: Device may already be registered. Continuing to next step."))
                            elif "certificate" in str(init_response.error_message).lower():
                                self.stdout.write(self.style.WARNING(
                                    "Hint: Check certificate configuration and validity."))
                            else:
                                return
                        else:
                            self.stdout.write("✓ Device initialization successful")
                            # Update config to mark as initialized
                            try:
                                config.is_initialized = True
                                config.save()
                            except Exception as e:
                                self.stdout.write(self.style.WARNING(f"Could not update config: {e}"))

                        # STEP 3: Get symmetric AES key (T104) - BEFORE AUTHENTICATION
                        self.stdout.write("Step 3: Requesting symmetric AES key (T104)...")
                        sym_response = client.get_symmetric_key()
                        if not sym_response.success:
                            self.stdout.write(
                                self.style.ERROR(f"✗ Failed to get symmetric key: {sym_response.error_message}"))

                            # Additional error handling for AES key issues
                            if "AppID error" in str(sym_response.error_message):
                                self.stdout.write(self.style.WARNING(
                                    "Hint: AppID error - check if device is properly registered (T102)."))
                            elif "Device not found" in str(sym_response.error_message):
                                self.stdout.write(self.style.WARNING(
                                    "Hint: Device not found - may need to reinitialize device registration."))

                            return

                        self.stdout.write("✓ Symmetric AES key obtained successfully")

                        # Verify AES key is valid
                        if not client.security_manager.is_aes_key_valid():
                            self.stdout.write(self.style.ERROR("✗ AES key validation failed"))
                            return
                        else:
                            self.stdout.write("✓ AES key validation successful")

                        # STEP 4: Authenticate/Login (T103) - USING THE AES KEY
                        self.stdout.write("Step 4: Authenticating with EFRIS (T103)...")

                        # ADDED: T103 login with error handling for device key expiration
                        try:
                            login_response = client.login()
                            if login_response.success:
                                self.stdout.write("✓ Login successful")
                            else:
                                if login_response.error_code == '402':  # Device key expired
                                    self.stdout.write("⚠ Device key expired, attempting renewal...")
                                    renewal_response = client.handle_key_expiration()
                                    if renewal_response.success:
                                        self.stdout.write("✓ Device key renewed successfully")

                                        # Retry login after renewal
                                        login_response = client.login()
                                        if login_response.success:
                                            self.stdout.write("✓ Login successful after key renewal")
                                        else:
                                            raise CommandError(
                                                f"Login failed after key renewal: {login_response.error_message}")
                                    else:
                                        raise CommandError(
                                            f"Failed to renew expired device key: {renewal_response.error_message}")
                                else:
                                    raise CommandError(f"Login failed: {login_response.error_message}")

                        except Exception as e:
                            self.stdout.write(f"✗ Authentication error: {e}")
                            raise CommandError(str(e))

                        # STEP 5: Now attempt dictionary sync
                        self.stdout.write("Step 5: Fetching system dictionaries...")
                        response = client.get_system_dictionary()

                        if response.success:
                            self.stdout.write(
                                self.style.SUCCESS("✓ System dictionaries synced successfully")
                            )

                            # Show sync details if available
                            if response.data:
                                self.show_sync_details(response.data)

                            # Update last sync time
                            config.last_dictionary_sync = timezone.now()
                            config.save()

                            self.stdout.write(f"Updated last sync time: {config.last_dictionary_sync}")

                        else:
                            self.stdout.write(
                                self.style.ERROR(f"✗ Dictionary sync failed: {response.error_message}")
                            )

                            # Provide specific guidance based on error code
                            if response.error_code:
                                self.stdout.write(f"Error code: {response.error_code}")

                            # Log the full error for debugging
                            if response.metadata:
                                self.stdout.write("Debug info:")
                                for key, value in response.metadata.items():
                                    self.stdout.write(f"  {key}: {value}")

                except Exception as api_error:
                    self.stdout.write(
                        self.style.ERROR(f"✗ API client error: {str(api_error)}")
                    )
                    # Print more detailed error for debugging
                    import traceback
                    self.stdout.write("Full error traceback:")
                    self.stdout.write(traceback.format_exc())

        except Company.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f"Company with ID '{company_id}' not found")
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Command failed: {str(e)}")
            )

    def update_key_data(self, config, private_key_path, public_cert_path, public_key_path, key_password):
        """Update key and certificate data from file paths"""
        try:
            # Handle private key
            if private_key_path and os.path.exists(private_key_path):
                with open(private_key_path, 'r') as f:
                    private_key_content = f.read().strip()
                    config.private_key = private_key_content
                    if key_password:
                        config.key_password = key_password
                    self.stdout.write(f"Updated private key from {private_key_path}")
                    self.stdout.write(f"Private key type: {config.private_key_type}")

            # Handle public certificate or public key
            public_file_path = public_cert_path or public_key_path
            if public_file_path and os.path.exists(public_file_path):
                with open(public_file_path, 'r') as f:
                    public_content = f.read().strip()
                    config.public_certificate = public_content

                    self.stdout.write(f"Updated public certificate/key from {public_file_path}")

                    # Try to extract additional information
                    try:
                        # Determine what type of data this is
                        if public_content.startswith('-----BEGIN CERTIFICATE-----'):
                            self._process_certificate(config, public_content)
                        elif public_content.startswith('-----BEGIN PUBLIC KEY-----') or public_content.startswith(
                                '-----BEGIN RSA PUBLIC KEY-----'):
                            self._process_public_key(config, public_content)
                        else:
                            # Try to determine if it's base64 encoded certificate or public key
                            self._process_base64_data(config, public_content)

                        self.stdout.write(f"Certificate/Key type: {config.certificate_type}")
                        if config.certificate_fingerprint:
                            self.stdout.write(f"Fingerprint: {config.certificate_fingerprint}")
                        if config.certificate_expires_at:
                            self.stdout.write(f"Expires: {config.certificate_expires_at}")

                    except Exception as process_error:
                        self.stdout.write(
                            self.style.WARNING(f"Could not process certificate/key details: {process_error}")
                        )

            # Save the configuration
            config.save()
            self.stdout.write("Key data updated successfully")

            # Validate the updated configuration
            try:
                config.clean()  # This will run all validations
                self.stdout.write(self.style.SUCCESS("✓ Key validation successful"))

                # Also run API client validation
                validation_errors = self.validate_efris_config(config, company)
                if validation_errors:
                    self.stdout.write(self.style.WARNING("⚠ API client validation warnings:"))
                    for error in validation_errors:
                        self.stdout.write(self.style.WARNING(f"  - {error}"))
                else:
                    self.stdout.write(self.style.SUCCESS("✓ API client validation successful"))

            except Exception as validation_error:
                self.stdout.write(
                    self.style.ERROR(f"✗ Key validation failed: {validation_error}")
                )

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Error updating key data: {str(e)}")
            )

    def _process_certificate(self, config, cert_content):
        """Process X.509 certificate"""
        cert_data = cert_content.encode('utf-8')
        certificate = x509.load_pem_x509_certificate(cert_data)
        cert_der = certificate.public_bytes(encoding=x509.Encoding.DER)

        # Generate fingerprint
        fingerprint = hashlib.sha256(cert_der).hexdigest().upper()
        config.certificate_fingerprint = fingerprint

        # Set expiry date
        config.certificate_expires_at = certificate.not_valid_after.replace(tzinfo=timezone.utc)

        self.stdout.write(f"Processed X.509 certificate")
        self.stdout.write(f"Subject: {certificate.subject.rfc4514_string()}")
        self.stdout.write(f"Issuer: {certificate.issuer.rfc4514_string()}")
        self.stdout.write(f"Valid from: {certificate.not_valid_before}")
        self.stdout.write(f"Valid to: {certificate.not_valid_after}")

    def _process_public_key(self, config, key_content):
        """Process public key"""
        public_key = serialization.load_pem_public_key(key_content.encode('utf-8'))

        # Generate fingerprint
        public_key_der = public_key.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        fingerprint = hashlib.sha256(public_key_der).hexdigest().upper()
        config.certificate_fingerprint = fingerprint
        config.certificate_expires_at = None  # Public keys don't have expiration

        self.stdout.write(f"Processed public key")
        self.stdout.write(f"Key type: {type(public_key).__name__}")
        self.stdout.write(f"Key size: {public_key.key_size} bits")

    def _process_base64_data(self, config, data_content):
        """Process base64 encoded certificate or public key"""
        # Clean and decode
        clean_b64 = ''.join(data_content.split())
        missing_padding = len(clean_b64) % 4
        if missing_padding:
            clean_b64 += '=' * (4 - missing_padding)

        decoded_data = base64.b64decode(clean_b64)

        # Try as certificate first
        try:
            certificate = x509.load_der_x509_certificate(decoded_data)
            cert_der = certificate.public_bytes(encoding=x509.Encoding.DER)

            fingerprint = hashlib.sha256(cert_der).hexdigest().upper()
            config.certificate_fingerprint = fingerprint
            config.certificate_expires_at = certificate.not_valid_after.replace(tzinfo=timezone.utc)

            self.stdout.write(f"Processed base64-encoded X.509 certificate")

        except Exception:
            # Try as public key
            try:
                public_key = serialization.load_der_public_key(decoded_data)

                fingerprint = hashlib.sha256(decoded_data).hexdigest().upper()
                config.certificate_fingerprint = fingerprint
                config.certificate_expires_at = None

                self.stdout.write(f"Processed base64-encoded public key")
                self.stdout.write(f"Key type: {type(public_key).__name__}")
                self.stdout.write(f"Key size: {public_key.key_size} bits")

            except Exception as e:
                raise Exception(f"Could not process as certificate or public key: {e}")

    # Add this method to your Command class in efris_sync_dictionaries.py:

    def show_sync_details(self, response_data):
        """Display sync details from EFRIS response"""
        if not response_data or not isinstance(response_data, dict):
            self.stdout.write("No sync details available")
            return

        self.stdout.write("Dictionary sync details:")

        # Show basic info about what was synced
        data_keys = list(response_data.keys())
        self.stdout.write(f"  Response contains {len(data_keys)} data sections")

        # Show some key sections if they exist
        for key in ['currencyType', 'payWay', 'sector', 'countryCode']:
            if key in response_data:
                data = response_data[key]
                if isinstance(data, list):
                    self.stdout.write(f"  {key}: {len(data)} items")
                else:
                    self.stdout.write(f"  {key}: Available")

        # Show total data size
        import json
        try:
            data_size = len(json.dumps(response_data))
            self.stdout.write(f"  Total data size: {data_size:,} bytes")
        except:
            pass
    def validate_efris_config(self, config, company):
        """Validate EFRIS configuration using the API client validation"""
        try:
            # Pass the company, not the config
            with EnhancedEFRISAPIClient(company) as client:
                is_valid, errors = client.validate_configuration()
                return errors if not is_valid else []
        except Exception as e:
            return [f"API client initialization failed: {str(e)}"]

    def setup_default_certificate_paths(self, company_id):
        """Get default certificate paths based on company structure"""
        base_path = "/home/nashvybzes/prime_tenant/znash/efris_keys"

        return {
            'private_key': os.path.join(base_path, 'private_key.pem'),
            'public_cert': os.path.join(base_path, 'certificate.pem'),
            'public_key': os.path.join(base_path, 'public_key.pem'),
        }

    def display_configuration_summary(self, config):
        """Display a summary of the current configuration"""
        self.stdout.write(self.style.HTTP_INFO("=== EFRIS Configuration Summary ==="))

        self.stdout.write(f"Environment: {config.get_environment_display()}")
        self.stdout.write(f"Mode: {config.get_mode_display()}")
        self.stdout.write(f"API URL: {config.api_url}")

        # Key status
        self.stdout.write(f"Private Key: {'✓ Present' if config.private_key else '✗ Missing'}")
        if config.private_key:
            self.stdout.write(f"  Type: {config.private_key_type}")
            if config.private_key_fingerprint:
                self.stdout.write(f"  Fingerprint: {config.private_key_fingerprint[:16]}...")

        self.stdout.write(f"Public Certificate/Key: {'✓ Present' if config.public_certificate else '✗ Missing'}")
        if config.public_certificate:
            self.stdout.write(f"  Type: {config.certificate_type}")
            if config.certificate_fingerprint:
                self.stdout.write(f"  Fingerprint: {config.certificate_fingerprint[:16]}...")
            if config.certificate_expires_at:
                self.stdout.write(f"  Expires: {config.certificate_expires_at}")
                days_left = config.days_until_certificate_expires
                if days_left is not None:
                    if days_left > 0:
                        self.stdout.write(f"  Days until expiry: {days_left}")
                    else:
                        self.stdout.write(f"  ✗ Expired {abs(days_left)} days ago")
            else:
                self.stdout.write(f"  Expiry: N/A (Public Key)")

        # Validation status
        self.stdout.write(f"Certificate Valid: {'✓ Yes' if config.is_certificate_valid else '✗ No'}")
        self.stdout.write(f"Configuration Active: {'✓ Yes' if config.is_active else '✗ No'}")
        self.stdout.write(f"Initialized: {'✓ Yes' if config.is_initialized else '✗ No'}")

        # Connection status
        if config.last_test_connection:
            status = "✓ Success" if config.test_connection_success else "✗ Failed"
            self.stdout.write(f"Last Connection Test: {status} ({config.last_test_connection})")

        if config.last_login:
            self.stdout.write(f"Last Login: {config.last_login}")

        # Sync status
        if config.last_dictionary_sync:
            self.stdout.write(f"Last Dictionary Sync: {config.last_dictionary_sync}")

        self.stdout.write(f"Auto Sync: {'✓ Enabled' if config.auto_sync_enabled else '✗ Disabled'}")
        self.stdout.write(f"Auto Fiscalize: {'✓ Enabled' if config.auto_fiscalize else '✗ Disabled'}")

    def add_arguments(self, parser):
        parser.add_argument('--company-id', type=str, required=True)
        parser.add_argument('--force', action='store_true', help='Force sync even if recently updated')
        parser.add_argument('--private-key-path', type=str, help='Path to private key file')
        parser.add_argument('--public-cert-path', type=str, help='Path to public certificate file')
        parser.add_argument('--public-key-path', type=str, help='Path to public key file (alternative to certificate)')
        parser.add_argument('--key-password', type=str, help='Password for encrypted private key')
        parser.add_argument('--validate-only', action='store_true', help='Only validate configuration, do not sync')
        parser.add_argument('--inspect-keys', action='store_true', help='Inspect and debug key formats')
        parser.add_argument('--show-config', action='store_true', help='Display current configuration summary')

    def handle(self, *args, **options):
        company_id = options['company_id']
        force = options['force']
        private_key_path = options.get('private_key_path')
        public_cert_path = options.get('public_cert_path')
        public_key_path = options.get('public_key_path')
        key_password = options.get('key_password')
        validate_only = options['validate_only']
        inspect_keys = options['inspect_keys']
        show_config = options['show_config']

        try:
            company = Company.objects.get(company_id=company_id)
            schema_name = company.schema_name

            self.stdout.write(f"Processing EFRIS configuration for: {company.display_name} (schema: {schema_name})")

            with schema_context(schema_name):
                # Get or create EFRIS configuration
                config, created = EFRISConfiguration.objects.get_or_create(company=company)

                if created:
                    self.stdout.write("Created new EFRIS configuration")

                # Show configuration summary if requested
                if show_config:
                    self.display_configuration_summary(config)
                    if not (private_key_path or public_cert_path or public_key_path or validate_only or inspect_keys):
                        return

                # Update certificate data if files are provided
                if private_key_path or public_cert_path or public_key_path:
                    self.update_key_data(config, private_key_path, public_cert_path, public_key_path, key_password)

                # Inspect keys if requested
                if inspect_keys:
                    self.stdout.write(self.style.HTTP_INFO("=== KEY INSPECTION ==="))
                    config.inspect_all_keys()
                    if validate_only or not force:
                        return

                # Validate configuration before proceeding
                validation_errors = self.validate_efris_config(config, company)
                if validation_errors:
                    self.stdout.write(
                        self.style.ERROR(f"Configuration validation failed:")
                    )
                    for error in validation_errors:
                        self.stdout.write(self.style.ERROR(f"  - {error}"))
                    return

                if validate_only:
                    self.stdout.write(self.style.SUCCESS("✓ Configuration validation successful"))
                    self.display_configuration_summary(config)
                    return

                # Now try to sync dictionaries
                try:
                    self.stdout.write("Initializing EFRIS API client...")

                    with EnhancedEFRISAPIClient(company) as client:
                        # First, let's validate the client configuration
                        is_config_valid, config_errors = client.validate_configuration()
                        if not is_config_valid:
                            self.stdout.write(self.style.ERROR("✗ Client configuration validation failed:"))
                            for error in config_errors:
                                self.stdout.write(self.style.ERROR(f"  - {error}"))
                            return

                        self.stdout.write("✓ Client configuration is valid")

                        # STEP 1: Test basic connectivity (T101 - no authentication required)
                        self.stdout.write("Step 1: Testing server connectivity (T101)...")
                        time_response = client.get_server_time()
                        if time_response.success:
                            if time_response.data:
                                server_time = time_response.data.get('serverTime', 'Unknown')
                                self.stdout.write(f"✓ Server connectivity OK (Server time: {server_time})")
                            else:
                                self.stdout.write("✓ Server connectivity OK")
                        else:
                            self.stdout.write(
                                self.style.WARNING(f"⚠ Server time check failed: {time_response.error_message}"))
                            # Continue anyway as this might not be critical

                        # STEP 2: Initialize/Register device (T102)
                        self.stdout.write("Step 2: Initializing device registration (T102)...")

                        # Always attempt device initialization for EFRIS
                        # This is required before T104 (AES key request)
                        self.stdout.write("Attempting device initialization...")
                        init_response = client.client_initialization()
                        if not init_response.success:
                            self.stdout.write(
                                self.style.ERROR(f"✗ Device initialization failed: {init_response.error_message}")
                            )

                            # Provide specific guidance for initialization failures
                            if "already registered" in str(init_response.error_message).lower():
                                self.stdout.write(self.style.WARNING(
                                    "Hint: Device may already be registered. Continuing to next step."))
                            elif "certificate" in str(init_response.error_message).lower():
                                self.stdout.write(self.style.WARNING(
                                    "Hint: Check certificate configuration and validity."))
                            else:
                                return
                        else:
                            self.stdout.write("✓ Device initialization successful")
                            # Update config to mark as initialized
                            try:
                                config.is_initialized = True
                                config.save()
                            except Exception as e:
                                self.stdout.write(self.style.WARNING(f"Could not update config: {e}"))

                        # STEP 3: Get symmetric AES key (T104) - BEFORE AUTHENTICATION
                        self.stdout.write("Step 3: Requesting symmetric AES key (T104)...")
                        sym_response = client.get_symmetric_key()
                        if not sym_response.success:
                            self.stdout.write(
                                self.style.ERROR(f"✗ Failed to get symmetric key: {sym_response.error_message}"))

                            # Additional error handling for AES key issues
                            if "AppID error" in str(sym_response.error_message):
                                self.stdout.write(self.style.WARNING(
                                    "Hint: AppID error - check if device is properly registered (T102)."))
                            elif "Device not found" in str(sym_response.error_message):
                                self.stdout.write(self.style.WARNING(
                                    "Hint: Device not found - may need to reinitialize device registration."))

                            return

                        self.stdout.write("✓ Symmetric AES key obtained successfully")

                        # Verify AES key is valid
                        if not client.security_manager.is_aes_key_valid():
                            self.stdout.write(self.style.ERROR("✗ AES key validation failed"))
                            return
                        else:
                            self.stdout.write("✓ AES key validation successful")

                        # STEP 4: Authenticate/Login (T103) - USING THE AES KEY
                        self.stdout.write("Step 4: Authenticating with EFRIS (T103)...")
                        auth_response = client.ensure_authenticated()
                        if not auth_response.success:
                            self.stdout.write(
                                self.style.ERROR(f"✗ Authentication failed: {auth_response.error_message}")
                            )

                            # Provide more specific guidance based on error
                            if "Device key expired" in str(auth_response.error_message):
                                self.stdout.write(self.style.WARNING(
                                    "Hint: Device key expired. Try reinitializing the device or check registration"))
                            elif "certificate" in str(auth_response.error_message).lower():
                                self.stdout.write(
                                    self.style.WARNING("Hint: Verify your certificate/private key configuration"))
                            elif "connection" in str(auth_response.error_message).lower():
                                self.stdout.write(
                                    self.style.WARNING("Hint: Check network connectivity to EFRIS servers"))
                            elif "encryption" in str(auth_response.error_message).lower():
                                self.stdout.write(
                                    self.style.WARNING("Hint: Encryption error - AES key might be invalid or expired"))

                            return

                        self.stdout.write("✓ Authentication successful")

                        # STEP 5: Now attempt dictionary sync
                        self.stdout.write("Step 5: Fetching system dictionaries...")
                        response = client.get_system_dictionary()

                        if response.success:
                            self.stdout.write(
                                self.style.SUCCESS("✓ System dictionaries synced successfully")
                            )

                            # Show sync details if available
                            if response.data:
                                self.show_sync_details(response.data)

                            # Update last sync time
                            config.last_dictionary_sync = timezone.now()
                            config.save()

                            self.stdout.write(f"Updated last sync time: {config.last_dictionary_sync}")

                        else:
                            self.stdout.write(
                                self.style.ERROR(f"✗ Dictionary sync failed: {response.error_message}")
                            )

                            # Provide specific guidance based on error code
                            if response.error_code:
                                self.stdout.write(f"Error code: {response.error_code}")

                            # Log the full error for debugging
                            if response.metadata:
                                self.stdout.write("Debug info:")
                                for key, value in response.metadata.items():
                                    self.stdout.write(f"  {key}: {value}")

                except Exception as api_error:
                    self.stdout.write(
                        self.style.ERROR(f"✗ API client error: {str(api_error)}")
                    )
                    # Print more detailed error for debugging
                    import traceback
                    self.stdout.write("Full error traceback:")
                    self.stdout.write(traceback.format_exc())

        except Company.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f"Company with ID '{company_id}' not found")
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Command failed: {str(e)}")
            )