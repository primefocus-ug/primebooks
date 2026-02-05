from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography import x509
import base64
import hashlib
import logging

User = get_user_model()
logger = logging.getLogger(__name__)


class EFRISConfiguration(models.Model):
    """Global EFRIS configuration for the company"""

    ENVIRONMENT_CHOICES = [
        ('sandbox', 'Sandbox/Testing'),
        ('production', 'Production'),
    ]

    MODE_CHOICES = [
        ('online', 'Online Mode'),
        ('offline', 'Offline Mode'),
    ]

    company = models.OneToOneField(
        'company.Company',
        on_delete=models.CASCADE,
        related_name='efris_config'
    )

    # API Configuration
    environment = models.CharField(
        max_length=20,
        choices=ENVIRONMENT_CHOICES,
        default='sandbox'
    )
    mode = models.CharField(
        max_length=10,
        choices=MODE_CHOICES,
        default='online'
    )
    api_base_url = models.URLField(
        blank=True,
        help_text=_("Will use default URLs if empty")
    )

    # Digital Keys and Certificates
    private_key = models.TextField(
        blank=True,
        help_text=_("RSA Private Key (PEM format or PKCS#12 format, base64 encoded)")
    )
    public_certificate = models.TextField(
        blank=True,
        help_text=_("X.509 Public Certificate or Public Key (PEM or base64 encoded)")
    )
    key_password = models.CharField(
        max_length=255,
        blank=True,
        help_text=_("Password for encrypted private key or PKCS#12 file")
    )

    certificate_fingerprint = models.CharField(max_length=128, blank=True)
    certificate_expires_at = models.DateTimeField(null=True, blank=True)
    private_key_fingerprint = models.CharField(max_length=128, blank=True)

    # Device Information
    device_number = models.CharField(max_length=50, blank=True)
    device_mac = models.CharField(max_length=17, default='FFFFFFFFFFFF')
    app_id = models.CharField(max_length=10, default='AP04')
    version = models.CharField(max_length=20, default='1.1.20191201')

    # Connection Settings
    timeout_seconds = models.PositiveIntegerField(default=30)
    max_retry_attempts = models.PositiveIntegerField(default=3)

    # Sync Settings
    auto_sync_enabled = models.BooleanField(default=True)
    auto_fiscalize = models.BooleanField(default=True)
    sync_interval_minutes = models.PositiveIntegerField(default=60)
    last_dictionary_sync = models.DateTimeField(null=True, blank=True)
    dictionary_version = models.CharField(max_length=20, default='1')

    # Status and Validation
    is_initialized = models.BooleanField(default=False)
    is_active = models.BooleanField(default=False)
    last_test_connection = models.DateTimeField(null=True, blank=True)
    test_connection_success = models.BooleanField(default=False)
    last_login = models.DateTimeField(null=True, blank=True)

    # Server Configuration
    server_public_key = models.TextField(blank=True)
    client_private_key = models.TextField(blank=True)
    symmetric_key = models.CharField(max_length=255, blank=True)

    client_private_key_encrypted = models.TextField(
        blank=True,
        help_text=_("Encrypted client private key received from T102 initialization")
    )
    key_table = models.TextField(
        blank=True,
        help_text=_("Key table received from T102 for decrypting client private key")
    )

    # Additional dictionary version tracking
    commodity_category_version = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text=_("Version of commodity categories from EFRIS")
    )
    excise_duty_version = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text=_("Version of excise duty categories from EFRIS")
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("EFRIS Configuration")
        verbose_name_plural = _("EFRIS Configurations")

    def __str__(self):
        return f"EFRIS Config - {self.company.display_name}"

    @property
    def tin(self):
        """Return the TIN from the related company"""
        return getattr(self.company, 'tin', None)

    @property
    def api_url(self):
        """Get appropriate API URL based on environment"""
        if self.api_base_url:
            return self.api_base_url.rstrip('/')

        if self.environment == 'production':
            return "https://efrisws.ura.go.ug/ws/taapp/getInformation"
        return "https://efristest.ura.go.ug/efrisws/ws/taapp/getInformation"

    @classmethod
    def get_for_company(cls, company):
        """Get configuration for a company (django-tenants compatible)"""
        from django_tenants.utils import schema_context
        with schema_context(company.schema_name):
            config, created = cls.objects.get_or_create(
                company=company,
                defaults={
                    'device_number': '1026925503_01',
                    'is_active': False,
                }
            )
            return config

    @property
    def is_configured(self):
        """Basic configuration check"""
        return (
                self.public_certificate and
                self.private_key and
                self.is_certificate_valid and
                self.is_active
        )

    @property
    def is_certificate_valid(self):
        """Check if certificate/key is valid"""
        if not self.public_certificate:
            return False

        # If it's just a public key (no expiration), consider it valid if we have it
        if self.certificate_expires_at is None:
            return bool(self.certificate_fingerprint)

        # If it's a certificate, check expiration
        return self.certificate_expires_at > timezone.now()

    @property
    def days_until_certificate_expires(self):
        """Get days until certificate expires (None for public keys)"""
        if not self.certificate_expires_at:
            return None
        return (self.certificate_expires_at - timezone.now()).days

    @property
    def certificate_type(self):
        """Determine if this is a certificate or just a public key"""
        if not self.public_certificate:
            return "unknown"

        cert_data = self.public_certificate.strip()
        if cert_data.startswith('-----BEGIN PUBLIC KEY-----'):
            return "public_key"
        elif cert_data.startswith('-----BEGIN CERTIFICATE-----'):
            return "x509_certificate"
        elif cert_data.startswith('-----BEGIN RSA PUBLIC KEY-----'):
            return "rsa_public_key"
        else:
            # For base64 data, we'd need to parse to determine
            return "unknown"

    @property
    def private_key_type(self):
        """Determine the type of private key"""
        if not self.private_key:
            return "unknown"

        key_data = self.private_key.strip()
        if key_data.startswith('-----BEGIN PRIVATE KEY-----'):
            return "pkcs8_private_key"
        elif key_data.startswith('-----BEGIN RSA PRIVATE KEY-----'):
            return "rsa_private_key"
        elif key_data.startswith('-----BEGIN ENCRYPTED PRIVATE KEY-----'):
            return "encrypted_private_key"
        else:
            return "unknown"

    def validate_private_key(self):
        """Validate the private key"""
        if not self.private_key:
            return True  # Private key is optional in some configurations

        key_data = self.private_key.strip()

        try:
            # Handle different private key formats
            if key_data.startswith('-----BEGIN'):
                # PEM format
                if self.key_password:
                    # Encrypted private key
                    private_key = serialization.load_pem_private_key(
                        key_data.encode('utf-8'),
                        password=self.key_password.encode('utf-8')
                    )
                else:
                    # Unencrypted private key
                    private_key = serialization.load_pem_private_key(
                        key_data.encode('utf-8'),
                        password=None
                    )
            else:
                # Try as base64 encoded DER
                try:
                    clean_b64 = ''.join(key_data.split())
                    missing_padding = len(clean_b64) % 4
                    if missing_padding:
                        clean_b64 += '=' * (4 - missing_padding)

                    key_der = base64.b64decode(clean_b64)

                    if self.key_password:
                        private_key = serialization.load_der_private_key(
                            key_der,
                            password=self.key_password.encode('utf-8')
                        )
                    else:
                        private_key = serialization.load_der_private_key(
                            key_der,
                            password=None
                        )
                except Exception:
                    # Try PKCS#12 format
                    try:
                        from cryptography.hazmat.primitives import pkcs12
                        key_der = base64.b64decode(clean_b64)
                        private_key, certificate, additional_certificates = pkcs12.load_key_and_certificates(
                            key_der,
                            password=self.key_password.encode('utf-8') if self.key_password else None
                        )
                    except Exception as e:
                        raise ValidationError(f"Could not load private key in any supported format: {str(e)}")

            # Generate fingerprint for the private key
            private_key_der = private_key.private_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            )
            self.private_key_fingerprint = hashlib.sha256(private_key_der).hexdigest().upper()

            print(f"Successfully loaded private key")
            print(f"Key type: {type(private_key).__name__}")
            print(f"Key size: {private_key.key_size} bits")
            print(f"Private key fingerprint: {self.private_key_fingerprint}")

            return True

        except Exception as e:
            raise ValidationError(f"Invalid private key: {str(e)}")

    def validate_certificate(self):
        """Validate the uploaded certificate/public key - supports both X.509 certificates and public keys"""
        if not self.public_certificate:
            raise ValidationError("Public certificate is required")

        cert_data_clean = self.public_certificate.strip()

        try:
            # Check if it's a public key (not a certificate)
            if cert_data_clean.startswith('-----BEGIN PUBLIC KEY-----'):
                return self._validate_public_key(cert_data_clean)
            elif cert_data_clean.startswith('-----BEGIN RSA PUBLIC KEY-----'):
                return self._validate_rsa_public_key(cert_data_clean)
            # Check if it's an X.509 certificate
            elif cert_data_clean.startswith('-----BEGIN CERTIFICATE-----'):
                return self._validate_x509_certificate(cert_data_clean)
            # Try base64-encoded formats
            else:
                # First try as base64-encoded certificate
                try:
                    return self._validate_base64_certificate(cert_data_clean)
                except:
                    # Then try as base64-encoded public key
                    return self._validate_base64_public_key(cert_data_clean)

        except ValidationError:
            raise
        except Exception as e:
            raise ValidationError(
                f"Could not parse the provided data as either an X.509 certificate or public key: {str(e)}"
            )

    def _validate_public_key(self, cert_data_clean):
        """Handle PEM public key format"""
        try:
            # Load the public key
            public_key = serialization.load_pem_public_key(cert_data_clean.encode('utf-8'))
            return self._process_public_key(public_key)
        except Exception as e:
            raise ValidationError(f"Invalid public key format: {str(e)}")

    def _validate_rsa_public_key(self, cert_data_clean):
        """Handle RSA PEM public key format"""
        try:
            # Convert RSA public key to standard format
            from cryptography.hazmat.primitives.asymmetric import rsa
            public_key = serialization.load_pem_public_key(cert_data_clean.encode('utf-8'))
            return self._process_public_key(public_key)
        except Exception as e:
            raise ValidationError(f"Invalid RSA public key format: {str(e)}")

    def _process_public_key(self, public_key):
        """Common processing for public keys"""

        return True

    def _validate_x509_certificate(self, cert_data_clean):
        """Handle PEM X.509 certificate format"""
        try:
            cert_data = cert_data_clean.encode('utf-8')
            certificate = x509.load_pem_x509_certificate(cert_data)
            cert_der = certificate.public_bytes(encoding=x509.Encoding.DER)

            # Extract certificate info
            self.certificate_expires_at = certificate.not_valid_after.replace(tzinfo=timezone.utc)

            # Generate fingerprint
            fingerprint = hashlib.sha256(cert_der).hexdigest().upper()
            self.certificate_fingerprint = fingerprint

            # Validate dates
            now = timezone.now()
            if certificate.not_valid_before > now:
                raise ValidationError("Certificate is not yet valid")
            if certificate.not_valid_after < now:
                raise ValidationError("Certificate has expired")

            print(f"Successfully loaded X.509 certificate")
            print(f"Valid from {certificate.not_valid_before} to {certificate.not_valid_after}")
            print(f"Certificate fingerprint: {fingerprint}")

            return True

        except Exception as e:
            raise ValidationError(f"Invalid X.509 certificate: {str(e)}")

    def _validate_base64_certificate(self, cert_data_clean):
        """Try to load as base64-encoded DER certificate"""
        try:
            # Clean and decode
            clean_b64 = ''.join(cert_data_clean.split())
            missing_padding = len(clean_b64) % 4
            if missing_padding:
                clean_b64 += '=' * (4 - missing_padding)

            cert_der = base64.b64decode(clean_b64)
            certificate = x509.load_der_x509_certificate(cert_der)

            # Extract info
            self.certificate_expires_at = certificate.not_valid_after.replace(tzinfo=timezone.utc)
            fingerprint = hashlib.sha256(cert_der).hexdigest().upper()
            self.certificate_fingerprint = fingerprint

            return True

        except Exception as e:
            raise ValidationError(f"Invalid base64 certificate: {str(e)}")

    def _validate_base64_public_key(self, cert_data_clean):
        """Try to load as base64-encoded DER public key"""
        try:
            # Clean and decode
            clean_b64 = ''.join(cert_data_clean.split())
            missing_padding = len(clean_b64) % 4
            if missing_padding:
                clean_b64 += '=' * (4 - missing_padding)

            key_der = base64.b64decode(clean_b64)
            public_key = serialization.load_der_public_key(key_der)

            # Generate fingerprint
            fingerprint = hashlib.sha256(key_der).hexdigest().upper()
            self.certificate_fingerprint = fingerprint
            self.certificate_expires_at = None

            return True

        except Exception as e:
            raise ValidationError(f"Invalid base64 public key: {str(e)}")

    def validate_key_pair_compatibility(self):
        """Validate that private key and public certificate/key are compatible"""
        if not self.private_key or not self.public_certificate:
            return True  # Can't validate if either is missing

        try:
            # Load private key
            private_key = self._load_private_key()

            # Load public key/certificate
            public_key = self._load_public_key()

            # Compare public keys
            private_public_key = private_key.public_key()

            # Compare public key components
            private_public_der = private_public_key.public_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )

            public_der = public_key.public_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )

            if private_public_der != public_der:
                raise ValidationError("Private key and public certificate/key do not match")

            return True

        except ValidationError:
            raise
        except Exception as e:
            raise ValidationError(f"Error validating key pair compatibility: {str(e)}")

    def _load_private_key(self):
        """Load the private key object"""
        key_data = self.private_key.strip()

        if key_data.startswith('-----BEGIN'):
            # PEM format
            if self.key_password:
                return serialization.load_pem_private_key(
                    key_data.encode('utf-8'),
                    password=self.key_password.encode('utf-8')
                )
            else:
                return serialization.load_pem_private_key(
                    key_data.encode('utf-8'),
                    password=None
                )
        else:
            # Base64 DER format
            clean_b64 = ''.join(key_data.split())
            missing_padding = len(clean_b64) % 4
            if missing_padding:
                clean_b64 += '=' * (4 - missing_padding)

            key_der = base64.b64decode(clean_b64)

            if self.key_password:
                return serialization.load_der_private_key(
                    key_der,
                    password=self.key_password.encode('utf-8')
                )
            else:
                return serialization.load_der_private_key(
                    key_der,
                    password=None
                )

    def _load_public_key(self):
        """Load the public key object from certificate or public key"""
        cert_data = self.public_certificate.strip()

        try:
            # Try as certificate first
            if cert_data.startswith('-----BEGIN CERTIFICATE-----'):
                cert = x509.load_pem_x509_certificate(cert_data.encode('utf-8'))
                return cert.public_key()
            elif cert_data.startswith('-----BEGIN PUBLIC KEY-----') or cert_data.startswith(
                    '-----BEGIN RSA PUBLIC KEY-----'):
                return serialization.load_pem_public_key(cert_data.encode('utf-8'))
            else:
                # Try base64 encoded
                clean_b64 = ''.join(cert_data.split())
                missing_padding = len(clean_b64) % 4
                if missing_padding:
                    clean_b64 += '=' * (4 - missing_padding)

                data_der = base64.b64decode(clean_b64)

                # Try as certificate first
                try:
                    cert = x509.load_der_x509_certificate(data_der)
                    return cert.public_key()
                except:
                    # Try as public key
                    return serialization.load_der_public_key(data_der)

        except Exception as e:
            raise ValidationError(f"Could not load public key: {str(e)}")

    def debug_certificate_data(self):
        """Debug helper to inspect certificate data format"""
        if not self.public_certificate:
            print("No certificate data provided")
            return

        cert_data = self.public_certificate.strip()

        print(f"Certificate data length: {len(cert_data)} characters")
        print(f"First 100 characters: {cert_data[:100]}")
        print(f"Last 100 characters: {cert_data[-100:]}")

        # Check if it looks like PEM
        if cert_data.startswith('-----BEGIN'):
            print("Format appears to be PEM")
            lines = cert_data.split('\n')
            print(f"Number of lines: {len(lines)}")
            if len(lines) > 2:
                print(f"First line: {lines[0]}")
                print(f"Last line: {lines[-1]}")
        else:
            print("Format appears to be base64 or binary")

            # Try to decode as base64 and check first few bytes
            try:
                # Clean the data
                clean_data = ''.join(cert_data.split())
                missing_padding = len(clean_data) % 4
                if missing_padding:
                    clean_data += '=' * (4 - missing_padding)

                decoded = base64.b64decode(clean_data)
                print(f"Successfully base64 decoded to {len(decoded)} bytes")
                print(f"First 20 bytes as hex: {decoded[:20].hex().upper()}")

                # DER certificates should start with 0x30 (SEQUENCE tag)
                if decoded[0] == 0x30:
                    print("First byte is 0x30 - looks like valid DER format")
                else:
                    print(f"First byte is 0x{decoded[0]:02X} - this might not be a DER certificate")

            except Exception as e:
                print(f"Base64 decode failed: {e}")

                # Check if it might be raw binary
                try:
                    raw_bytes = cert_data.encode('latin1')
                    print(f"Treating as raw binary: {len(raw_bytes)} bytes")
                    print(f"First 20 bytes as hex: {raw_bytes[:20].hex().upper()}")

                    if raw_bytes[0] == 0x30:
                        print("First byte is 0x30 - might be raw DER format")
                    else:
                        print(f"First byte is 0x{raw_bytes[0]:02X} - this doesn't look like DER")

                except Exception as e2:
                    print(f"Raw binary interpretation also failed: {e2}")

    def debug_private_key_data(self):
        """Debug helper to inspect private key data format"""
        if not self.private_key:
            print("No private key data provided")
            return

        key_data = self.private_key.strip()

        print(f"Private key data length: {len(key_data)} characters")
        print(f"First 100 characters: {key_data[:100]}")

        # Check if it looks like PEM
        if key_data.startswith('-----BEGIN'):
            print("Format appears to be PEM")
            lines = key_data.split('\n')
            print(f"Number of lines: {len(lines)}")
            if len(lines) > 2:
                print(f"First line: {lines[0]}")
                print(f"Last line: {lines[-1]}")
        else:
            print("Format appears to be base64 or binary")

    def inspect_all_keys(self):
        """Comprehensive inspection of all keys and certificates"""
        print("=== Private Key Inspection ===")
        self.debug_private_key_data()

        print("\n=== Certificate/Public Key Inspection ===")
        self.debug_certificate_data()

        print("\n=== Validation Tests ===")
        try:
            if self.private_key:
                print("Testing private key validation...")
                self.validate_private_key()
                print("✓ Private key validation successful!")
            else:
                print("- No private key to validate")
        except ValidationError as e:
            print(f"✗ Private key validation failed: {e}")

        try:
            if self.public_certificate:
                print("Testing certificate/public key validation...")
                self.validate_certificate()
                print("✓ Certificate/public key validation successful!")
            else:
                print("- No certificate/public key to validate")
        except ValidationError as e:
            print(f"✗ Certificate/public key validation failed: {e}")

        try:
            if self.private_key and self.public_certificate:
                print("Testing key pair compatibility...")
                self.validate_key_pair_compatibility()
                print("✓ Key pair compatibility validated!")
            else:
                print("- Cannot validate key pair compatibility (missing keys)")
        except ValidationError as e:
            print(f"✗ Key pair compatibility failed: {e}")

    def clean(self):
        """Model validation"""
        super().clean()

        errors = {}

        # Validate private key if provided
        if self.private_key:
            try:
                self.validate_private_key()
            except ValidationError as e:
                errors['private_key'] = str(e)

        # Validate certificate/public key if provided
        if self.public_certificate:
            try:
                self.validate_certificate()
            except ValidationError as e:
                errors['public_certificate'] = str(e)

        # Validate key pair compatibility
        if self.private_key and self.public_certificate and not errors:
            try:
                self.validate_key_pair_compatibility()
            except ValidationError as e:
                errors['__all__'] = str(e)

        if errors:
            raise ValidationError(errors)

    @property
    def api_url(self):
        """Get appropriate API URL based on environment"""
        if self.api_base_url:
            return self.api_base_url.rstrip('/')
        if self.environment == 'production':
            return "https://efrisws.ura.go.ug/ws/taapp/getInformation"
        return "https://efristest.ura.go.ug/efrisws/ws/taapp/getInformation"

    @api_url.setter
    def api_url(self, value):
        self.api_base_url = value


