from math import radians, sin, cos, atan2, sqrt
from accounts.models import AuditLog
from django.db import models
from django.core.validators import RegexValidator, MinValueValidator
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
import uuid
from django.utils import timezone
from datetime import timedelta
import json
from django.conf import settings


class Store(models.Model):
    STORE_TYPES = [
        ('MAIN', _('Main Store')),
        ('BRANCH', _('Branch Store')),
        ('WAREHOUSE', _('Warehouse')),
        ('OUTLET', _('Retail Outlet')),
    ]

    company = models.ForeignKey(
        'company.Company',
        on_delete=models.CASCADE,
        related_name='stores',
        verbose_name=_("Company"), null=True, blank=True
    )

    staff = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='stores',
        verbose_name=_("Assigned Staff"),
        help_text=_("Users who can access this store")
    )
    store_managers = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name='managed_stores',
        verbose_name=_("Store Managers"),
        help_text=_("Users who can manage this store")
    )

    accessible_by_all = models.BooleanField(
        default=False,
        verbose_name=_("Accessible by All Company Users"),
        help_text=_("If checked, all users in the company can access this store")
    )

    name = models.CharField(max_length=255, verbose_name=_("Store Name"))
    code = models.CharField(
        max_length=20,
        unique=True,
        blank=True,
        null=True,
        verbose_name=_("Store Code"),
        help_text=_("Internal identifier for the store")
    )
    store_type = models.CharField(
        max_length=20,
        choices=STORE_TYPES,
        default='BRANCH',
        verbose_name=_("Store Type")
    )

    # Merged fields from CompanyBranch
    nin = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name=_("NIN"),
        help_text=_("National Identification Number")
    )
    tin = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name=_("TIN"),
        help_text=_("Tax Identification Number")
    )
    # EFRIS Store Override Configuration
    use_company_efris = models.BooleanField(
        default=True,
        verbose_name=_("Use Company EFRIS Configuration"),
        help_text=_("When checked, uses company-level EFRIS settings. Uncheck to use store-specific settings.")
    )

    store_efris_private_key = models.TextField(
        blank=True,
        null=True,
        verbose_name=_("Store Private Key")
    )

    store_efris_public_certificate = models.TextField(
        blank=True,
        null=True,
        verbose_name=_("Store Public Certificate")
    )

    store_efris_key_password = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_("Store Key Password")
    )

    store_efris_certificate_fingerprint = models.CharField(
        max_length=128,
        blank=True,
        null=True,
        verbose_name=_("Store Certificate Fingerprint")
    )

    store_efris_is_production = models.BooleanField(
        default=False,
        verbose_name=_("Store EFRIS Production Mode")
    )

    store_efris_integration_mode = models.CharField(
        max_length=10,
        choices=[('online', 'Online Mode'), ('offline', 'Offline Mode')],
        default='online',
        verbose_name=_("Store EFRIS Integration Mode")
    )

    store_auto_fiscalize_sales = models.BooleanField(
        default=True,
        verbose_name=_("Store Auto-Fiscalize Sales")
    )

    store_auto_sync_products = models.BooleanField(
        default=True,
        verbose_name=_("Store Auto-Sync Products")
    )

    store_efris_is_active = models.BooleanField(
        default=False,
        verbose_name=_("Store EFRIS Active")
    )

    store_efris_last_sync = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name=_("Store EFRIS Last Sync")
    )
    # Branch behavior flags
    is_main_branch = models.BooleanField(
        default=False,
        verbose_name=_("Main Branch/Store"),
        help_text=_("Designates this as the primary store for the company")
    )
    allows_sales = models.BooleanField(
        default=True,
        verbose_name=_("Allows Sales")
    )
    allows_inventory = models.BooleanField(
        default=True,
        verbose_name=_("Manages Inventory")
    )

    # Manager Information (from CompanyBranch)
    manager_name = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Store Manager")
    )
    manager_phone = models.CharField(
        max_length=20,
        blank=True,
        validators=[RegexValidator(r'^\+?[0-9]+$', _('Enter a valid phone number.'))],
        verbose_name=_("Manager Phone")
    )

    # Operating Hours (from CompanyBranch)
    operating_hours = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Operating hours for each day of the week")
    )
    timezone = models.CharField(
        max_length=100,
        blank=True,
        default='Africa/Kampala'
    )

    # Metadata (from CompanyBranch)
    sort_order = models.PositiveIntegerField(
        default=0,
        help_text=_("Used for ordering stores in lists")
    )
    notes = models.TextField(
        blank=True,
        verbose_name=_("Notes")
    )

    # Location fields (existing)
    location = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Location/Area")
    )
    physical_address = models.TextField(verbose_name=_("Physical Address"))
    location_gps = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_("GPS Coordinates")
    )
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        blank=True,
        null=True
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        blank=True,
        null=True
    )
    region = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_("Region/District")
    )

    # Contact fields (existing)
    phone = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        validators=[RegexValidator(r'^\+?[0-9]+$', _('Enter a valid phone number.'))],
        verbose_name=_("Primary Phone")
    )
    secondary_phone = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        validators=[RegexValidator(r'^\+?[0-9]+$', _('Enter a valid phone number.'))],
        verbose_name=_("Secondary Phone")
    )
    email = models.EmailField(
        blank=True,
        null=True,
        verbose_name=_("Store Email")
    )
    logo = models.ImageField(
        upload_to='store-logos/',
        blank=True,
        null=True,
        verbose_name=_("Store Logo")
    )

    # EFRIS fields (existing)
    efris_device_number = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name=_("EFRIS Device Number"),
        help_text=_("Device number assigned by URA")
    )
    device_serial_number = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_("Device Serial Number")
    )
    efris_enabled = models.BooleanField(
        default=False,
        verbose_name=_("EFRIS Enabled")
    )
    is_registered_with_efris = models.BooleanField(
        default=False,
        verbose_name=_("Registered with EFRIS")
    )
    efris_registration_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("EFRIS Registration Date")
    )
    efris_last_sync = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name=_("Last EFRIS Sync")
    )
    last_stock_sync = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Last Stock Sync")
    )

    # EFRIS Settings (existing)
    auto_fiscalize_sales = models.BooleanField(
        default=True,
        verbose_name=_("Auto-Fiscalize Sales")
    )
    allow_manual_fiscalization = models.BooleanField(
        default=True,
        verbose_name=_("Allow Manual Fiscalization")
    )
    report_stock_movements = models.BooleanField(
        default=True,
        verbose_name=_("Report Stock Movements to EFRIS")
    )

    # Status (existing)
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Active")
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Created At")
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Updated At")
    )

    def get_absolute_url(self):
        """Get the URL for the store detail page."""
        return reverse('stores:store_detail', kwargs={'pk': self.pk})

    def get_map_url(self):
        """Generate Google Maps URL for the store location."""
        if self.latitude and self.longitude:
            return f"https://www.google.com/maps?q={self.latitude},{self.longitude}"
        return None

    def get_directions_url(self, from_lat=None, from_lng=None):
        """Generate Google Maps directions URL."""
        if not self.latitude or not self.longitude:
            return None

        if from_lat and from_lng:
            return f"https://www.google.com/maps/dir/{from_lat},{from_lng}/{self.latitude},{self.longitude}"
        else:
            return f"https://www.google.com/maps/dir/?api=1&destination={self.latitude},{self.longitude}"

    def distance_to(self, lat, lon):
        """
        Calculate distance to another point in kilometers using Haversine formula.

        Args:
            lat: Latitude of target point
            lon: Longitude of target point

        Returns:
            Distance in kilometers, or None if this store has no coordinates
        """
        if not self.latitude or not self.longitude:
            return None

        # Earth's radius in kilometers
        R = 6371.0

        # Convert degrees to radians
        lat1 = radians(float(self.latitude))
        lon1 = radians(float(self.longitude))
        lat2 = radians(float(lat))
        lon2 = radians(float(lon))

        # Differences
        dlat = lat2 - lat1
        dlon = lon2 - lon1

        # Haversine formula
        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))

        distance = R * c
        return round(distance, 2)

    @classmethod
    def find_nearest_stores(cls, lat, lon, limit=5, max_distance_km=None):
        """
        Find the nearest stores to a given location.

        Args:
            lat: Latitude to search from
            lon: Longitude to search from
            limit: Maximum number of stores to return
            max_distance_km: Maximum distance in kilometers (optional)

        Returns:
            List of tuples: (store, distance_km)
        """
        stores_with_coords = cls.objects.filter(
            is_active=True,
            latitude__isnull=False,
            longitude__isnull=False
        )

        # Calculate distances
        stores_with_distance = []
        for store in stores_with_coords:
            distance = store.distance_to(lat, lon)
            if distance is not None:
                if max_distance_km is None or distance <= max_distance_km:
                    stores_with_distance.append((store, distance))

        # Sort by distance
        stores_with_distance.sort(key=lambda x: x[1])

        return stores_with_distance[:limit]

    def get_inventory_summary(self):
        """Get a summary of inventory for this store."""
        from django.db.models import Sum, Count, Q, F

        inventory = self.inventory_items.select_related('product')

        return {
            'total_products': inventory.count(),
            'total_quantity': inventory.aggregate(Sum('quantity'))['quantity__sum'] or 0,
            'low_stock_count': inventory.filter(
                quantity__lte=F('low_stock_threshold')
            ).count(),
            'out_of_stock_count': inventory.filter(quantity=0).count(),
            'total_value': inventory.aggregate(
                total=Sum(F('quantity') * F('product__cost_price'))
            )['total'] or 0,
        }

    def get_sales_summary(self, days=30):
        """Get sales summary for the specified number of days."""
        from django.utils import timezone
        from datetime import timedelta
        from django.db.models import Sum, Count, Avg

        start_date = timezone.now() - timedelta(days=days)

        # Use 'created_at' or 'date' field based on what your Sale model has
        try:
            sales = self.sales.filter(created_at__gte=start_date)
        except:
            # Try alternative field names
            try:
                sales = self.sales.filter(date__gte=start_date)
            except:
                sales = self.sales.all()

        return {
            'total_sales': sales.count(),
            'total_revenue': sales.aggregate(Sum('total_amount'))['total_amount__sum'] or 0,
            'average_sale': sales.aggregate(Avg('total_amount'))['total_amount__avg'] or 0,
            'paid_sales': sales.filter(payment_status='PAID').count(),
            'pending_sales': sales.filter(payment_status='PENDING').count(),
        }

    def get_company_efris_config(self):
        """
        Fetch company EFRIS configuration with improved error handling.
        Returns a dictionary of company EFRIS values.
        """
        if not self.company_id:
            return {}

        try:
            from django_tenants.utils import schema_context
            from company.models import Company
            from efris.models import EFRISConfiguration  # Import the EFRISConfiguration model

            config = {}

            # Step 1: Get company info from public schema
            with schema_context('public'):
                company = Company.objects.get(company_id=self.company_id)

                # Get basic company info
                config.update({
                    # Business Information
                    'tin': company.tin or '',
                    'nin': company.nin or '',
                    'email': company.email or '',
                    'phone': company.phone or '',
                    'business_address': company.physical_address or '',
                    'business_name': company.trading_name or company.name or '',
                    'taxpayer_name': company.name or '',

                    # Company-level EFRIS settings
                    'efris_enabled': company.efris_enabled,
                    'efris_is_active': company.efris_is_active,
                    'efris_device_number': company.efris_device_number or '',
                    'efris_is_production': company.efris_is_production,
                    'efris_integration_mode': company.efris_integration_mode,
                    'efris_auto_fiscalize_sales': company.efris_auto_fiscalize_sales,
                    'efris_auto_sync_products': company.efris_auto_sync_products,
                })

            # Step 2: Get EFRIS configuration from tenant schema
            # Switch to company's tenant schema to access EFRISConfiguration
            with schema_context(self.company.schema_name):
                try:
                    # Get the EFRISConfiguration for this company
                    efris_config = EFRISConfiguration.objects.filter(company=self.company).first()

                    if efris_config:
                        # Add EFRIS configuration details
                        config.update({
                            'efris_private_key': efris_config.private_key or '',
                            'efris_public_certificate': efris_config.public_certificate or '',
                            'efris_key_password': efris_config.key_password or '',
                            'efris_certificate_fingerprint': efris_config.certificate_fingerprint or '',
                            'efris_certificate_expires_at': efris_config.certificate_expires_at,
                            'efris_environment': efris_config.environment or 'sandbox',
                            'efris_mode': efris_config.mode or 'online',
                            'efris_device_mac': efris_config.device_mac or '',
                            'efris_app_id': efris_config.app_id or '',
                            'efris_version': efris_config.version or '',
                            'efris_is_initialized': efris_config.is_initialized,
                            'efris_timeout_seconds': efris_config.timeout_seconds or 30,
                            'efris_max_retry_attempts': efris_config.max_retry_attempts or 3,
                            'efris_auto_sync_enabled': efris_config.auto_sync_enabled,
                            'efris_auto_fiscalize': efris_config.auto_fiscalize,
                            'efris_sync_interval_minutes': efris_config.sync_interval_minutes or 60,
                        })
                except Exception as tenant_error:
                    # Handle case where EFRISConfiguration might not exist or schema not accessible
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.warning(f"Could not fetch EFRIS configuration for company {self.company_id}: {tenant_error}")

                    # Fallback to checking if certificate data exists in company JSONField
                    # (if you still want to support the old way)
                    if hasattr(company, 'efris_certificate_data') and company.efris_certificate_data and isinstance(
                            company.efris_certificate_data, dict):
                        config.update({
                            'efris_private_key': company.efris_certificate_data.get('private_key', ''),
                            'efris_public_certificate': company.efris_certificate_data.get('public_certificate', ''),
                            'efris_key_password': company.efris_certificate_data.get('key_password', ''),
                            'efris_certificate_fingerprint': company.efris_certificate_data.get(
                                'certificate_fingerprint', ''),
                        })

            return config

        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error fetching company EFRIS config for store {self.id}: {e}")
            return {}

    def get_efris_value(self, field_name, company_value=None):
        """
        Get EFRIS value with store override logic.

        Args:
            field_name: The base field name (without 'store_' prefix)
            company_value: The company's value for this field (optional)

        Returns:
            The effective value (store-specific or company value)
        """
        # If using company config, return company value
        if self.use_company_efris:
            return company_value

        # Try to get store-specific field
        store_field_name = f"store_{field_name}"

        # Handle special field mappings
        if field_name == 'tin':
            store_field_name = 'tin'
        elif field_name == 'efris_device_number':
            store_field_name = 'efris_device_number'
        elif field_name == 'efris_certificate_fingerprint':
            store_field_name = 'store_efris_certificate_fingerprint'

        if hasattr(self, store_field_name):
            store_value = getattr(self, store_field_name)
            # Return store value if it's not empty
            if store_value not in [None, '', [], {}]:
                return store_value

        # Fallback to company value
        return company_value

    @property
    def effective_efris_config(self):
        """
        Returns the effective EFRIS configuration for this store.
        Automatically uses store-specific values when available and enabled.
        """
        # Get company config as base
        company_config = self.get_company_efris_config()

        # Build effective config with overrides
        effective_config = {
            # Core EFRIS fields
            'tin': self.get_efris_value('tin', company_config.get('tin')),
            'nin': self.get_efris_value('nin', company_config.get('nin')),
            'device_number': self.get_efris_value('efris_device_number', company_config.get('efris_device_number')),

            # Certificate Configuration
            'private_key': self.get_efris_value('efris_private_key', company_config.get('efris_private_key')),
            'public_certificate': self.get_efris_value('efris_public_certificate',
                                                       company_config.get('efris_public_certificate')),
            'key_password': self.get_efris_value('efris_key_password', company_config.get('efris_key_password')),
            'certificate_fingerprint': self.get_efris_value('efris_certificate_fingerprint',
                                                            company_config.get('efris_certificate_fingerprint')),

            # Environment & Mode
            'is_production': self.get_efris_value('efris_is_production', company_config.get('efris_is_production')),
            'integration_mode': self.get_efris_value('efris_integration_mode',
                                                     company_config.get('efris_integration_mode')),

            # Automation Settings
            'auto_fiscalize_sales': self.get_efris_value('auto_fiscalize_sales',
                                                         company_config.get('efris_auto_fiscalize_sales')),
            'auto_sync_products': self.get_efris_value('auto_sync_products',
                                                       company_config.get('efris_auto_sync_products')),

            # Status
            'is_active': self.get_efris_value('efris_is_active', company_config.get('efris_is_active')),
            'enabled': self.get_efris_value('efris_enabled', company_config.get('efris_enabled')),
            'last_sync': self.get_efris_value('efris_last_sync', company_config.get('efris_last_sync')),

            'email': self.email or company_config.get('email'),
            'phone': self.phone or company_config.get('phone'),
            'business_address': self.physical_address or company_config.get('business_address'),

            # Store Information
            'store_name': self.name,
            'store_code': self.code,
            'store_id': self.id,

            # Configuration Source
            'use_company_efris': self.use_company_efris,
            'config_source': 'company' if self.use_company_efris else 'store',
        }

        effective_config['business_name'] = company_config.get('business_name', '')
        effective_config['taxpayer_name'] = company_config.get('taxpayer_name', '')

        return effective_config

    @property
    def can_fiscalize(self):
        """
        Enhanced check if store can fiscalize transactions.
        Considers both company and store-specific EFRIS config.
        """
        config = self.effective_efris_config

        # Required fields for fiscalization
        required_fields = [
            config.get('enabled'),
            config.get('is_active'),
            config.get('device_number'),
            config.get('tin'),
            config.get('private_key'),
            config.get('public_certificate'),
        ]

        return (
                all(required_fields) and
                self.is_active and
                self.allows_sales
        )

    @property
    def efris_config_status(self):
        """
        Get detailed EFRIS configuration status.
        Returns dict with status information.
        """
        config = self.effective_efris_config

        status = {
            'configured': False,
            'config_source': config.get('config_source'),
            'missing_fields': [],
            'warnings': [],
        }

        # Check required fields
        required_fields = {
            'tin': 'TIN Number',
            'device_number': 'Device Number',
            'private_key': 'Private Key',
            'public_certificate': 'Public Certificate',
            'email': 'Email Address',
            'phone': 'Phone Number',
        }

        for field, label in required_fields.items():
            if not config.get(field):
                status['missing_fields'].append(label)

        # Check optional but recommended fields
        if not config.get('business_address'):
            status['warnings'].append('Business address not set')

        if not config.get('key_password') and config.get('private_key'):
            status['warnings'].append('Private key may not be encrypted')

        # Determine if configured
        status['configured'] = len(status['missing_fields']) == 0

        return status

    def validate_efris_configuration(self):
        """
        Validate EFRIS configuration and return errors.
        Returns tuple: (is_valid, errors_list)
        """
        config = self.effective_efris_config
        errors = []

        # Check if EFRIS is enabled
        if not config.get('enabled'):
            return True, []  # Not an error if EFRIS is disabled

        # Required fields validation
        if not config.get('tin'):
            errors.append("TIN number is required for EFRIS integration")

        if not config.get('device_number'):
            errors.append("EFRIS device number is required")

        if not config.get('private_key'):
            errors.append("Private key is required for EFRIS integration")

        if not config.get('public_certificate'):
            errors.append("Public certificate is required for EFRIS integration")

        if not config.get('email'):
            errors.append("Email address is required for EFRIS integration")

        if not config.get('phone'):
            errors.append("Phone number is required for EFRIS integration")

        # Validate certificate fingerprint if provided
        if config.get('certificate_fingerprint'):
            fingerprint = config.get('certificate_fingerprint')
            if len(fingerprint) not in [64, 128]:  # SHA256 or SHA512
                errors.append("Invalid certificate fingerprint format")

        return len(errors) == 0, errors

    def switch_to_company_efris(self):
        """Switch to using company EFRIS configuration."""
        self.use_company_efris = True
        self.save(update_fields=['use_company_efris', 'updated_at'])

    def switch_to_store_efris(self):
        """
        Switch to using store-specific EFRIS configuration.
        Validates that required store fields are set.
        """
        is_valid, errors = self.validate_efris_configuration()

        if not is_valid:
            raise ValueError(f"Cannot switch to store EFRIS config. Missing: {', '.join(errors)}")

        self.use_company_efris = False
        self.save(update_fields=['use_company_efris', 'updated_at'])

    def copy_company_efris_to_store(self):
        """
        Copy company EFRIS configuration to store-specific fields.
        Useful for creating a store-specific config based on company settings.
        """
        company_config = self.get_company_efris_config()

        # Copy relevant fields
        self.tin = company_config.get('tin')
        self.efris_device_number = company_config.get('efris_device_number')
        self.store_efris_client_id = company_config.get('efris_client_id')
        self.store_efris_api_key = company_config.get('efris_api_key')
        self.store_efris_private_key = company_config.get('efris_private_key')
        self.store_efris_public_certificate = company_config.get('efris_public_certificate')
        self.store_efris_key_password = company_config.get('efris_key_password')
        self.store_efris_certificate_fingerprint = company_config.get('efris_certificate_fingerprint')
        self.store_efris_is_production = company_config.get('efris_is_production')
        self.store_efris_integration_mode = company_config.get('efris_integration_mode')
        self.store_auto_fiscalize_sales = company_config.get('efris_auto_fiscalize_sales')
        self.store_auto_sync_products = company_config.get('efris_auto_sync_products')
        self.store_efris_is_active = company_config.get('efris_is_active')

        self.save()

    def get_device_summary(self):
        """Get summary of devices for this store."""
        devices = self.devices.filter(is_active=True)

        return {
            'total_devices': devices.count(),
            'efris_devices': devices.filter(is_efris_linked=True).count(),
            'pos_devices': devices.filter(device_type='POS').count(),
            'fiscal_devices': devices.filter(device_type='EFRIS_FISCAL').count(),
        }

    def get_staff_count(self):
        """Get the number of staff assigned to this store."""
        return self.staff.filter(is_active=True).count()

    def validate_coordinates(self):
        """
        Validate that coordinates are within reasonable bounds.
        Uganda is approximately between:
        Latitude: -1.5° to 4.2°
        Longitude: 29.5° to 35.0°
        """
        if not self.latitude or not self.longitude:
            return True, "No coordinates set"

        lat = float(self.latitude)
        lon = float(self.longitude)

        # Uganda bounds (with some buffer)
        if -2.0 <= lat <= 5.0 and 29.0 <= lon <= 36.0:
            return True, "Coordinates valid"
        else:
            return False, "Coordinates appear to be outside Uganda"

    @property
    def has_coordinates(self):
        """Check if store has valid coordinates."""
        return self.latitude is not None and self.longitude is not None

    @property
    def coordinate_string(self):
        """Get formatted coordinate string."""
        if self.has_coordinates:
            return f"{self.latitude}, {self.longitude}"
        return "No coordinates"

    @property
    def store_status_badge(self):
        """Get HTML badge class based on store status."""
        if not self.is_active:
            return "danger"
        elif self.is_main_branch:
            return "primary"
        elif self.efris_enabled:
            return "success"
        else:
            return "secondary"

    @property
    def store_status_text(self):
        """Get human-readable store status."""
        if not self.is_active:
            return "Inactive"
        elif self.is_main_branch:
            return "Main Branch"
        elif self.efris_enabled:
            return "EFRIS Enabled"
        else:
            return "Active"

    def get_nearby_stores(self, radius_km=50, limit=10):
        """
        Get stores within a specified radius.

        Args:
            radius_km: Search radius in kilometers
            limit: Maximum number of stores to return

        Returns:
            QuerySet of nearby stores with distance annotation
        """
        if not self.has_coordinates:
            return Store.objects.none()

        return Store.find_nearest_stores(
            float(self.latitude),
            float(self.longitude),
            limit=limit + 1,  # +1 to exclude self
            max_distance_km=radius_km
        )[1:]  # Exclude the first result (self)

    def format_address_for_geocoding(self):
        """Format address for geocoding services."""
        parts = []

        if self.physical_address:
            parts.append(self.physical_address)

        if self.location:
            parts.append(self.location)

        if self.region:
            parts.append(self.region)

        parts.append("Uganda")  # Add country

        return ", ".join(parts)

    def get_performance_metrics(self):
        """Get comprehensive performance metrics for the store."""
        inventory_summary = self.get_inventory_summary()
        sales_summary = self.get_sales_summary()
        device_summary = self.get_device_summary()

        return {
            'inventory': inventory_summary,
            'sales': sales_summary,
            'devices': device_summary,
            'staff_count': self.get_staff_count(),
            'efris_status': self.efris_status,
            'can_fiscalize': self.can_fiscalize,
            'is_operational': self.is_active and self.allows_sales,
        }

    class Meta:
        verbose_name = _("Store")
        verbose_name_plural = _("Stores")
        ordering = ['-is_main_branch', 'sort_order', 'name']
        constraints = [
            models.UniqueConstraint(
                fields=['company', 'code'],
                name='unique_store_code_per_company'
            ),
            models.UniqueConstraint(
                fields=['efris_device_number'],
                condition=models.Q(efris_device_number__isnull=False),
                name='unique_efris_device_number'
            )
        ]
        indexes = [
            models.Index(fields=['company', 'is_active']),
            models.Index(fields=['is_main_branch']),
            models.Index(fields=['company', 'store_type']),
            models.Index(fields=['latitude', 'longitude']),  # For map queries
            models.Index(fields=['region']),  # For region filtering
        ]


    def __str__(self):
        company_name = self.company.name if self.company else "No Company"
        return f"{company_name} - {self.name}"

    def save(self, *args, **kwargs):
        skip_main_branch_update = kwargs.pop('skip_main_branch_update', False)

        # Auto-generate code if not provided
        if not self.code:
            self.code = f"ST-{uuid.uuid4().hex[:6].upper()}"

        # Set default values for required fields
        if self.allows_sales is None:
            self.allows_sales = True
        if self.allows_inventory is None:
            self.allows_inventory = True

        # Only try to update other stores if this store has an ID (already exists)
        # and if we're setting it as main branch and not skipping the logic
        if not skip_main_branch_update and self.id and self.is_main_branch and self.company:
            try:
                Store.objects.filter(
                    company=self.company,
                    is_main_branch=True
                ).exclude(id=self.id).update(is_main_branch=False)
            except Exception as e:
                # If this fails (e.g., table doesn't exist or no other stores), just log and continue
                print(f"Warning: Could not update other stores: {e}")

        super().save(*args, **kwargs)

    @property
    def full_address(self):
        """Get full formatted address."""
        parts = [self.physical_address, self.location]
        return ", ".join(filter(None, parts))

    @property
    def tax_details(self):
        return {
            'store_name': self.name,
            'store_address': self.physical_address,
            'store_phone': self.phone,
            'efris_device_number': self.efris_device_number,
            'tin': self.tin,
            'nin': self.nin,
        }


    @property
    def efris_status(self):
        """Get comprehensive EFRIS status"""
        if not self.efris_enabled:
            return "disabled"
        elif not self.efris_device_number:
            return "no_device"
        elif not self.is_registered_with_efris:
            return "unregistered"
        elif self.can_fiscalize:
            return "active"
        else:
            return "inactive"

    def is_open_now(self):
        """Check if store is currently open based on operating hours."""
        if not self.operating_hours:
            return True  # Assume open if no hours set

        from django.utils import timezone
        now = timezone.now()
        day_name = now.strftime('%A').lower()

        day_hours = self.operating_hours.get(day_name)
        if not day_hours or not day_hours.get('is_open', True):
            return False

        current_time = now.time()
        open_time = day_hours.get('open_time')
        close_time = day_hours.get('close_time')

        if open_time and close_time:
            from datetime import datetime
            open_dt = datetime.strptime(open_time, '%H:%M').time()
            close_dt = datetime.strptime(close_time, '%H:%M').time()
            return open_dt <= current_time <= close_dt

        return True

    # Backward compatibility properties
    @property
    def branch_name(self):
        """Backward compatibility for templates using branch.name"""
        return self.name

    @property
    def branch_code(self):
        """Backward compatibility for templates using branch.code"""
        return self.code


