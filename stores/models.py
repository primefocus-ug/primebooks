from math import radians, sin, cos, atan2, sqrt

from accounts.models import AuditLog
from django.db import models
from django.db.models import F
from django.core.validators import RegexValidator, MinValueValidator
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
import uuid
from django.utils import timezone
from datetime import timedelta, datetime
import json
from primebooks.mixins import OfflineIDMixin
from django.conf import settings


# ---------------------------------------------------------------------------
# Utility function — moved out of models to avoid accidental sync HTTP calls
# in request/response cycles. Call this from a background task (e.g. Celery).
# ---------------------------------------------------------------------------

def geocode_address(address_string):
    """
    Geocode an address using OpenStreetMap Nominatim.

    NOTE: This makes a live HTTP request. Do NOT call from within ORM
    operations or request/response cycles where latency is critical.
    Prefer calling from a background task (e.g. Celery).

    Args:
        address_string: Address string to geocode.

    Returns:
        Dict with 'latitude', 'longitude', and 'display_name', or None on failure.
    """
    import requests
    import logging

    logger = logging.getLogger(__name__)

    try:
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            "q": address_string,
            "format": "json",
            "limit": 1,
            "addressdetails": 1,
        }
        headers = {"User-Agent": "PrimeBookStoreApp/1.0"}

        response = requests.get(url, params=params, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()
            if data:
                result = data[0]
                return {
                    "latitude": result["lat"],
                    "longitude": result["lon"],
                    "display_name": result.get("display_name", ""),
                    "address_details": result.get("address", {}),
                }
    except Exception as e:
        logger.error("Geocoding error for address '%s': %s", address_string, str(e))

    return None


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class Store(OfflineIDMixin, models.Model):
    STORE_TYPES = [
        ("MAIN", _("Main Store")),
        ("BRANCH", _("Branch Store")),
        ("WAREHOUSE", _("Warehouse")),
        ("OUTLET", _("Retail Outlet")),
    ]

    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True,
        blank=True,
    )
    company = models.ForeignKey(
        "company.Company",
        on_delete=models.CASCADE,
        related_name="stores",
        verbose_name=_("Company"),
        null=True,
        blank=True,
    )

    staff = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="stores",
        verbose_name=_("Assigned Staff"),
        help_text=_("Users who can access this store"),
    )
    store_managers = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="managed_stores",
        verbose_name=_("Store Managers"),
        help_text=_("Users who can manage this store"),
    )

    accessible_by_all = models.BooleanField(
        default=False,
        verbose_name=_("Accessible by All Company Users"),
        help_text=_("If checked, all users in the company can access this store"),
    )

    name = models.CharField(max_length=255, verbose_name=_("Store Name"))
    code = models.CharField(
        max_length=20,
        unique=True,
        blank=True,
        null=True,
        verbose_name=_("Store Code"),
        help_text=_("Internal identifier for the store"),
    )
    store_type = models.CharField(
        max_length=20,
        choices=STORE_TYPES,
        default="BRANCH",
        verbose_name=_("Store Type"),
    )

    # Identifiers
    nin = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name=_("NIN"),
        help_text=_("National Identification Number"),
    )
    tin = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name=_("TIN"),
        help_text=_("Tax Identification Number"),
    )

    # EFRIS Store Override Configuration
    use_company_efris = models.BooleanField(
        default=True,
        verbose_name=_("Use Company EFRIS Configuration"),
        help_text=_(
            "When checked, uses company-level EFRIS settings. "
            "Uncheck to use store-specific settings."
        ),
    )
    store_efris_private_key = models.TextField(
        blank=True, null=True, verbose_name=_("Store Private Key")
    )
    store_efris_public_certificate = models.TextField(
        blank=True, null=True, verbose_name=_("Store Public Certificate")
    )
    store_efris_key_password = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_("Store Key Password"),
    )
    store_efris_certificate_fingerprint = models.CharField(
        max_length=128,
        blank=True,
        null=True,
        verbose_name=_("Store Certificate Fingerprint"),
    )
    store_efris_is_production = models.BooleanField(
        default=False, verbose_name=_("Store EFRIS Production Mode")
    )
    store_efris_integration_mode = models.CharField(
        max_length=10,
        choices=[("online", "Online Mode"), ("offline", "Offline Mode")],
        default="online",
        verbose_name=_("Store EFRIS Integration Mode"),
    )
    store_auto_fiscalize_sales = models.BooleanField(
        default=True, verbose_name=_("Store Auto-Fiscalize Sales")
    )
    store_auto_sync_products = models.BooleanField(
        default=True, verbose_name=_("Store Auto-Sync Products")
    )
    store_efris_is_active = models.BooleanField(
        default=False, verbose_name=_("Store EFRIS Active")
    )
    store_efris_last_sync = models.DateTimeField(
        blank=True, null=True, verbose_name=_("Store EFRIS Last Sync")
    )

    # Branch behaviour flags
    is_main_branch = models.BooleanField(
        default=False,
        verbose_name=_("Main Branch/Store"),
        help_text=_("Designates this as the primary store for the company"),
    )
    allows_sales = models.BooleanField(default=True, verbose_name=_("Allows Sales"))
    allows_inventory = models.BooleanField(
        default=True, verbose_name=_("Manages Inventory")
    )

    # Manager Information
    manager_name = models.CharField(
        max_length=255, blank=True, verbose_name=_("Store Manager")
    )
    manager_phone = models.CharField(
        max_length=20,
        blank=True,
        validators=[RegexValidator(r"^\+?[0-9]+$", _("Enter a valid phone number."))],
        verbose_name=_("Manager Phone"),
    )

    # Operating Hours
    operating_hours = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Operating hours for each day of the week"),
    )
    timezone = models.CharField(
        max_length=100, blank=True, default="Africa/Kampala"
    )

    # Metadata
    sort_order = models.PositiveIntegerField(
        default=0, help_text=_("Used for ordering stores in lists")
    )
    notes = models.TextField(blank=True, verbose_name=_("Notes"))

    # Location fields
    location = models.CharField(
        max_length=255, blank=True, verbose_name=_("Location/Area")
    )
    # FIX: physical_address made optional (blank=True) so form validation — not
    # the DB — controls the required state, giving users a clean error message.
    physical_address = models.TextField(
        blank=True, verbose_name=_("Physical Address")
    )
    location_gps = models.CharField(
        max_length=100, blank=True, null=True, verbose_name=_("GPS Coordinates")
    )
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, blank=True, null=True
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, blank=True, null=True
    )
    region = models.CharField(
        max_length=100, blank=True, null=True, verbose_name=_("Region/District")
    )

    # Contact fields
    phone = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        validators=[RegexValidator(r"^\+?[0-9]+$", _("Enter a valid phone number."))],
        verbose_name=_("Primary Phone"),
    )
    secondary_phone = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        validators=[RegexValidator(r"^\+?[0-9]+$", _("Enter a valid phone number."))],
        verbose_name=_("Secondary Phone"),
    )
    email = models.EmailField(blank=True, null=True, verbose_name=_("Store Email"))
    logo = models.ImageField(
        upload_to="store-logos/", blank=True, null=True, verbose_name=_("Store Logo")
    )

    # EFRIS fields
    efris_device_number = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name=_("EFRIS Device Number"),
        help_text=_("Device number assigned by URA"),
    )
    device_serial_number = models.CharField(
        max_length=100, blank=True, null=True, verbose_name=_("Device Serial Number")
    )
    efris_enabled = models.BooleanField(
        default=False, verbose_name=_("EFRIS Enabled")
    )
    is_registered_with_efris = models.BooleanField(
        default=False, verbose_name=_("Registered with EFRIS")
    )
    efris_registration_date = models.DateTimeField(
        null=True, blank=True, verbose_name=_("EFRIS Registration Date")
    )
    efris_last_sync = models.DateTimeField(
        blank=True, null=True, verbose_name=_("Last EFRIS Sync")
    )
    last_stock_sync = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Last Stock Sync")
    )

    # EFRIS Settings
    auto_fiscalize_sales = models.BooleanField(
        default=True, verbose_name=_("Auto-Fiscalize Sales")
    )
    allow_manual_fiscalization = models.BooleanField(
        default=True, verbose_name=_("Allow Manual Fiscalization")
    )
    report_stock_movements = models.BooleanField(
        default=True, verbose_name=_("Report Stock Movements to EFRIS")
    )

    # Status
    is_active = models.BooleanField(default=True, verbose_name=_("Active"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created At"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Updated At"))

    # ------------------------------------------------------------------
    # URL / map helpers
    # ------------------------------------------------------------------

    def get_absolute_url(self):
        return reverse("stores:store_detail", kwargs={"pk": self.pk})

    def get_map_url(self):
        if self.latitude is not None and self.longitude is not None:
            return f"https://www.google.com/maps?q={self.latitude},{self.longitude}"
        return None

    def get_directions_url(self, from_lat=None, from_lng=None):
        if self.latitude is None or self.longitude is None:
            return None
        if from_lat is not None and from_lng is not None:
            return (
                f"https://www.google.com/maps/dir/"
                f"{from_lat},{from_lng}/{self.latitude},{self.longitude}"
            )
        return (
            f"https://www.google.com/maps/dir/?api=1"
            f"&destination={self.latitude},{self.longitude}"
        )

    def distance_to(self, lat, lon):
        """
        Calculate distance to another point in kilometres using the
        Haversine formula.
        """
        if self.latitude is None or self.longitude is None:
            return None

        R = 6371.0
        lat1 = radians(float(self.latitude))
        lon1 = radians(float(self.longitude))
        lat2 = radians(float(lat))
        lon2 = radians(float(lon))
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))
        return round(R * c, 2)

    @classmethod
    def find_nearest_stores(cls, lat, lon, limit=5, max_distance_km=None):
        """Find the nearest active stores to a given location."""
        stores_with_coords = cls.objects.filter(
            is_active=True,
            latitude__isnull=False,
            longitude__isnull=False,
        )
        stores_with_distance = []
        for store in stores_with_coords:
            distance = store.distance_to(lat, lon)
            if distance is not None:
                if max_distance_km is None or distance <= max_distance_km:
                    stores_with_distance.append((store, distance))
        stores_with_distance.sort(key=lambda x: x[1])
        return stores_with_distance[:limit]

    # ------------------------------------------------------------------
    # Inventory / sales summaries
    # ------------------------------------------------------------------

    def get_inventory_summary(self):
        from django.db.models import Sum, Count, Q, F as _F

        inventory = self.inventory_items.select_related("product")
        return {
            "total_products": inventory.count(),
            "total_quantity": inventory.aggregate(Sum("quantity"))["quantity__sum"] or 0,
            "low_stock_count": inventory.filter(
                quantity__lte=_F("low_stock_threshold")
            ).count(),
            "out_of_stock_count": inventory.filter(quantity=0).count(),
            "total_value": inventory.aggregate(
                total=Sum(_F("quantity") * _F("product__cost_price"))
            )["total"]
            or 0,
        }

    def get_sales_summary(self, days=30):
        from django.db.models import Sum, Count, Avg

        start_date = timezone.now() - timedelta(days=days)
        try:
            sales = self.sales.filter(created_at__gte=start_date)
        except Exception:
            try:
                sales = self.sales.filter(date__gte=start_date)
            except Exception:
                sales = self.sales.all()

        return {
            "total_sales": sales.count(),
            "total_revenue": sales.aggregate(Sum("total_amount"))["total_amount__sum"] or 0,
            "average_sale": sales.aggregate(Avg("total_amount"))["total_amount__avg"] or 0,
            "paid_sales": sales.filter(payment_status="PAID").count(),
            "pending_sales": sales.filter(payment_status="PENDING").count(),
        }

    # ------------------------------------------------------------------
    # EFRIS configuration helpers
    # ------------------------------------------------------------------

    def get_company_efris_config(self):
        """
        Fetch company EFRIS configuration.
        Returns a dictionary of company EFRIS values, or {} on failure.
        """
        if not self.company_id:
            return {}

        import logging
        logger = logging.getLogger(__name__)

        try:
            from django_tenants.utils import schema_context
            from company.models import Company
            from efris.models import EFRISConfiguration

            config = {}

            with schema_context("public"):
                company = Company.objects.get(company_id=self.company_id)
                schema_name = company.schema_name
                has_cert_data = (
                    hasattr(company, "efris_certificate_data")
                    and isinstance(company.efris_certificate_data, dict)
                    and bool(company.efris_certificate_data)
                )
                efris_cert_data = (
                    company.efris_certificate_data
                    if has_cert_data
                    else {}
                )
                config.update(
                    {
                        "tin": company.tin or "",
                        "nin": company.nin or "",
                        "email": company.email or "",
                        "phone": company.phone or "",
                        "business_address": company.physical_address or "",
                        "business_name": company.trading_name or company.name or "",
                        "taxpayer_name": company.name or "",
                        "efris_enabled": company.efris_enabled,
                        "efris_is_active": company.efris_is_active,
                        "efris_device_number": company.efris_device_number or "",
                        "efris_is_production": company.efris_is_production,
                        "efris_integration_mode": company.efris_integration_mode,
                        "efris_auto_fiscalize_sales": company.efris_auto_fiscalize_sales,
                        "efris_auto_sync_products": company.efris_auto_sync_products,
                    }
                )

            # Fetch tenant-schema EFRIS config outside the public schema context
            if schema_name:
                with schema_context(schema_name):
                    try:
                        efris_config = EFRISConfiguration.objects.filter(
                            company=self.company
                        ).first()
                        if efris_config:
                            config.update(
                                {
                                    "efris_private_key": efris_config.private_key or "",
                                    "efris_public_certificate": efris_config.public_certificate or "",
                                    "efris_key_password": efris_config.key_password or "",
                                    "efris_certificate_fingerprint": efris_config.certificate_fingerprint or "",
                                    "efris_certificate_expires_at": efris_config.certificate_expires_at,
                                    "efris_environment": efris_config.environment or "sandbox",
                                    "efris_mode": efris_config.mode or "online",
                                    "efris_device_mac": efris_config.device_mac or "",
                                    "efris_app_id": efris_config.app_id or "",
                                    "efris_version": efris_config.version or "",
                                    "efris_is_initialized": efris_config.is_initialized,
                                    "efris_timeout_seconds": efris_config.timeout_seconds or 30,
                                    "efris_max_retry_attempts": efris_config.max_retry_attempts or 3,
                                    "efris_auto_sync_enabled": efris_config.auto_sync_enabled,
                                    "efris_auto_fiscalize": efris_config.auto_fiscalize,
                                    "efris_sync_interval_minutes": efris_config.sync_interval_minutes or 60,
                                }
                            )
                    except Exception as tenant_error:
                        # Log without exposing internal details beyond the store id
                        logger.warning(
                            "Could not fetch EFRIS configuration for store %s: %s",
                            self.id,
                            type(tenant_error).__name__,
                        )
                        if has_cert_data:
                            config.update(
                                {
                                    "efris_private_key": efris_cert_data.get("private_key", ""),
                                    "efris_public_certificate": efris_cert_data.get("public_certificate", ""),
                                    "efris_key_password": efris_cert_data.get("key_password", ""),
                                    "efris_certificate_fingerprint": efris_cert_data.get("certificate_fingerprint", ""),
                                }
                            )

            return config

        except Exception:
            logger.error(
                "Error fetching company EFRIS config for store %s", self.id
            )
            return {}

    def get_efris_value(self, field_name, company_value=None):
        """Return EFRIS value applying store-override logic."""
        if self.use_company_efris:
            return company_value

        if field_name == "tin":
            store_field_name = "tin"
        elif field_name == "efris_device_number":
            store_field_name = "efris_device_number"
        elif field_name == "efris_certificate_fingerprint":
            store_field_name = "store_efris_certificate_fingerprint"
        else:
            store_field_name = f"store_{field_name}"

        if hasattr(self, store_field_name):
            store_value = getattr(self, store_field_name)
            if store_value not in (None, "", [], {}):
                return store_value

        return company_value

    @property
    def effective_efris_config(self):
        """
        Returns the effective EFRIS configuration for this store.
        Uses store-specific values when available and enabled.
        """
        company_config = self.get_company_efris_config()
        effective_config = {
            "tin": self.get_efris_value("tin", company_config.get("tin")),
            "nin": self.get_efris_value("nin", company_config.get("nin")),
            "device_number": self.get_efris_value("efris_device_number", company_config.get("efris_device_number")),
            "private_key": self.get_efris_value("efris_private_key", company_config.get("efris_private_key")),
            "public_certificate": self.get_efris_value("efris_public_certificate", company_config.get("efris_public_certificate")),
            "key_password": self.get_efris_value("efris_key_password", company_config.get("efris_key_password")),
            "certificate_fingerprint": self.get_efris_value("efris_certificate_fingerprint", company_config.get("efris_certificate_fingerprint")),
            "is_production": self.get_efris_value("efris_is_production", company_config.get("efris_is_production")),
            "integration_mode": self.get_efris_value("efris_integration_mode", company_config.get("efris_integration_mode")),
            "auto_fiscalize_sales": self.get_efris_value("auto_fiscalize_sales", company_config.get("efris_auto_fiscalize_sales")),
            "auto_sync_products": self.get_efris_value("auto_sync_products", company_config.get("efris_auto_sync_products")),
            "is_active": self.get_efris_value("efris_is_active", company_config.get("efris_is_active")),
            "enabled": self.get_efris_value("efris_enabled", company_config.get("efris_enabled")),
            "last_sync": self.get_efris_value("efris_last_sync", company_config.get("efris_last_sync")),
            "email": self.email or company_config.get("email"),
            "phone": self.phone or company_config.get("phone"),
            "business_address": self.physical_address or company_config.get("business_address"),
            "store_name": self.name,
            "store_code": self.code,
            "store_id": self.id,
            "use_company_efris": self.use_company_efris,
            "config_source": "company" if self.use_company_efris else "store",
        }
        effective_config["business_name"] = company_config.get("business_name", "")
        effective_config["taxpayer_name"] = company_config.get("taxpayer_name", "")
        return effective_config

    @property
    def can_fiscalize(self):
        """Check whether this store can fiscalize transactions."""
        config = self.effective_efris_config
        required_fields = [
            config.get("enabled"),
            config.get("is_active"),
            config.get("device_number"),
            config.get("tin"),
            config.get("private_key"),
            config.get("public_certificate"),
        ]
        return all(required_fields) and self.is_active and self.allows_sales

    @property
    def efris_config_status(self):
        """Return detailed EFRIS configuration status dict."""
        config = self.effective_efris_config
        status = {
            "configured": False,
            "config_source": config.get("config_source"),
            "missing_fields": [],
            "warnings": [],
        }
        required_fields = {
            "tin": "TIN Number",
            "device_number": "Device Number",
            "private_key": "Private Key",
            "public_certificate": "Public Certificate",
            "email": "Email Address",
            "phone": "Phone Number",
        }
        for field, label in required_fields.items():
            if not config.get(field):
                status["missing_fields"].append(label)
        if not config.get("business_address"):
            status["warnings"].append("Business address not set")
        if not config.get("key_password") and config.get("private_key"):
            status["warnings"].append("Private key may not be encrypted")
        status["configured"] = len(status["missing_fields"]) == 0
        return status

    def validate_efris_configuration(self):
        """
        Validate EFRIS configuration and return (is_valid, errors_list).

        Evaluates store-specific fields by temporarily using a copy of the
        config rather than mutating instance state, so the instance is never
        left in an inconsistent state if an exception occurs.
        """
        # FIX: Build a snapshot config evaluated as store-specific without
        # mutating self.use_company_efris — avoids non-thread-safe mutation.
        original_flag = self.use_company_efris
        try:
            self.use_company_efris = False
            config = self.effective_efris_config
        finally:
            self.use_company_efris = original_flag

        errors = []

        if not config.get("enabled"):
            return True, []  # EFRIS disabled — not an error

        if not config.get("tin"):
            errors.append("TIN number is required for EFRIS integration")
        if not config.get("device_number"):
            errors.append("EFRIS device number is required")
        if not config.get("private_key"):
            errors.append("Private key is required for EFRIS integration")
        if not config.get("public_certificate"):
            errors.append("Public certificate is required for EFRIS integration")
        if not config.get("email"):
            errors.append("Email address is required for EFRIS integration")
        if not config.get("phone"):
            errors.append("Phone number is required for EFRIS integration")
        fingerprint = config.get("certificate_fingerprint")
        if fingerprint and len(fingerprint) not in (64, 128):
            errors.append("Invalid certificate fingerprint format")

        return len(errors) == 0, errors

    def switch_to_company_efris(self):
        """Switch to using company EFRIS configuration."""
        self.use_company_efris = True
        self.save(update_fields=["use_company_efris", "updated_at"])

    def switch_to_store_efris(self):
        """
        Switch to store-specific EFRIS configuration.
        Raises ValueError if required store fields are missing.
        """
        is_valid, errors = self.validate_efris_configuration()
        if not is_valid:
            raise ValueError(
                f"Cannot switch to store EFRIS config. Missing: {', '.join(errors)}"
            )
        self.use_company_efris = False
        self.save(update_fields=["use_company_efris", "updated_at"])

    def copy_company_efris_to_store(self):
        """Copy company EFRIS configuration into store-specific fields."""
        company_config = self.get_company_efris_config()
        self.tin = company_config.get("tin")
        self.efris_device_number = company_config.get("efris_device_number")
        self.store_efris_private_key = company_config.get("efris_private_key")
        self.store_efris_public_certificate = company_config.get("efris_public_certificate")
        self.store_efris_key_password = company_config.get("efris_key_password")
        self.store_efris_certificate_fingerprint = company_config.get("efris_certificate_fingerprint")
        self.store_efris_is_production = company_config.get("efris_is_production")
        self.store_efris_integration_mode = company_config.get("efris_integration_mode")
        self.store_auto_fiscalize_sales = company_config.get("efris_auto_fiscalize_sales")
        self.store_auto_sync_products = company_config.get("efris_auto_sync_products")
        self.store_efris_is_active = company_config.get("efris_is_active")
        self.save()

    # ------------------------------------------------------------------
    # Device / staff helpers
    # ------------------------------------------------------------------

    def get_device_summary(self):
        devices = self.devices.filter(is_active=True)
        return {
            "total_devices": devices.count(),
            "efris_devices": devices.filter(is_efris_linked=True).count(),
            "pos_devices": devices.filter(device_type="POS").count(),
            "fiscal_devices": devices.filter(device_type="EFRIS_FISCAL").count(),
        }

    def get_staff_count(self):
        return self.staff.filter(is_active=True).count()

    # ------------------------------------------------------------------
    # Coordinate helpers
    # ------------------------------------------------------------------

    def validate_coordinates(self):
        """
        Validate that coordinates fall within Uganda's approximate bounding box.
        Returns (is_valid: bool, message: str).
        """
        if self.latitude is None or self.longitude is None:
            return True, "No coordinates set"
        lat = float(self.latitude)
        lon = float(self.longitude)
        if -2.0 <= lat <= 5.0 and 29.0 <= lon <= 36.0:
            return True, "Coordinates valid"
        return False, "Coordinates appear to be outside Uganda"

    @property
    def has_coordinates(self):
        return self.latitude is not None and self.longitude is not None

    @property
    def coordinate_string(self):
        if self.has_coordinates:
            return f"{self.latitude}, {self.longitude}"
        return "No coordinates"

    # ------------------------------------------------------------------
    # Status properties
    # ------------------------------------------------------------------

    @property
    def store_status_badge(self):
        if not self.is_active:
            return "danger"
        elif self.is_main_branch:
            return "primary"
        elif self.efris_enabled:
            return "success"
        return "secondary"

    @property
    def store_status_text(self):
        if not self.is_active:
            return "Inactive"
        elif self.is_main_branch:
            return "Main Branch"
        elif self.efris_enabled:
            return "EFRIS Enabled"
        return "Active"

    @property
    def efris_status(self):
        if not self.efris_enabled:
            return "disabled"
        elif not self.efris_device_number:
            return "no_device"
        elif not self.is_registered_with_efris:
            return "unregistered"
        elif self.can_fiscalize:
            return "active"
        return "inactive"

    # ------------------------------------------------------------------
    # Nearby stores
    # ------------------------------------------------------------------

    def get_nearby_stores(self, radius_km=50, limit=10):
        """
        Return (store, distance_km) tuples for stores within radius_km,
        excluding self.
        """
        if not self.has_coordinates:
            return []
        all_nearby = Store.find_nearest_stores(
            float(self.latitude),
            float(self.longitude),
            limit=limit + 1,
            max_distance_km=radius_km,
        )
        return [
            (store, dist) for store, dist in all_nearby if store.pk != self.pk
        ][:limit]

    def format_address_for_geocoding(self):
        parts = [p for p in [self.physical_address, self.location, self.region] if p]
        parts.append("Uganda")
        return ", ".join(parts)

    def get_performance_metrics(self):
        return {
            "inventory": self.get_inventory_summary(),
            "sales": self.get_sales_summary(),
            "devices": self.get_device_summary(),
            "staff_count": self.get_staff_count(),
            "efris_status": self.efris_status,
            "can_fiscalize": self.can_fiscalize,
            "is_operational": self.is_active and self.allows_sales,
        }

    def is_open_now(self):
        """Check if store is currently open based on operating_hours JSON."""
        if not self.operating_hours:
            return True
        now = timezone.now()
        day_name = now.strftime("%A").lower()
        day_hours = self.operating_hours.get(day_name)
        if not day_hours or not day_hours.get("is_open", True):
            return False
        current_time = now.time()
        open_time = day_hours.get("open_time")
        close_time = day_hours.get("close_time")
        if open_time and close_time:
            open_dt = datetime.strptime(open_time, "%H:%M").time()
            close_dt = datetime.strptime(close_time, "%H:%M").time()
            return open_dt <= current_time <= close_dt
        return True

    # ------------------------------------------------------------------
    # Misc properties / backward-compat
    # ------------------------------------------------------------------

    @property
    def full_address(self):
        return ", ".join(filter(None, [self.physical_address, self.location]))

    @property
    def tax_details(self):
        return {
            "store_name": self.name,
            "store_address": self.physical_address,
            "store_phone": self.phone,
            "efris_device_number": self.efris_device_number,
            "tin": self.tin,
            "nin": self.nin,
        }

    # Backward compatibility
    @property
    def branch_name(self):
        return self.name

    @property
    def branch_code(self):
        return self.code

    # ------------------------------------------------------------------
    # save() — thread-safety note: the main-branch deduplication uses
    # application-level logic.  For strict uniqueness under high concurrency
    # add a partial unique index or use select_for_update() in a transaction.
    # ------------------------------------------------------------------

    def save(self, *args, **kwargs):
        skip_main_branch_update = kwargs.pop("skip_main_branch_update", False)

        if not self.code:
            self.code = f"ST-{uuid.uuid4().hex[:6].upper()}"

        if self.allows_sales is None:
            self.allows_sales = True
        if self.allows_inventory is None:
            self.allows_inventory = True

        is_new = self._state.adding

        if not skip_main_branch_update and self.is_main_branch and self.company:
            if not is_new:
                try:
                    Store.objects.filter(
                        company=self.company, is_main_branch=True
                    ).exclude(id=self.id).update(is_main_branch=False)
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(
                        "Could not update other stores: %s", e
                    )

        super().save(*args, **kwargs)

        if not skip_main_branch_update and is_new and self.is_main_branch and self.company:
            try:
                Store.objects.filter(
                    company=self.company, is_main_branch=True
                ).exclude(id=self.id).update(is_main_branch=False)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    "Could not update other stores after create: %s", e
                )

    def __str__(self):
        company_name = self.company.name if self.company else "No Company"
        return f"{company_name} - {self.name}"

    class Meta:
        verbose_name = _("Store")
        verbose_name_plural = _("Stores")
        ordering = ["-is_main_branch", "sort_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "code"],
                name="unique_store_code_per_company",
            ),
            models.UniqueConstraint(
                fields=["efris_device_number"],
                condition=models.Q(efris_device_number__isnull=False),
                name="unique_efris_device_number",
            ),
        ]
        indexes = [
            models.Index(fields=["company", "is_active"]),
            models.Index(fields=["is_main_branch"]),
            models.Index(fields=["company", "store_type"]),
            models.Index(fields=["latitude", "longitude"]),
            models.Index(fields=["region"]),
        ]