class ProductUploadTask(models.Model):
    """Track background product upload jobs"""

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    task_id = models.CharField(max_length=100, unique=True, db_index=True)

    # Progress tracking
    total_products = models.IntegerField(default=0)
    processed_count = models.IntegerField(default=0)
    successful_count = models.IntegerField(default=0)
    failed_count = models.IntegerField(default=0)

    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    error_details = models.JSONField(null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # User tracking
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['task_id']),
            models.Index(fields=['status', 'created_at']),
        ]

    def __str__(self):
        return f"Upload Task {self.task_id} - {self.status}"

    @property
    def progress_percentage(self):
        """Calculate progress percentage"""
        if self.total_products == 0:
            return 0
        return int((self.processed_count / self.total_products) * 100)

    @property
    def is_complete(self):
        return self.status in ['completed', 'failed']



class EFRISDigitalKey(models.Model):
    """Store and manage digital keys for EFRIS"""

    KEY_TYPES = [
        ('self_signed', 'Self-Signed Certificate'),
        ('ca_issued', 'Certificate Authority Issued'),
    ]

    STATUS_CHOICES = [
        ('active', 'Active'),
        ('expired', 'Expired'),
        ('revoked', 'Revoked'),
        ('pending', 'Pending Validation'),
    ]

    company = models.ForeignKey(
        'company.Company',
        on_delete=models.CASCADE,
        related_name='efris_keys'
    )

    key_type = models.CharField(max_length=20, choices=KEY_TYPES, default='self_signed')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    # Key Data
    private_key = models.TextField(help_text=_("PKCS#12 private key (base64)"))
    public_certificate = models.TextField(help_text=_("X.509 certificate (base64)"))
    key_password = models.CharField(max_length=255, blank=True)

    # Certificate Information
    subject_name = models.CharField(max_length=255, blank=True)
    issuer_name = models.CharField(max_length=255, blank=True)
    serial_number = models.CharField(max_length=100, blank=True)
    fingerprint = models.CharField(max_length=128, unique=True)

    # Validity
    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField()

    # Upload Information
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    # URA Registration
    uploaded_to_ura = models.BooleanField(default=False)
    ura_upload_date = models.DateTimeField(null=True, blank=True)
    ura_response = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-uploaded_at']
        verbose_name = _("EFRIS Digital Key")
        verbose_name_plural = _("EFRIS Digital Keys")

    def __str__(self):
        return f"{self.subject_name} ({self.get_status_display()})"

    @property
    def is_valid(self):
        """Check if key is currently valid"""
        now = timezone.now()
        return (
                self.status == 'active' and
                self.valid_from <= now <= self.valid_until
        )

    @property
    def days_until_expiry(self):
        """Days until key expires"""
        return (self.valid_until - timezone.now()).days

    def validate_key_pair(self):
        """Validate that private key and certificate match"""
        try:
            import base64
            from cryptography.hazmat.primitives import serialization
            from cryptography import x509

            # Load private key
            private_key_data = base64.b64decode(self.private_key)
            private_key = serialization.load_pkcs12(
                private_key_data,
                self.key_password.encode() if self.key_password else None
            )[0]

            # Load certificate
            cert_data = base64.b64decode(self.public_certificate)
            certificate = x509.load_der_x509_certificate(cert_data)

            # Extract certificate info
            self.subject_name = certificate.subject.rfc4514_string()
            self.issuer_name = certificate.issuer.rfc4514_string()
            self.serial_number = str(certificate.serial_number)
            self.valid_from = certificate.not_valid_before
            self.valid_until = certificate.not_valid_after

            # Generate fingerprint
            import hashlib
            self.fingerprint = hashlib.sha256(cert_data).hexdigest()

            # Validate key pair matches
            public_key = certificate.public_key()
            private_numbers = private_key.private_numbers()
            public_numbers = public_key.public_numbers()

            if private_numbers.public_numbers.n != public_numbers.n:
                raise ValidationError("Private key and certificate do not match")

            self.status = 'active'
            return True

        except Exception as e:
            self.status = 'pending'
            raise ValidationError(f"Key validation failed: {str(e)}")