class StoreAccess(models.Model):
    """
    Detailed store access control with permissions
    """
    ACCESS_LEVELS = [
        ('view', _('View Only')),
        ('staff', _('Staff Access')),
        ('manager', _('Manager Access')),
        ('admin', _('Admin Access')),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='store_access_permissions',
        verbose_name=_("User")
    )

    store = models.ForeignKey(
        'Store',
        on_delete=models.CASCADE,
        related_name='access_permissions',
        verbose_name=_("Store")
    )

    access_level = models.CharField(
        max_length=20,
        choices=ACCESS_LEVELS,
        default='staff',
        verbose_name=_("Access Level")
    )

    # Granular permissions
    can_view_sales = models.BooleanField(default=True)
    can_create_sales = models.BooleanField(default=True)
    can_view_inventory = models.BooleanField(default=True)
    can_manage_inventory = models.BooleanField(default=False)
    can_view_reports = models.BooleanField(default=False)
    can_fiscalize = models.BooleanField(default=False)
    can_manage_staff = models.BooleanField(default=False)

    # Metadata
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='store_access_grants',
        verbose_name=_("Granted By")
    )

    granted_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = _("Store Access Permission")
        verbose_name_plural = _("Store Access Permissions")
        unique_together = [['user', 'store']]
        indexes = [
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['store', 'is_active']),
            models.Index(fields=['access_level', 'is_active']),
        ]

    def __str__(self):
        return f"{self.user.get_full_name()} - {self.store.name} ({self.get_access_level_display()})"

    def revoke(self, revoked_by=None):
        """Revoke access to this store"""
        self.is_active = False
        self.revoked_at = timezone.now()
        self.save(update_fields=['is_active', 'revoked_at'])

        # Log the revocation
        AuditLog.log(
            action='store_access_revoked',
            user=revoked_by,
            description=f"Revoked {self.user.get_full_name()}'s access to {self.store.name}",
            store=self.store,
            metadata={
                'affected_user_id': self.user.id,
                'access_level': self.access_level
            }
        )