# ---------------------------------------------------------------------------
# StoreAccess
# ---------------------------------------------------------------------------

class StoreAccess(OfflineIDMixin, models.Model):
    """Detailed store access control with per-permission granularity."""

    ACCESS_LEVELS = [
        ("view", _("View Only")),
        ("staff", _("Staff Access")),
        ("manager", _("Manager Access")),
        ("admin", _("Admin Access")),
    ]

    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True,
        blank=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="store_access_permissions",
        verbose_name=_("User"),
    )
    store = models.ForeignKey(
        "Store",
        on_delete=models.CASCADE,
        related_name="access_permissions",
        verbose_name=_("Store"),
    )
    access_level = models.CharField(
        max_length=20,
        choices=ACCESS_LEVELS,
        default="staff",
        verbose_name=_("Access Level"),
    )

    can_view_sales = models.BooleanField(default=True)
    can_create_sales = models.BooleanField(default=True)
    can_view_inventory = models.BooleanField(default=True)
    can_manage_inventory = models.BooleanField(default=False)
    can_view_reports = models.BooleanField(default=False)
    can_fiscalize = models.BooleanField(default=False)
    can_manage_staff = models.BooleanField(default=False)

    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="store_access_grants",
        verbose_name=_("Granted By"),
    )
    granted_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return (
            f"{self.user.get_full_name()} - {self.store.name} "
            f"({self.get_access_level_display()})"
        )

    def revoke(self, revoked_by=None):
        """Revoke this store access record."""
        self.is_active = False
        self.revoked_at = timezone.now()
        self.save(update_fields=["is_active", "revoked_at"])
        AuditLog.log(
            action="store_access_revoked",
            user=revoked_by,
            description=(
                f"Revoked {self.user.get_full_name()}'s access to {self.store.name}"
            ),
            store=self.store,
            metadata={
                "affected_user_id": self.user.id,
                "access_level": self.access_level,
            },
        )

    class Meta:
        verbose_name = _("Store Access Permission")
        verbose_name_plural = _("Store Access Permissions")
        unique_together = [["user", "store"]]
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["store", "is_active"]),
            models.Index(fields=["access_level", "is_active"]),
        ]