class EFRISExceptionLog(models.Model):
    """Store EFRIS exception logs for batch upload"""

    INTERRUPTION_TYPE_CHOICES = [
        ('101', 'Number of Disconnected'),
        ('102', 'Login Failure'),
        ('103', 'Receipt Upload Failure'),
        ('104', 'System related errors'),
        ('105', 'Paper roll replacement'),
    ]

    company = models.ForeignKey(
        'company.Company',
        on_delete=models.CASCADE,
        related_name='efris_exception_logs'
    )
    interruption_type_code = models.CharField(
        max_length=3,
        choices=INTERRUPTION_TYPE_CHOICES
    )
    description = models.TextField(max_length=3000)
    error_detail = models.TextField(max_length=4000, blank=True, null=True)
    interruption_time = models.DateTimeField()

    # Upload tracking
    uploaded = models.BooleanField(default=False)
    uploaded_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'efris_exception_logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['company', 'uploaded']),
            models.Index(fields=['interruption_time']),
        ]

    def __str__(self):
        return f"{self.get_interruption_type_code_display()} - {self.interruption_time}"

class EFRISSystemDictionary(models.Model):
    """Store EFRIS system dictionaries (tax rates, currencies, etc.)"""

    DICTIONARY_TYPES = [
        ('creditNoteMaximumInvoicingDays', 'Credit Note Maximum Days'),
        ('currencyType', 'Currency Types'),
        ('rateUnit', 'Rate Units'),
        ('sector', 'Business Sectors'),
        ('payWay', 'Payment Methods'),
        ('countryCode', 'Country Codes'),
        ('deliveryTerms', 'Delivery Terms'),
        ('commodityCategory', 'Commodity Categories'),
        ('exciseDuty', 'Excise Duties'),
        ('format', 'Date/Time Formats'),
    ]

    company = models.ForeignKey(
        'company.Company',
        on_delete=models.CASCADE,
        related_name='efris_dictionaries'
    )
    dictionary_type = models.CharField(max_length=50, choices=DICTIONARY_TYPES)
    version = models.CharField(max_length=20, default='1.0')
    data = models.JSONField(default=dict)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['company', 'dictionary_type']]
        verbose_name = _("EFRIS System Dictionary")
        verbose_name_plural = _("EFRIS System Dictionaries")

    def __str__(self):
        return f"{self.get_dictionary_type_display()} - {self.company.display_name}"