def geocode_address(address_string):
    """
    Geocode an address using OpenStreetMap Nominatim.

    Args:
        address_string: Address to geocode

    Returns:
        Dictionary with 'latitude', 'longitude', and 'display_name', or None if failed
    """
    import requests

    try:
        url = 'https://nominatim.openstreetmap.org/search'
        params = {
            'q': address_string,
            'format': 'json',
            'limit': 1,
            'addressdetails': 1
        }
        headers = {
            'User-Agent': 'PrimeBookStoreApp/1.0'
        }

        response = requests.get(url, params=params, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()
            if data:
                result = data[0]
                return {
                    'latitude': result['lat'],
                    'longitude': result['lon'],
                    'display_name': result.get('display_name', ''),
                    'address_details': result.get('address', {})
                }
    except Exception as e:
        print(f"Geocoding error: {str(e)}")

    return None

class StoreOperatingHours(models.Model):
    DAYS_OF_WEEK = [
        (0, _('Monday')),
        (1, _('Tuesday')),
        (2, _('Wednesday')),
        (3, _('Thursday')),
        (4, _('Friday')),
        (5, _('Saturday')),
        (6, _('Sunday')),
    ]

    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name='operating_hours_detailed',
        verbose_name=_("Store")
    )
    day = models.IntegerField(
        choices=DAYS_OF_WEEK,
        verbose_name=_("Day of Week")
    )
    opening_time = models.TimeField(
        verbose_name=_("Opening Time")
    )
    closing_time = models.TimeField(
        verbose_name=_("Closing Time")
    )
    is_closed = models.BooleanField(
        default=False,
        verbose_name=_("Closed All Day")
    )

    class Meta:
        verbose_name = _("Operating Hour")
        verbose_name_plural = _("Operating Hours")
        ordering = ['day']
        constraints = [
            models.UniqueConstraint(fields=['store', 'day'], name='unique_store_day')
        ]

    def __str__(self):
        if self.is_closed:
            return f"{self.store.name} - {self.get_day_display()}: Closed"
        return f"{self.store.name} - {self.get_day_display()}: {self.opening_time} to {self.closing_time}"