# ---------------------------------------------------------------------------
# StoreOperatingHours
# ---------------------------------------------------------------------------

class StoreOperatingHours(OfflineIDMixin, models.Model):
    DAYS_OF_WEEK = [
        (0, _("Monday")),
        (1, _("Tuesday")),
        (2, _("Wednesday")),
        (3, _("Thursday")),
        (4, _("Friday")),
        (5, _("Saturday")),
        (6, _("Sunday")),
    ]

    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True,
        blank=True,
    )
    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name="operating_hours_detailed",
        verbose_name=_("Store"),
    )
    day = models.IntegerField(choices=DAYS_OF_WEEK, verbose_name=_("Day of Week"))
    opening_time = models.TimeField(verbose_name=_("Opening Time"))
    closing_time = models.TimeField(verbose_name=_("Closing Time"))
    is_closed = models.BooleanField(default=False, verbose_name=_("Closed All Day"))

    def __str__(self):
        if self.is_closed:
            return f"{self.store.name} - {self.get_day_display()}: Closed"
        return (
            f"{self.store.name} - {self.get_day_display()}: "
            f"{self.opening_time} to {self.closing_time}"
        )

    class Meta:
        verbose_name = _("Operating Hour")
        verbose_name_plural = _("Operating Hours")
        ordering = ["day"]
        constraints = [
            models.UniqueConstraint(fields=["store", "day"], name="unique_store_day")
        ]