class EFRISAPILog(models.Model):
    """Log all EFRIS API interactions"""

    INTERFACE_CODES = [
        ('T101', 'Get Server Time'),
        ('T102', 'Client Initialization'),
        ('T103', 'Login'),
        ('T104', 'Get Symmetric Key'),
        ('T105', 'Forget Password'),
        ('T106', 'Invoice Query'),
        ('T107', 'Query Normal Invoices'),
        ('T108', 'Invoice Details'),
        ('T109', 'Invoice Upload'),
        ('T110', 'Credit Note Application'),
        ('T111', 'Credit/Debit Note List Query'),
        ('T112', 'Credit Note Details'),
        ('T113', 'Credit Note Approval'),
        ('T114', 'Cancel Credit/Debit Note'),
        ('T115', 'System Dictionary Update'),
        ('T116', 'Z-Report Upload'),
        ('T117', 'Invoice Reconciliation'),
        ('T119', 'Query Taxpayer by TIN'),
        ('T127', 'Goods/Services Inquiry'),
        ('T129', 'Batch Invoice Upload'),
        ('T130', 'Goods Upload'),
        ('T131', 'Stock Management'),
        ('T136', 'Certificate Upload'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('timeout', 'Timeout'),
        ('cancelled', 'Cancelled'),
    ]

    company = models.ForeignKey(
        'company.Company',
        on_delete=models.CASCADE,
        related_name='efris_api_logs'
    )
    interface_code = models.CharField(max_length=10, choices=INTERFACE_CODES)
    request_data = models.JSONField(default=dict)
    response_data = models.JSONField(default=dict)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    return_code = models.CharField(max_length=10, blank=True)
    return_message = models.TextField(blank=True)
    error_message = models.TextField(blank=True, null=True)

    request_time = models.DateTimeField(auto_now_add=True)
    response_time = models.DateTimeField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)

    # Link to related objects
    invoice = models.ForeignKey(
        'invoices.Invoice',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='efris_logs'
    )
    product = models.ForeignKey(
        'inventory.Product',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='efris_logs'
    )

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['-request_time']
        verbose_name = _("EFRIS API Log")
        verbose_name_plural = _("EFRIS API Logs")
        indexes = [
            models.Index(fields=['company', 'interface_code']),
            models.Index(fields=['status', 'request_time']),
            models.Index(fields=['return_code']),
        ]

    def __str__(self):
        return f"{self.interface_code} - {self.status} ({self.request_time})"