class StoreDevice(models.Model):
    DEVICE_TYPES = [
        ('POS', _('Point of Sale')),
        ('INVOICE', _('Invoice Printer')),
        ('SCANNER', _('Barcode Scanner')),
        ('EFRIS_FISCAL', _('EFRIS Fiscal Device')),
        ('OTHER', _('Other Device')),
    ]

    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.CASCADE,
        related_name='devices',
        verbose_name=_("Store")
    )
    name = models.CharField(
        max_length=100,
        verbose_name=_("Device Name")
    )
    device_number = models.CharField(
        max_length=50,
        unique=True,
        verbose_name=_("Device Number"),
        help_text=_("Device identifier (URA assigned for fiscal devices)")
    )
    device_type = models.CharField(
        max_length=20,
        choices=DEVICE_TYPES,
        default='POS',
        verbose_name=_("Device Type")
    )
    serial_number = models.CharField(
        max_length=100,
        unique=True,
        verbose_name=_("Serial Number")
    )
    mac_address = models.CharField(
        max_length=17,
        blank=True,
        null=True,
        verbose_name=_("MAC Address"),
        help_text=_("Hardware MAC address for dedicated terminals")
    )
    hardware_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_("Hardware ID"),
        help_text=_("Unique hardware identifier")
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Active")
    )
    is_efris_linked = models.BooleanField(
        default=False,
        verbose_name=_("EFRIS Linked"),
        help_text=_("Is this device linked to EFRIS system")
    )
    require_approval = models.BooleanField(
        default=True,
        verbose_name=_("Require Approval"),
        help_text=_("Require admin approval before use")
    )
    max_concurrent_users = models.PositiveIntegerField(
        default=3,
        verbose_name=_("Max Concurrent Users"),
        help_text=_("Maximum number of users that can use this device simultaneously")
    )
    registered_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Registered At")
    )
    last_maintenance = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name=_("Last Maintenance")
    )
    last_seen_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name=_("Last Seen"),
        help_text=_("Last time this device was used")
    )
    notes = models.TextField(
        blank=True,
        null=True,
        verbose_name=_("Notes")
    )

    class Meta:
        verbose_name = _("Store Device")
        verbose_name_plural = _("Store Devices")
        ordering = ['-registered_at']
        indexes = [
            models.Index(fields=['store', 'is_active']),
            models.Index(fields=['device_type', 'is_active']),
            models.Index(fields=['mac_address']),
            models.Index(fields=['hardware_id']),
        ]

    def __str__(self):
        return f"{self.name} ({self.device_number}) - {self.store.name}"

    @property
    def is_fiscal_device(self):
        """Check if this is a fiscal device"""
        return self.device_type == 'EFRIS_FISCAL' or self.is_efris_linked

    @property
    def active_sessions_count(self):
        """Get count of currently active sessions on this device"""
        return self.device_sessions.filter(
            is_active=True,
            expires_at__gt=timezone.now()
        ).count()

    @property
    def is_at_capacity(self):
        """Check if device has reached max concurrent users"""
        return self.active_sessions_count >= self.max_concurrent_users

    def update_last_seen(self):
        """Update the last seen timestamp"""
        self.last_seen_at = timezone.now()
        self.save(update_fields=['last_seen_at'])