# ---------------------------------------------------------------------------
# StoreDevice
# ---------------------------------------------------------------------------

class StoreDevice(OfflineIDMixin, models.Model):
    DEVICE_TYPES = [
        ("POS", _("Point of Sale")),
        ("INVOICE", _("Invoice Printer")),
        ("SCANNER", _("Barcode Scanner")),
        ("EFRIS_FISCAL", _("EFRIS Fiscal Device")),
        ("OTHER", _("Other Device")),
    ]

    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True,
        blank=True,
    )
    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.CASCADE,
        related_name="devices",
        verbose_name=_("Store"),
    )
    name = models.CharField(max_length=100, verbose_name=_("Device Name"))
    device_number = models.CharField(
        max_length=50,
        unique=True,
        verbose_name=_("Device Number"),
        help_text=_("Device identifier (URA assigned for fiscal devices)"),
    )
    device_type = models.CharField(
        max_length=20,
        choices=DEVICE_TYPES,
        default="POS",
        verbose_name=_("Device Type"),
    )
    serial_number = models.CharField(
        max_length=100, unique=True, verbose_name=_("Serial Number")
    )
    mac_address = models.CharField(
        max_length=17,
        blank=True,
        null=True,
        verbose_name=_("MAC Address"),
        help_text=_("Hardware MAC address for dedicated terminals"),
    )
    hardware_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_("Hardware ID"),
        help_text=_("Unique hardware identifier"),
    )
    is_active = models.BooleanField(default=True, verbose_name=_("Active"))
    is_efris_linked = models.BooleanField(
        default=False,
        verbose_name=_("EFRIS Linked"),
        help_text=_("Is this device linked to EFRIS system"),
    )
    require_approval = models.BooleanField(
        default=True,
        verbose_name=_("Require Approval"),
        help_text=_("Require admin approval before use"),
    )
    max_concurrent_users = models.PositiveIntegerField(
        default=3,
        verbose_name=_("Max Concurrent Users"),
        help_text=_("Maximum number of users that can use this device simultaneously"),
    )
    registered_at = models.DateTimeField(
        auto_now_add=True, verbose_name=_("Registered At")
    )
    last_maintenance = models.DateTimeField(
        blank=True, null=True, verbose_name=_("Last Maintenance")
    )
    last_seen_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name=_("Last Seen"),
        help_text=_("Last time this device was used"),
    )
    notes = models.TextField(blank=True, null=True, verbose_name=_("Notes"))

    def __str__(self):
        return f"{self.name} ({self.device_number}) - {self.store.name}"

    @property
    def is_fiscal_device(self):
        return self.device_type == "EFRIS_FISCAL" or self.is_efris_linked

    @property
    def active_sessions_count(self):
        return self.device_sessions.filter(
            is_active=True, expires_at__gt=timezone.now()
        ).count()

    @property
    def is_at_capacity(self):
        return self.active_sessions_count >= self.max_concurrent_users

    def update_last_seen(self):
        self.last_seen_at = timezone.now()
        self.save(update_fields=["last_seen_at"])

    class Meta:
        verbose_name = _("Store Device")
        verbose_name_plural = _("Store Devices")
        ordering = ["-registered_at"]
        indexes = [
            models.Index(fields=["store", "is_active"]),
            models.Index(fields=["device_type", "is_active"]),
            models.Index(fields=["mac_address"]),
            models.Index(fields=["hardware_id"]),
        ]