class EFRISSyncQueue(models.Model):
    """Queue for EFRIS synchronization tasks"""

    SYNC_TYPES = [
        ('invoice_fiscalize', 'Fiscalize Invoice'),
        ('product_upload', 'Upload Product'),
        ('stock_update', 'Update Stock'),
        ('credit_note_apply', 'Apply Credit Note'),
        ('dictionary_sync', 'Sync Dictionary'),
        ('certificate_upload', 'Upload Certificate'),
        ('goods_inquiry', 'Goods Inquiry'),
        ('taxpayer_info', 'Taxpayer Information'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
        ('retry', 'Retry Required'),
    ]

    PRIORITY_CHOICES = [
        (1, 'High'),
        (2, 'Normal'),
        (3, 'Low'),
    ]

    company = models.ForeignKey(
        'company.Company',
        on_delete=models.CASCADE,
        related_name='efris_sync_queue'
    )
    sync_type = models.CharField(max_length=30, choices=SYNC_TYPES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    priority = models.IntegerField(choices=PRIORITY_CHOICES, default=2)

    # Generic foreign keys to related objects
    object_id = models.PositiveIntegerField(null=True, blank=True)
    object_type = models.CharField(max_length=50, blank=True)

    # Task data and results
    task_data = models.JSONField(default=dict)
    result_data = models.JSONField(default=dict)
    error_message = models.TextField(blank=True)

    # Scheduling
    scheduled_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # Retry logic
    retry_count = models.PositiveIntegerField(default=0)
    max_retries = models.PositiveIntegerField(default=3)
    next_retry_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['priority', 'scheduled_at']
        verbose_name = _("EFRIS Sync Queue")
        verbose_name_plural = _("EFRIS Sync Queue")
        indexes = [
            models.Index(fields=['company', 'status']),
            models.Index(fields=['sync_type', 'status']),
            models.Index(fields=['scheduled_at']),
            models.Index(fields=['priority', 'scheduled_at']),
        ]

    def __str__(self):
        return f"{self.sync_type} - {self.status}"

    def can_retry(self):
        """Check if task can be retried"""
        return (
                self.status in ['failed', 'retry'] and
                self.retry_count < self.max_retries
        )


class EFRISFiscalizationBatch(models.Model):
    """Batch processing for multiple fiscalization operations"""

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('partial', 'Partially Completed'),
        ('failed', 'Failed'),
    ]

    company = models.ForeignKey(
        'company.Company',
        on_delete=models.CASCADE,
        related_name='efris_batches'
    )
    batch_name = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    total_items = models.PositiveIntegerField(default=0)
    processed_items = models.PositiveIntegerField(default=0)
    successful_items = models.PositiveIntegerField(default=0)
    failed_items = models.PositiveIntegerField(default=0)

    batch_data = models.JSONField(default=dict)
    result_summary = models.JSONField(default=dict)

    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = _("EFRIS Fiscalization Batch")
        verbose_name_plural = _("EFRIS Fiscalization Batches")

    def __str__(self):
        return f"Batch: {self.batch_name} ({self.status})"

    @property
    def completion_percentage(self):
        if self.total_items == 0:
            return 0
        return (self.processed_items / self.total_items) * 100


class EFRISDeviceInfo(models.Model):
    """EFRIS device information per store"""

    DEVICE_STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('suspended', 'Suspended'),
        ('expired', 'Expired'),
        ('registered', 'Registered'),
        ('pending', 'Pending Registration'),
    ]

    store = models.OneToOneField(
        'stores.Store',
        on_delete=models.CASCADE,
        related_name='efris_device'
    )

    # Device Details from existing store model
    @property
    def device_number(self):
        return self.store.efris_device_number

    @property
    def device_serial(self):
        return self.store.device_serial_number

    # Status
    status = models.CharField(max_length=20, choices=DEVICE_STATUS_CHOICES, default='pending')
    is_online = models.BooleanField(default=False)
    last_ping = models.DateTimeField(null=True, blank=True)

    # Limits and Usage
    offline_days_limit = models.PositiveIntegerField(default=90)
    offline_amount_limit = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=10000000,
        validators=[MinValueValidator(0)]
    )
    current_offline_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=0
    )

    # Timestamps
    registered_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    last_sync = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("EFRIS Device Info")
        verbose_name_plural = _("EFRIS Device Info")

    def __str__(self):
        return f"Device {self.device_number} - {self.store.name}"

    @property
    def is_expired(self):
        return self.expires_at and self.expires_at < timezone.now()

    @property
    def can_fiscalize_offline(self):
        return (
                self.status == 'active' and
                not self.is_expired and
                self.current_offline_amount < self.offline_amount_limit
        )