class UserDeviceSession(models.Model):
    """Track active user sessions on devices with fingerprinting"""

    SESSION_STATUS = [
        ('ACTIVE', _('Active')),
        ('EXPIRED', _('Expired')),
        ('LOGGED_OUT', _('Logged Out')),
        ('FORCE_CLOSED', _('Force Closed')),
        ('SUSPICIOUS', _('Suspicious')),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='device_sessions',
        verbose_name=_("User")
    )
    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.CASCADE,
        related_name='user_sessions',
        verbose_name=_("Store")
    )
    store_device = models.ForeignKey(
        StoreDevice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='device_sessions',
        verbose_name=_("Store Device"),
        help_text=_("Physical POS device if applicable")
    )

    # Session Information
    session_key = models.CharField(
        max_length=100,
        unique=True,
        verbose_name=_("Session Key")
    )
    status = models.CharField(
        max_length=20,
        choices=SESSION_STATUS,
        default='ACTIVE',
        verbose_name=_("Status")
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Is Active")
    )

    # Device Fingerprint
    device_fingerprint = models.CharField(
        max_length=64,
        db_index=True,
        verbose_name=_("Device Fingerprint"),
        help_text=_("Unique hash identifying this device")
    )

    # Browser Information
    browser_name = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("Browser Name")
    )
    browser_version = models.CharField(
        max_length=20,
        blank=True,
        verbose_name=_("Browser Version")
    )

    # Operating System
    os_name = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("OS Name")
    )
    os_version = models.CharField(
        max_length=20,
        blank=True,
        verbose_name=_("OS Version")
    )

    # Network Information
    ip_address = models.GenericIPAddressField(
        verbose_name=_("IP Address")
    )
    user_agent = models.TextField(
        verbose_name=_("User Agent String")
    )

    # Display Information
    screen_resolution = models.CharField(
        max_length=20,
        blank=True,
        verbose_name=_("Screen Resolution"),
        help_text=_("Format: 1920x1080")
    )

    # Location Information
    timezone = models.CharField(
        max_length=100,
        blank=True,
        default='UTC',
        verbose_name=_("Timezone")
    )
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        blank=True,
        null=True,
        verbose_name=_("Latitude")
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        blank=True,
        null=True,
        verbose_name=_("Longitude")
    )
    location_accuracy = models.FloatField(
        blank=True,
        null=True,
        verbose_name=_("Location Accuracy (meters)")
    )

    # Session Timing
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Login Time")
    )
    last_activity_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Last Activity")
    )
    expires_at = models.DateTimeField(
        verbose_name=_("Expires At")
    )
    logged_out_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name=_("Logout Time")
    )

    # Security Flags
    is_new_device = models.BooleanField(
        default=False,
        verbose_name=_("New Device"),
        help_text=_("First time user logged in from this device")
    )
    is_suspicious = models.BooleanField(
        default=False,
        verbose_name=_("Suspicious Activity"),
        help_text=_("Flagged for suspicious activity")
    )
    suspicious_reason = models.TextField(
        blank=True,
        verbose_name=_("Suspicious Reason")
    )
    security_alerts_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Security Alerts Count")
    )

    # Additional Metadata
    metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Additional Metadata")
    )

    class Meta:
        verbose_name = _("User Device Session")
        verbose_name_plural = _("User Device Sessions")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['store', 'is_active']),
            models.Index(fields=['store_device', 'is_active']),
            models.Index(fields=['device_fingerprint']),
            models.Index(fields=['ip_address', 'created_at']),
            models.Index(fields=['is_suspicious', 'is_active']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['expires_at']),
        ]

    def __str__(self):
        device_info = f" on {self.store_device.name}" if self.store_device else ""
        return f"{self.user.get_full_name()} - {self.browser_name}{device_info} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        # Set expiry time if not set (24 hours from creation for security)
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(hours=24)

        super().save(*args, **kwargs)

    @property
    def is_expired(self):
        """Check if session has expired"""
        return timezone.now() > self.expires_at

    from datetime import timedelta
    from django.utils import timezone

    @property
    def session_duration(self):
        """Get session duration safely"""
        # If created_at is missing, return 0 duration
        if not self.created_at:
            return timedelta(0)
        if self.logged_out_at:
            return self.logged_out_at - self.created_at
        return timezone.now() - self.created_at

    @property
    def location_string(self):
        """Get formatted location string"""
        if self.latitude and self.longitude:
            return f"{self.latitude}, {self.longitude}"
        return None

    def extend_session(self, hours=24):
        """Extend session expiry time"""
        self.expires_at = timezone.now() + timedelta(hours=hours)
        self.save(update_fields=['expires_at'])

    def terminate(self, reason='LOGGED_OUT'):
        """Terminate the session"""
        self.is_active = False
        self.logged_out_at = timezone.now()
        self.status = reason
        self.save(update_fields=['is_active', 'logged_out_at', 'status'])

    def flag_suspicious(self, reason):
        """Flag session as suspicious"""
        self.is_suspicious = True
        self.suspicious_reason = reason
        self.security_alerts_count += 1
        self.status = 'SUSPICIOUS'
        self.save(update_fields=['is_suspicious', 'suspicious_reason',
                                 'security_alerts_count', 'status'])