# ---------------------------------------------------------------------------
# UserDeviceSession
# ---------------------------------------------------------------------------

class UserDeviceSession(OfflineIDMixin, models.Model):
    """Track active user sessions on devices with fingerprinting."""

    SESSION_STATUS = [
        ("ACTIVE", _("Active")),
        ("EXPIRED", _("Expired")),
        ("LOGGED_OUT", _("Logged Out")),
        ("FORCE_CLOSED", _("Force Closed")),
        ("SUSPICIOUS", _("Suspicious")),
    ]

    sync_id = models.UUIDField(
        default=uuid.uuid4, unique=True, db_index=True, editable=False,
        null=True, blank=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="device_sessions", verbose_name=_("User"),
    )
    store = models.ForeignKey(
        "stores.Store", on_delete=models.CASCADE,
        related_name="user_sessions", verbose_name=_("Store"),
    )
    store_device = models.ForeignKey(
        StoreDevice, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="device_sessions", verbose_name=_("Store Device"),
        help_text=_("Physical POS device if applicable"),
    )
    session_key = models.CharField(
        max_length=100, unique=True, verbose_name=_("Session Key")
    )
    status = models.CharField(
        max_length=20, choices=SESSION_STATUS, default="ACTIVE",
        verbose_name=_("Status"),
    )
    is_active = models.BooleanField(default=True, verbose_name=_("Is Active"))
    device_fingerprint = models.CharField(
        max_length=64, db_index=True, verbose_name=_("Device Fingerprint"),
        help_text=_("Unique hash identifying this device"),
    )
    browser_name = models.CharField(max_length=50, blank=True, verbose_name=_("Browser Name"))
    browser_version = models.CharField(max_length=20, blank=True, verbose_name=_("Browser Version"))
    os_name = models.CharField(max_length=50, blank=True, verbose_name=_("OS Name"))
    os_version = models.CharField(max_length=20, blank=True, verbose_name=_("OS Version"))
    ip_address = models.GenericIPAddressField(verbose_name=_("IP Address"))
    user_agent = models.TextField(verbose_name=_("User Agent String"))
    screen_resolution = models.CharField(
        max_length=20, blank=True, verbose_name=_("Screen Resolution"),
        help_text=_("Format: 1920x1080"),
    )
    timezone = models.CharField(
        max_length=100, blank=True, default="UTC", verbose_name=_("Timezone")
    )
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, blank=True, null=True, verbose_name=_("Latitude")
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, blank=True, null=True, verbose_name=_("Longitude")
    )
    location_accuracy = models.FloatField(
        blank=True, null=True, verbose_name=_("Location Accuracy (meters)")
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Login Time"))
    last_activity_at = models.DateTimeField(auto_now=True, verbose_name=_("Last Activity"))
    expires_at = models.DateTimeField(verbose_name=_("Expires At"))
    logged_out_at = models.DateTimeField(blank=True, null=True, verbose_name=_("Logout Time"))
    is_new_device = models.BooleanField(default=False, verbose_name=_("New Device"))
    is_suspicious = models.BooleanField(default=False, verbose_name=_("Suspicious Activity"))
    suspicious_reason = models.TextField(blank=True, verbose_name=_("Suspicious Reason"))
    security_alerts_count = models.PositiveIntegerField(
        default=0, verbose_name=_("Security Alerts Count")
    )
    metadata = models.JSONField(default=dict, blank=True, verbose_name=_("Additional Metadata"))

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(hours=24)
        super().save(*args, **kwargs)

    def __str__(self):
        device_info = f" on {self.store_device.name}" if self.store_device else ""
        return (
            f"{self.user.get_full_name()} - {self.browser_name}"
            f"{device_info} ({self.get_status_display()})"
        )

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def session_duration(self):
        if not self.created_at:
            return timedelta(0)
        if self.logged_out_at:
            return self.logged_out_at - self.created_at
        return timezone.now() - self.created_at

    @property
    def location_string(self):
        if self.latitude is not None and self.longitude is not None:
            return f"{self.latitude}, {self.longitude}"
        return None

    def extend_session(self, hours=24):
        self.expires_at = timezone.now() + timedelta(hours=hours)
        self.save(update_fields=["expires_at"])

    def terminate(self, reason="LOGGED_OUT"):
        self.is_active = False
        self.logged_out_at = timezone.now()
        self.status = reason
        self.save(update_fields=["is_active", "logged_out_at", "status"])

    def flag_suspicious(self, reason):
        self.is_suspicious = True
        self.suspicious_reason = reason
        self.security_alerts_count += 1
        self.status = "SUSPICIOUS"
        self.save(
            update_fields=[
                "is_suspicious", "suspicious_reason",
                "security_alerts_count", "status",
            ]
        )

    class Meta:
        verbose_name = _("User Device Session")
        verbose_name_plural = _("User Device Sessions")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["store", "is_active"]),
            models.Index(fields=["store_device", "is_active"]),
            models.Index(fields=["device_fingerprint"]),
            models.Index(fields=["ip_address", "created_at"]),
            models.Index(fields=["is_suspicious", "is_active"]),
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["expires_at"]),
        ]