class FiscalizationAudit(models.Model):
    """Audit trail for all fiscalization operations"""

    ACTION_CHOICES = [
        ('FISCALIZE', 'Invoice Fiscalization'),
        ('CREDIT_NOTE', 'Credit Note Application'),
        ('DEBIT_NOTE', 'Debit Note Application'),
        ('CANCEL', 'Cancellation Request'),
        ('QUERY', 'Invoice Query'),
        ('SYNC', 'Data Synchronization'),
        ('ERROR', 'Error Handling'),
        ('RETRY', 'Retry Attempt'),
        ('VALIDATE', 'Validation Check'),
        ('UPLOAD_GOODS', 'Goods Upload'),
        ('STOCK_UPDATE', 'Stock Update'),
        ('CERTIFICATE_UPLOAD', 'Certificate Upload'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
        ('timeout', 'Timeout'),
        ('retry_needed', 'Retry Needed'),
        ('partially_completed', 'Partially Completed'),
    ]

    SEVERITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ]

    # Core Information
    company = models.ForeignKey(
        'company.Company',
        on_delete=models.CASCADE,
        related_name='efris_audit_logs'
    )

    action = models.CharField(max_length=30, choices=ACTION_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default='medium')

    # Invoice Information
    invoice = models.ForeignKey(
        'invoices.Invoice',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='fiscalization_audits_efris'
    )
    invoice_number = models.CharField(max_length=100, blank=True)
    fiscal_document_number = models.CharField(max_length=100, blank=True)
    verification_code = models.CharField(max_length=100, blank=True)
    request_payload = models.JSONField(blank=True, null=True)
    response_payload = models.JSONField(blank=True, null=True)
    # EFRIS Response Data
    efris_interface_code = models.CharField(max_length=10, blank=True)
    efris_return_code = models.CharField(max_length=10, blank=True)
    efris_return_message = models.TextField(blank=True)
    efris_response = models.JSONField(default=dict, blank=True)

    # Request Information
    request_data = models.JSONField(default=dict, blank=True)
    device_number = models.CharField(max_length=50, blank=True)
    device_mac = models.CharField(max_length=17, blank=True)

    # Timing Information
    started_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.FloatField(null=True, blank=True)

    # Error Information
    error_message = models.TextField(blank=True)
    error_code = models.CharField(max_length=50, blank=True)
    error_details = models.JSONField(default=dict, blank=True)

    # System Information
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='efris_audit_actions'
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    # Retry Information
    retry_count = models.PositiveIntegerField(default=0)
    max_retries = models.PositiveIntegerField(default=3)
    parent_audit = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='retry_attempts'
    )

    # Business Context
    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True
    )
    tax_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True
    )
    customer_tin = models.CharField(max_length=20, blank=True)
    customer_name = models.CharField(max_length=255, blank=True)

    # Additional Context
    notes = models.TextField(blank=True)
    tags = models.CharField(max_length=255, blank=True, help_text="Comma-separated tags")

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = _("Fiscalization Audit")
        verbose_name_plural = _("Fiscalization Audits")
        indexes = [
            models.Index(fields=['company', 'action']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['invoice', 'action']),
            models.Index(fields=['fiscal_document_number']),
            models.Index(fields=['efris_interface_code', 'efris_return_code']),
            models.Index(fields=['severity', 'status']),
            models.Index(fields=['user', 'created_at']),
        ]

    def __str__(self):
        if self.invoice_number:
            return f"{self.action} - {self.invoice_number} ({self.status})"
        return f"{self.action} - {self.get_status_display()} ({self.created_at})"

    @property
    def is_success(self):
        """Check if audit represents successful operation"""
        return self.status == 'success'

    @property
    def is_failed(self):
        """Check if audit represents failed operation"""
        return self.status in ['failed', 'timeout', 'cancelled']

    @property
    def can_retry(self):
        """Check if operation can be retried"""
        return (
                self.is_failed and
                self.retry_count < self.max_retries and
                self.action in ['FISCALIZE', 'CREDIT_NOTE', 'DEBIT_NOTE', 'UPLOAD_GOODS']
        )

    @property
    def duration_display(self):
        """Human-readable duration"""
        if not self.duration_seconds:
            return "N/A"

        if self.duration_seconds < 1:
            return f"{self.duration_seconds * 1000:.0f}ms"
        elif self.duration_seconds < 60:
            return f"{self.duration_seconds:.1f}s"
        else:
            minutes = int(self.duration_seconds // 60)
            seconds = int(self.duration_seconds % 60)
            return f"{minutes}m {seconds}s"

    def mark_completed(self, status='success', efris_response=None, error_message=''):
        """Mark audit as completed"""
        self.completed_at = timezone.now()
        self.status = status

        if self.started_at and self.completed_at:
            self.duration_seconds = (self.completed_at - self.started_at).total_seconds()

        if efris_response:
            self.efris_response = efris_response
            return_info = efris_response.get('returnStateInfo', {})
            self.efris_return_code = return_info.get('returnCode', '')
            self.efris_return_message = return_info.get('returnMessage', '')

        if error_message:
            self.error_message = error_message

        self.save()

    def create_retry_audit(self, user=None):
        """Create a new audit entry for retry attempt"""
        if not self.can_retry:
            return None

        retry_audit = FiscalizationAudit.objects.create(
            company=self.company,
            action=self.action,
            invoice=self.invoice,
            invoice_number=self.invoice_number,
            request_data=self.request_data,
            device_number=self.device_number,
            device_mac=self.device_mac,
            user=user or self.user,
            retry_count=self.retry_count + 1,
            parent_audit=self,
            amount=self.amount,
            tax_amount=self.tax_amount,
            customer_tin=self.customer_tin,
            customer_name=self.customer_name,
            notes=f"Retry attempt {self.retry_count + 1} for audit #{self.id}"
        )
        return retry_audit

    def add_context(self, **kwargs):
        """Add additional context to the audit"""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.save()

    def get_success_rate_for_action(self):
        """Get success rate for this action type in the company"""
        total = FiscalizationAudit.objects.filter(
            company=self.company,
            action=self.action
        ).count()

        if total == 0:
            return 0

        successful = FiscalizationAudit.objects.filter(
            company=self.company,
            action=self.action,
            status='success'
        ).count()

        return (successful / total) * 100


class EFRISCommodityCategorry(models.Model):
    """Store minimal EFRIS commodity categories for reference"""
    company = models.ForeignKey('company.Company',null=True,
    blank=True, on_delete=models.CASCADE)
    commodity_category_code = models.CharField(max_length=18, db_index=True)
    commodity_category_name = models.CharField(max_length=200)
    is_exempt = models.CharField(max_length=3)     # 101=Yes, 102=No
    is_leaf_node = models.CharField(max_length=3)  # 101=Yes, 102=No
    is_zero_rate = models.CharField(max_length=3)  # 101=Yes, 102=No

    last_synced = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['company', 'commodity_category_code']]
        ordering = ['commodity_category_code']

    def __str__(self):
        return f"{self.commodity_category_code} - {self.commodity_category_name}"