class DeviceOperatorLog(models.Model):
    ACTION_CHOICES = [
        ('LOGIN', _('Device Login')),
        ('LOGOUT', _('Device Logout')),
        ('SALE', _('Sale Transaction')),
        ('REFUND', _('Refund Transaction')),
        ('FISCALIZE', _('Manual Fiscalization')),
        ('STOCK_UPDATE', _('Stock Update')),
        ('EFRIS_SYNC', _('EFRIS Synchronization')),
        ('MAINTENANCE', _('Device Maintenance')),
        ('SESSION_EXTENDED', _('Session Extended')),
        ('SESSION_TERMINATED', _('Session Terminated')),
        ('SUSPICIOUS_ACTIVITY', _('Suspicious Activity Detected')),
        ('ERROR', _('Error Occurred')),
        ('OTHER', _('Other Action')),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='device_logs',
        verbose_name=_("User")
    )
    action = models.CharField(
        max_length=50,
        choices=ACTION_CHOICES,
        verbose_name=_("Action")
    )
    device = models.ForeignKey(
        StoreDevice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='operator_logs',
        verbose_name=_("Device")
    )
    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.CASCADE,
        related_name='device_logs',
        verbose_name=_("Store")
    )
    session = models.ForeignKey(
        UserDeviceSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='action_logs',
        verbose_name=_("Session"),
        help_text=_("Associated device session")
    )
    timestamp = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Timestamp")
    )
    ip_address = models.GenericIPAddressField(
        blank=True,
        null=True,
        verbose_name=_("IP Address")
    )
    details = models.JSONField(
        default=dict,
        verbose_name=_("Details"),
        help_text=_("Additional action details in JSON format")
    )
    is_efris_related = models.BooleanField(
        default=False,
        verbose_name=_("EFRIS Related"),
        help_text=_("Whether this action is related to EFRIS operations")
    )
    success = models.BooleanField(
        default=True,
        verbose_name=_("Success"),
        help_text=_("Whether the action was successful")
    )
    error_message = models.TextField(
        blank=True,
        verbose_name=_("Error Message"),
        help_text=_("Error details if action failed")
    )

    class Meta:
        verbose_name = _('Device Operator Log')
        verbose_name_plural = _('Device Operator Logs')
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['store', 'timestamp']),
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['device', 'timestamp']),
            models.Index(fields=['action', 'timestamp']),
            models.Index(fields=['is_efris_related', 'timestamp']),
            models.Index(fields=['session', 'timestamp']),
            models.Index(fields=['success', 'timestamp']),
        ]

    def __str__(self):
        device_info = f" on {self.device.name}" if self.device else ""
        return f"{self.user} - {self.get_action_display()}{device_info} at {self.timestamp}"