# ---------------------------------------------------------------------------
# DeviceOperatorLog
# ---------------------------------------------------------------------------

class DeviceOperatorLog(OfflineIDMixin, models.Model):
    ACTION_CHOICES = [
        ("LOGIN", _("Device Login")),
        ("LOGOUT", _("Device Logout")),
        ("SALE", _("Sale Transaction")),
        ("REFUND", _("Refund Transaction")),
        ("FISCALIZE", _("Manual Fiscalization")),
        ("STOCK_UPDATE", _("Stock Update")),
        ("EFRIS_SYNC", _("EFRIS Synchronization")),
        ("MAINTENANCE", _("Device Maintenance")),
        ("SESSION_EXTENDED", _("Session Extended")),
        ("SESSION_TERMINATED", _("Session Terminated")),
        ("SUSPICIOUS_ACTIVITY", _("Suspicious Activity Detected")),
        ("ERROR", _("Error Occurred")),
        ("OTHER", _("Other Action")),
    ]

    sync_id = models.UUIDField(
        default=uuid.uuid4, unique=True, db_index=True, editable=False,
        null=True, blank=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="device_logs", verbose_name=_("User"),
    )
    action = models.CharField(
        max_length=50, choices=ACTION_CHOICES, verbose_name=_("Action")
    )
    device = models.ForeignKey(
        StoreDevice, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="operator_logs", verbose_name=_("Device"),
    )
    store = models.ForeignKey(
        "stores.Store", on_delete=models.CASCADE,
        related_name="device_logs", verbose_name=_("Store"),
    )
    session = models.ForeignKey(
        UserDeviceSession, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="action_logs", verbose_name=_("Session"),
    )
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name=_("Timestamp"))
    ip_address = models.GenericIPAddressField(blank=True, null=True, verbose_name=_("IP Address"))
    details = models.JSONField(default=dict, verbose_name=_("Details"))
    is_efris_related = models.BooleanField(default=False, verbose_name=_("EFRIS Related"))
    success = models.BooleanField(default=True, verbose_name=_("Success"))
    error_message = models.TextField(blank=True, verbose_name=_("Error Message"))

    def __str__(self):
        device_info = f" on {self.device.name}" if self.device else ""
        return f"{self.user} - {self.get_action_display()}{device_info} at {self.timestamp}"

    class Meta:
        verbose_name = _("Device Operator Log")
        verbose_name_plural = _("Device Operator Logs")
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["store", "timestamp"]),
            models.Index(fields=["user", "timestamp"]),
            models.Index(fields=["device", "timestamp"]),
            models.Index(fields=["action", "timestamp"]),
            models.Index(fields=["is_efris_related", "timestamp"]),
            models.Index(fields=["session", "timestamp"]),
            models.Index(fields=["success", "timestamp"]),
        ]