class EFRISIntegrationSettings(models.Model):
    """Advanced EFRIS integration settings per company"""

    company = models.OneToOneField(
        'company.Company',
        on_delete=models.CASCADE,
        related_name='efris_integration_settings'
    )

    # Automation Settings
    auto_fiscalize_invoices = models.BooleanField(default=True)
    auto_upload_products = models.BooleanField(default=False)
    auto_sync_dictionaries = models.BooleanField(default=True)
    auto_retry_failed_operations = models.BooleanField(default=True)

    # Retry Configuration
    max_retry_attempts = models.PositiveIntegerField(default=3)
    retry_delay_minutes = models.PositiveIntegerField(default=5)
    exponential_backoff = models.BooleanField(default=True)

    # Notification Settings
    notify_on_fiscalization_success = models.BooleanField(default=False)
    notify_on_fiscalization_failure = models.BooleanField(default=True)
    notify_on_certificate_expiry = models.BooleanField(default=True)
    notification_email = models.EmailField(blank=True)

    # Validation Settings
    strict_validation_mode = models.BooleanField(default=True)
    validate_customer_tin = models.BooleanField(default=True)
    require_customer_details = models.BooleanField(default=False)

    # Batch Processing
    batch_size_limit = models.PositiveIntegerField(default=50)
    batch_processing_enabled = models.BooleanField(default=True)
    max_concurrent_batches = models.PositiveIntegerField(default=2)

    # Performance Settings
    request_timeout_seconds = models.PositiveIntegerField(default=30)
    connection_pool_size = models.PositiveIntegerField(default=10)
    enable_request_caching = models.BooleanField(default=True)
    cache_duration_minutes = models.PositiveIntegerField(default=15)

    # Audit and Logging
    detailed_audit_logging = models.BooleanField(default=True)
    log_request_data = models.BooleanField(default=True)
    log_response_data = models.BooleanField(default=True)
    audit_retention_days = models.PositiveIntegerField(default=365)

    # Security Settings
    encrypt_sensitive_data = models.BooleanField(default=True)
    mask_tin_in_logs = models.BooleanField(default=True)
    require_user_approval_for_retries = models.BooleanField(default=False)

    # Business Rules
    allow_backdated_invoices = models.BooleanField(default=False)
    max_backdate_days = models.PositiveIntegerField(default=7)
    require_approval_above_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("EFRIS Integration Settings")
        verbose_name_plural = _("EFRIS Integration Settings")

    def __str__(self):
        return f"EFRIS Settings - {self.company.name}"