class SecurityAlert(models.Model):
    """Track security alerts and suspicious activities"""

    ALERT_TYPES = [
        ('NEW_DEVICE', _('New Device Login')),
        ('NEW_LOCATION', _('New Location Login')),
        ('MULTIPLE_FAILED_LOGINS', _('Multiple Failed Login Attempts')),
        ('CONCURRENT_SESSIONS_EXCEEDED', _('Too Many Concurrent Sessions')),
        ('UNUSUAL_ACTIVITY', _('Unusual Activity Pattern')),
        ('IP_CHANGE', _('IP Address Changed During Session')),
        ('SUSPICIOUS_TRANSACTION', _('Suspicious Transaction')),
        ('DEVICE_CAPACITY_EXCEEDED', _('Device Capacity Exceeded')),
        ('OTHER', _('Other Security Concern')),
    ]

    SEVERITY_LEVELS = [
        ('LOW', _('Low')),
        ('MEDIUM', _('Medium')),
        ('HIGH', _('High')),
        ('CRITICAL', _('Critical')),
    ]

    STATUS_CHOICES = [
        ('OPEN', _('Open')),
        ('INVESTIGATING', _('Investigating')),
        ('RESOLVED', _('Resolved')),
        ('FALSE_POSITIVE', _('False Positive')),
        ('IGNORED', _('Ignored')),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='security_alerts',
        verbose_name=_("User")
    )
    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.CASCADE,
        related_name='security_alerts',
        verbose_name=_("Store")
    )
    session = models.ForeignKey(
        UserDeviceSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='security_alerts',
        verbose_name=_("Session")
    )
    device = models.ForeignKey(
        StoreDevice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='security_alerts',
        verbose_name=_("Device")
    )

    alert_type = models.CharField(
        max_length=50,
        choices=ALERT_TYPES,
        verbose_name=_("Alert Type")
    )
    severity = models.CharField(
        max_length=20,
        choices=SEVERITY_LEVELS,
        default='MEDIUM',
        verbose_name=_("Severity")
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='OPEN',
        verbose_name=_("Status")
    )

    title = models.CharField(
        max_length=200,
        verbose_name=_("Alert Title")
    )
    description = models.TextField(
        verbose_name=_("Description")
    )

    ip_address = models.GenericIPAddressField(
        blank=True,
        null=True,
        verbose_name=_("IP Address")
    )

    alert_data = models.JSONField(
        default=dict,
        verbose_name=_("Alert Data"),
        help_text=_("Additional data related to the alert")
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Created At")
    )
    resolved_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name=_("Resolved At")
    )
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='resolved_alerts',
        verbose_name=_("Resolved By")
    )
    resolution_notes = models.TextField(
        blank=True,
        verbose_name=_("Resolution Notes")
    )

    notified = models.BooleanField(
        default=False,
        verbose_name=_("Admin Notified")
    )
    notified_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name=_("Notified At")
    )

    class Meta:
        verbose_name = _("Security Alert")
        verbose_name_plural = _("Security Alerts")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['store', 'status']),
            models.Index(fields=['alert_type', 'status']),
            models.Index(fields=['severity', 'status']),
            models.Index(fields=['created_at', 'status']),
            models.Index(fields=['notified', 'status']),
        ]

    def __str__(self):
        return f"{self.get_alert_type_display()} - {self.user} ({self.get_severity_display()})"

    def resolve(self, resolved_by, notes=''):
        """Mark alert as resolved"""
        self.status = 'RESOLVED'
        self.resolved_at = timezone.now()
        self.resolved_by = resolved_by
        self.resolution_notes = notes
        self.save(update_fields=['status', 'resolved_at', 'resolved_by', 'resolution_notes'])

    def mark_false_positive(self, resolved_by, notes=''):
        """Mark alert as false positive"""
        self.status = 'FALSE_POSITIVE'
        self.resolved_at = timezone.now()
        self.resolved_by = resolved_by
        self.resolution_notes = notes
        self.save(update_fields=['status', 'resolved_at', 'resolved_by', 'resolution_notes'])