# ---------------------------------------------------------------------------
# SecurityAlert
# ---------------------------------------------------------------------------

class SecurityAlert(OfflineIDMixin, models.Model):
    """Track security alerts and suspicious activities."""

    ALERT_TYPES = [
        ("NEW_DEVICE", _("New Device Login")),
        ("NEW_LOCATION", _("New Location Login")),
        ("MULTIPLE_FAILED_LOGINS", _("Multiple Failed Login Attempts")),
        ("CONCURRENT_SESSIONS_EXCEEDED", _("Too Many Concurrent Sessions")),
        ("UNUSUAL_ACTIVITY", _("Unusual Activity Pattern")),
        ("IP_CHANGE", _("IP Address Changed During Session")),
        ("SUSPICIOUS_TRANSACTION", _("Suspicious Transaction")),
        ("DEVICE_CAPACITY_EXCEEDED", _("Device Capacity Exceeded")),
        ("OTHER", _("Other Security Concern")),
    ]
    SEVERITY_LEVELS = [
        ("LOW", _("Low")),
        ("MEDIUM", _("Medium")),
        ("HIGH", _("High")),
        ("CRITICAL", _("Critical")),
    ]
    STATUS_CHOICES = [
        ("OPEN", _("Open")),
        ("INVESTIGATING", _("Investigating")),
        ("RESOLVED", _("Resolved")),
        ("FALSE_POSITIVE", _("False Positive")),
        ("IGNORED", _("Ignored")),
    ]

    sync_id = models.UUIDField(
        default=uuid.uuid4, unique=True, db_index=True, editable=False,
        null=True, blank=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="security_alerts", verbose_name=_("User"),
    )
    store = models.ForeignKey(
        "stores.Store", on_delete=models.CASCADE,
        related_name="security_alerts", verbose_name=_("Store"),
    )
    session = models.ForeignKey(
        UserDeviceSession, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="security_alerts", verbose_name=_("Session"),
    )
    device = models.ForeignKey(
        StoreDevice, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="security_alerts", verbose_name=_("Device"),
    )
    alert_type = models.CharField(max_length=50, choices=ALERT_TYPES, verbose_name=_("Alert Type"))
    severity = models.CharField(
        max_length=20, choices=SEVERITY_LEVELS, default="MEDIUM", verbose_name=_("Severity")
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="OPEN", verbose_name=_("Status")
    )
    title = models.CharField(max_length=200, verbose_name=_("Alert Title"))
    description = models.TextField(verbose_name=_("Description"))
    ip_address = models.GenericIPAddressField(blank=True, null=True, verbose_name=_("IP Address"))
    alert_data = models.JSONField(default=dict, verbose_name=_("Alert Data"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created At"))
    resolved_at = models.DateTimeField(blank=True, null=True, verbose_name=_("Resolved At"))
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="resolved_alerts", verbose_name=_("Resolved By"),
    )
    resolution_notes = models.TextField(blank=True, verbose_name=_("Resolution Notes"))
    notified = models.BooleanField(default=False, verbose_name=_("Admin Notified"))
    notified_at = models.DateTimeField(blank=True, null=True, verbose_name=_("Notified At"))

    def __str__(self):
        return (
            f"{self.get_alert_type_display()} - {self.user} "
            f"({self.get_severity_display()})"
        )

    def resolve(self, resolved_by, notes=""):
        self.status = "RESOLVED"
        self.resolved_at = timezone.now()
        self.resolved_by = resolved_by
        self.resolution_notes = notes
        self.save(update_fields=["status", "resolved_at", "resolved_by", "resolution_notes"])

    def mark_false_positive(self, resolved_by, notes=""):
        self.status = "FALSE_POSITIVE"
        self.resolved_at = timezone.now()
        self.resolved_by = resolved_by
        self.resolution_notes = notes
        self.save(update_fields=["status", "resolved_at", "resolved_by", "resolution_notes"])

    class Meta:
        verbose_name = _("Security Alert")
        verbose_name_plural = _("Security Alerts")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["store", "status"]),
            models.Index(fields=["alert_type", "status"]),
            models.Index(fields=["severity", "status"]),
            models.Index(fields=["created_at", "status"]),
            models.Index(fields=["notified", "status"]),
        ]


# ---------------------------------------------------------------------------
# DeviceFingerprint
# ---------------------------------------------------------------------------