class EFRISOperationMetrics(models.Model):
    """Store operational metrics for EFRIS operations"""

    METRIC_TYPES = [
        ('fiscalization_count', 'Daily Fiscalization Count'),
        ('success_rate', 'Operation Success Rate'),
        ('average_response_time', 'Average Response Time'),
        ('error_rate', 'Error Rate'),
        ('batch_completion_rate', 'Batch Completion Rate'),
        ('certificate_status', 'Certificate Status'),
        ('system_uptime', 'System Uptime'),
    ]

    company = models.ForeignKey(
        'company.Company',
        on_delete=models.CASCADE,
        related_name='efris_metrics'
    )

    metric_type = models.CharField(max_length=50, choices=METRIC_TYPES)
    metric_value = models.DecimalField(max_digits=15, decimal_places=2)
    metric_unit = models.CharField(max_length=20, blank=True)  # %, count, ms, etc.

    # Time period for the metric
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()

    # Additional context
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['company', 'metric_type', 'period_start', 'period_end']]
        ordering = ['-period_start']
        verbose_name = _("EFRIS Operation Metric")
        verbose_name_plural = _("EFRIS Operation Metrics")

    def __str__(self):
        return f"{self.get_metric_type_display()}: {self.metric_value}{self.metric_unit}"


class EFRISNotification(models.Model):
    """EFRIS-related notifications and alerts"""

    NOTIFICATION_TYPES = [
        ('fiscalization_success', 'Fiscalization Success'),
        ('fiscalization_failure', 'Fiscalization Failed'),
        ('certificate_expiring', 'Certificate Expiring'),
        ('certificate_expired', 'Certificate Expired'),
        ('sync_failure', 'Synchronization Failed'),
        ('quota_exceeded', 'Quota Exceeded'),
        ('system_maintenance', 'System Maintenance'),
        ('api_error', 'API Error'),
        ('batch_completed', 'Batch Completed'),
        ('validation_warning', 'Validation Warning'),
    ]

    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]

    STATUS_CHOICES = [
        ('unread', 'Unread'),
        ('read', 'Read'),
        ('dismissed', 'Dismissed'),
        ('archived', 'Archived'),
    ]

    company = models.ForeignKey(
        'company.Company',
        on_delete=models.CASCADE,
        related_name='efris_notifications'
    )

    notification_type = models.CharField(max_length=30, choices=NOTIFICATION_TYPES)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='medium')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='unread')

    title = models.CharField(max_length=200)
    message = models.TextField()

    # Related objects
    invoice = models.ForeignKey(
        'invoices.Invoice',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='efris_notifications'
    )

    audit = models.ForeignKey(
        FiscalizationAudit,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='notifications'
    )

    # Additional data
    action_url = models.URLField(blank=True)
    action_label = models.CharField(max_length=50, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    # Delivery tracking
    email_sent = models.BooleanField(default=False)
    email_sent_at = models.DateTimeField(null=True, blank=True)
    push_sent = models.BooleanField(default=False)
    push_sent_at = models.DateTimeField(null=True, blank=True)

    # User interaction
    read_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='efris_notifications_read'
    )
    read_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = _("EFRIS Notification")
        verbose_name_plural = _("EFRIS Notifications")
        indexes = [
            models.Index(fields=['company', 'status']),
            models.Index(fields=['notification_type', 'priority']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.title} ({self.get_priority_display()})"

    def mark_as_read(self, user=None):
        """Mark notification as read"""
        self.status = 'read'
        self.read_by = user
        self.read_at = timezone.now()
        self.save()

    def mark_as_dismissed(self):
        """Mark notification as dismissed"""
        self.status = 'dismissed'
        self.save()


class EFRISErrorPattern(models.Model):
    """Track and analyze error patterns for better debugging"""

    company = models.ForeignKey(
        'company.Company',
        on_delete=models.CASCADE,
        related_name='efris_error_patterns'
    )

    error_code = models.CharField(max_length=50)
    error_message = models.TextField()
    interface_code = models.CharField(max_length=10, blank=True)

    # Pattern analysis
    occurrence_count = models.PositiveIntegerField(default=1)
    first_occurred = models.DateTimeField(auto_now_add=True)
    last_occurred = models.DateTimeField(auto_now=True)

    # Resolution tracking
    is_resolved = models.BooleanField(default=False)
    resolution_notes = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    # Pattern metadata
    affected_operations = models.JSONField(default=list, blank=True)
    suggested_solution = models.TextField(blank=True)
    priority = models.CharField(
        max_length=10,
        choices=[('low', 'Low'), ('medium', 'Medium'), ('high', 'High')],
        default='medium'
    )

    class Meta:
        unique_together = [['company', 'error_code', 'interface_code']]
        verbose_name = _("EFRIS Error Pattern")
        verbose_name_plural = _("EFRIS Error Patterns")

    def __str__(self):
        return f"{self.error_code} - {self.occurrence_count} occurrences"

    def increment_occurrence(self):
        """Increment occurrence count and update last occurred timestamp"""
        self.occurrence_count += 1
        self.last_occurred = timezone.now()
        self.save()