class DeviceFingerprint(models.Model):
    """Store known device fingerprints for users"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='known_devices',
        verbose_name=_("User")
    )
    fingerprint_hash = models.CharField(
        max_length=64,
        db_index=True,
        verbose_name=_("Fingerprint Hash")
    )
    device_name = models.CharField(
        max_length=100,
        verbose_name=_("Device Name"),
        help_text=_("User-friendly device name")
    )

    # Aggregated device info
    browser_name = models.CharField(max_length=50, blank=True)
    os_name = models.CharField(max_length=50, blank=True)

    # Trust level
    is_trusted = models.BooleanField(
        default=False,
        verbose_name=_("Trusted Device")
    )
    trust_score = models.IntegerField(
        default=0,
        verbose_name=_("Trust Score"),
        help_text=_("Higher score = more trusted (0-100)")
    )

    # Usage tracking
    first_seen_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("First Seen")
    )
    last_seen_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Last Seen")
    )
    login_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Login Count")
    )

    # Location tracking
    last_ip_address = models.GenericIPAddressField(
        blank=True,
        null=True,
        verbose_name=_("Last IP Address")
    )
    last_location = models.CharField(
        max_length=200,
        blank=True,
        verbose_name=_("Last Location")
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Active")
    )

    notes = models.TextField(
        blank=True,
        verbose_name=_("Notes")
    )

    class Meta:
        verbose_name = _("Device Fingerprint")
        verbose_name_plural = _("Device Fingerprints")
        unique_together = [['user', 'fingerprint_hash']]
        ordering = ['-last_seen_at']
        indexes = [
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['fingerprint_hash']),
            models.Index(fields=['is_trusted']),
        ]

    def __str__(self):
        return f"{self.device_name} - {self.user.get_full_name()}"

    def increment_login(self):
        """Increment login count and update trust score"""
        self.login_count += 1
        # Increase trust score with each successful login (max 100)
        self.trust_score = min(100, self.trust_score + 5)
        self.save(update_fields=['login_count', 'trust_score'])

    def flag_suspicious(self):
        """Decrease trust score due to suspicious activity"""
        self.trust_score = max(0, self.trust_score - 20)
        self.save(update_fields=['trust_score'])