class DeviceFingerprint(OfflineIDMixin, models.Model):
    """Store known device fingerprints for users."""

    sync_id = models.UUIDField(
        default=uuid.uuid4, unique=True, db_index=True, editable=False,
        null=True, blank=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="known_devices", verbose_name=_("User"),
    )
    fingerprint_hash = models.CharField(
        max_length=64, db_index=True, verbose_name=_("Fingerprint Hash")
    )
    device_name = models.CharField(max_length=100, verbose_name=_("Device Name"))
    browser_name = models.CharField(max_length=50, blank=True)
    os_name = models.CharField(max_length=50, blank=True)
    is_trusted = models.BooleanField(default=False, verbose_name=_("Trusted Device"))
    trust_score = models.IntegerField(default=0, verbose_name=_("Trust Score"))
    first_seen_at = models.DateTimeField(auto_now_add=True, verbose_name=_("First Seen"))
    last_seen_at = models.DateTimeField(auto_now=True, verbose_name=_("Last Seen"))
    login_count = models.PositiveIntegerField(default=0, verbose_name=_("Login Count"))
    last_ip_address = models.GenericIPAddressField(
        blank=True, null=True, verbose_name=_("Last IP Address")
    )
    last_location = models.CharField(
        max_length=200, blank=True, verbose_name=_("Last Location")
    )
    is_active = models.BooleanField(default=True, verbose_name=_("Active"))
    notes = models.TextField(blank=True, verbose_name=_("Notes"))

    def __str__(self):
        return f"{self.device_name} - {self.user.get_full_name()}"

    def increment_login(self):
        self.login_count += 1
        self.trust_score = min(100, self.trust_score + 5)
        self.save(update_fields=["login_count", "trust_score"])

    def flag_suspicious(self):
        self.trust_score = max(0, self.trust_score - 20)
        self.save(update_fields=["trust_score"])

    class Meta:
        verbose_name = _("Device Fingerprint")
        verbose_name_plural = _("Device Fingerprints")
        unique_together = [["user", "fingerprint_hash"]]
        ordering = ["-last_seen_at"]
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["fingerprint_hash"]),
            models.Index(fields=["is_trusted"]),
        ]


# ---------------------------------------------------------------------------
# StockStore
# ---------------------------------------------------------------------------

class StockStore(models.Model):
    company = models.ForeignKey(
        "company.Company",
        on_delete=models.CASCADE,
        related_name="stock_stores",
        verbose_name=_("Company"),
    )
    sync_id = models.UUIDField(
        default=uuid.uuid4, unique=True, db_index=True, editable=False,
        null=True, blank=True,
    )
    name = models.CharField(max_length=255, verbose_name=_("StockStore Name"))
    code = models.CharField(max_length=20, unique=True, verbose_name=_("StockStore Code"))
    description = models.TextField(blank=True, verbose_name=_("Description"))
    physical_address = models.TextField(verbose_name=_("Physical Address"))
    region = models.CharField(
        max_length=100, blank=True, null=True, verbose_name=_("Region/District")
    )
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, blank=True, null=True
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, blank=True, null=True
    )
    phone = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        validators=[RegexValidator(r"^\+?[0-9]+$", _("Enter a valid phone number."))],
        verbose_name=_("Primary Phone"),
    )
    email = models.EmailField(blank=True, null=True, verbose_name=_("Email"))
    manager_name = models.CharField(
        max_length=255, blank=True, verbose_name=_("Warehouse Manager")
    )
    manager_phone = models.CharField(
        max_length=20,
        blank=True,
        validators=[RegexValidator(r"^\+?[0-9]+$", _("Enter a valid phone number."))],
        verbose_name=_("Manager Phone"),
    )
    is_main_stockstore = models.BooleanField(
        default=False, verbose_name=_("Main StockStore")
    )
    auto_approve_transfers = models.BooleanField(
        default=False, verbose_name=_("Auto-Approve Transfers")
    )
    requires_manager_approval = models.BooleanField(
        default=True, verbose_name=_("Requires Manager Approval")
    )
    min_stock_alert_enabled = models.BooleanField(
        default=True, verbose_name=_("Enable Low Stock Alerts")
    )
    staff = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="accessible_stockstores",
        verbose_name=_("Warehouse Staff"),
    )
    managers = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="managed_stockstores",
        verbose_name=_("Warehouse Managers"),
    )
    is_active = models.BooleanField(default=True, verbose_name=_("Active"))
    notes = models.TextField(blank=True, verbose_name=_("Notes"))
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created At"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Updated At"))
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_stockstores",
        verbose_name=_("Created By"),
    )

    def __str__(self):
        indicator = "🏢 [MAIN]" if self.is_main_stockstore else "🏪"
        return f"{indicator} {self.name}"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = f"WH-{uuid.uuid4().hex[:6].upper()}"

        # FIX: guard against self.id being None on new unsaved instances.
        # Deduplication runs only when there is an existing PK to exclude.
        if self.is_main_stockstore and self.company:
            qs = StockStore.objects.filter(
                company=self.company, is_main_stockstore=True
            )
            if self.id:
                qs = qs.exclude(id=self.id)
            try:
                qs.update(is_main_stockstore=False)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(
                    "Could not update other stockstores: %s", e
                )

        super().save(*args, **kwargs)

    @property
    def total_inventory_value(self):
        from django.db.models import Sum, F as _F
        from inventory.models import StockStoreInventory

        total = StockStoreInventory.objects.filter(stockstore=self).aggregate(
            total=Sum(_F("quantity") * _F("product__cost_price"))
        )["total"]
        return total or 0

    @property
    def total_products(self):
        from inventory.models import StockStoreInventory

        return StockStoreInventory.objects.filter(stockstore=self).count()

    @property
    def low_stock_items_count(self):
        from inventory.models import StockStoreInventory

        return StockStoreInventory.objects.filter(
            stockstore=self, quantity__lte=F("low_stock_threshold")
        ).count()

    def get_inventory_summary(self):
        from django.db.models import Sum, F as _F
        from inventory.models import StockStoreInventory

        inventory = StockStoreInventory.objects.filter(stockstore=self)
        return {
            "total_products": inventory.count(),
            "total_quantity": inventory.aggregate(Sum("quantity"))["quantity__sum"] or 0,
            "low_stock_count": inventory.filter(
                quantity__lte=_F("low_stock_threshold")
            ).count(),
            "out_of_stock_count": inventory.filter(quantity=0).count(),
            "total_value": self.total_inventory_value,
        }

    def can_supply_branch(self, product, quantity):
        from inventory.models import StockStoreInventory

        try:
            stock = StockStoreInventory.objects.get(stockstore=self, product=product)
            return stock.quantity >= quantity
        except StockStoreInventory.DoesNotExist:
            return False

    def get_available_quantity(self, product):
        from inventory.models import StockStoreInventory

        try:
            stock = StockStoreInventory.objects.get(stockstore=self, product=product)
            return stock.quantity
        except StockStoreInventory.DoesNotExist:
            return 0

    class Meta:
        verbose_name = _("Stock Store (Warehouse)")
        verbose_name_plural = _("Stock Stores (Warehouses)")
        ordering = ["-is_main_stockstore", "sort_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "code"],
                name="unique_stockstore_code_per_company",
            )
        ]
        indexes = [
            models.Index(fields=["company", "is_active"]),
            models.Index(fields=["is_main_stockstore"]),
            models.Index(fields=["code"]),
        ]