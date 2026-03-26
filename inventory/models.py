from django.db import models, transaction
from django.core.validators import MinValueValidator
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.core.validators import RegexValidator
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.exceptions import ValidationError
from .managers import ProductCategoryManager, ServiceCategoryManager
from .efris import EFRISProductMixin
from primebooks.mixins import OfflineIDMixin
import logging
import uuid
from primebooks.mixins import OfflineIDMixin

logger=logging.getLogger(__name__)

User = get_user_model()


class ImportSession(OfflineIDMixin, models.Model):
    """Track import sessions and their results"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True, blank=True
    )
    user = models.ForeignKey('accounts.CustomUser', on_delete=models.CASCADE)
    filename = models.CharField(max_length=255)
    file_size = models.PositiveIntegerField()  # in bytes
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Import settings
    import_mode = models.CharField(max_length=20, default='both')
    conflict_resolution = models.CharField(max_length=20, default='overwrite')
    has_header = models.BooleanField(default=True)
    column_mapping = models.JSONField(default=dict)
    
    # Results
    total_rows = models.PositiveIntegerField(default=0)
    processed_rows = models.PositiveIntegerField(default=0)
    created_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # Error details
    error_message = models.TextField(blank=True)
    error_details = models.JSONField(default=list)  # List of errors
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Import {self.id} - {self.filename} ({self.status})"
    
    @property
    def duration(self):
        """Calculate import duration"""
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        return None
    
    @property
    def success_rate(self):
        """Calculate success rate as percentage"""
        if self.processed_rows > 0:
            success_rows = self.created_count + self.updated_count
            return (success_rows / self.processed_rows) * 100
        return 0


class Category(OfflineIDMixin, models.Model):
    CATEGORY_TYPE_CHOICES = [
        ('product', 'Product Category'),
        ('service', 'Service Category'),
    ]
    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True, blank=True
    )
    # Basic Info
    name = models.CharField(
        max_length=255,
        verbose_name=_("Category Name"),
        help_text=_("Your internal category name (e.g., 'Electronics', 'Beverages')")
    )
    code = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name=_("Category Code")
    )
    description = models.TextField(blank=True, verbose_name=_("Description"))

    # NEW: Category Type (Product or Service)
    category_type = models.CharField(
        max_length=10,
        choices=CATEGORY_TYPE_CHOICES,
        default='product',
        verbose_name=_("Category Type"),
        help_text=_("Is this a product or service category?")
    )

    # EFRIS Reference (kept as foreign key reference)
    efris_commodity_category_code = models.CharField(
        max_length=18,
        blank=True,
        null=True,
        db_index=True,
        verbose_name=_("EFRIS Commodity Category Code"),
        help_text=_("Reference to official EFRIS commodity category (leaf nodes only)")
    )

    # EFRIS Sync Fields
    efris_auto_sync = models.BooleanField(
        default=True,
        verbose_name=_("EFRIS Auto Sync Enabled")
    )
    efris_is_uploaded = models.BooleanField(
        default=False,
        verbose_name=_("Uploaded to EFRIS")
    )
    efris_upload_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("EFRIS Upload Date")
    )
    efris_category_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name=_("EFRIS Category ID")
    )
    objects = models.Manager()

    # Custom managers
    products = ProductCategoryManager()
    services = ServiceCategoryManager()
    # Other Fields
    is_active = models.BooleanField(default=True, verbose_name=_("Active"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Category")
        verbose_name_plural = _("Categories")
        ordering = ['category_type', 'name']
        indexes = [
            models.Index(fields=['efris_commodity_category_code']),
            models.Index(fields=['efris_is_uploaded']),
            models.Index(fields=['category_type']),  # NEW: Index for filtering
        ]

    def __str__(self):
        type_indicator = "🛍️" if self.category_type == 'product' else "⚙️"
        return f"{type_indicator} {self.name}"

    def clean(self):
        """Validate category data before saving"""
        super().clean()

        # ✅ FIXED: Only validate EFRIS fields if auto_sync is enabled
        # If auto_sync is off, skip EFRIS validation entirely
        if self.efris_commodity_category_code and self.efris_auto_sync:
            from company.models import EFRISCommodityCategory
            try:
                efris_cat = EFRISCommodityCategory.objects.get(
                    commodity_category_code=self.efris_commodity_category_code
                )

                # ✅ Validate it's a leaf node (CRITICAL REQUIREMENT)
                if efris_cat.is_leaf_node != '101':
                    raise ValidationError({
                        'efris_commodity_category_code':
                            _("Selected EFRIS category is not a leaf node (is_leaf_node must be '101'). "
                              "Only leaf nodes (terminal categories) can be used for products and services.")
                    })

                # ✅ Validate type matches (product vs service)
                efris_type = 'service' if efris_cat.service_mark == '101' else 'product'
                if self.category_type != efris_type:
                    raise ValidationError({
                        'efris_commodity_category_code':
                            _(f"EFRIS category is a {efris_type} (serviceMark={efris_cat.service_mark}), "
                              f"but you selected category type as '{self.category_type}'. They must match.")
                    })

            except EFRISCommodityCategory.DoesNotExist:
                raise ValidationError({
                    'efris_commodity_category_code':
                        _("Invalid EFRIS commodity category code. This code does not exist in the system.")
                })
    # Properties that fetch from shared EFRIS data
    @property
    def efris_commodity_category(self):
        """Get the full EFRIS commodity category object"""
        if not self.efris_commodity_category_code:
            return None

        from company.models import EFRISCommodityCategory
        try:
            return EFRISCommodityCategory.objects.get(
                commodity_category_code=self.efris_commodity_category_code
            )
        except EFRISCommodityCategory.DoesNotExist:
            return None

    @property
    def efris_commodity_category_name(self):
        """Get EFRIS commodity category name from shared data."""
        category = self.efris_commodity_category
        return category.commodity_category_name if category else 'General Goods'

    @property
    def efris_rate(self):
        """Get the VAT rate from EFRIS category"""
        category = self.efris_commodity_category
        return float(category.rate) if category and category.rate else 0.18

    @property
    def efris_is_exempt(self):
        """Check if category is tax exempt."""
        category = self.efris_commodity_category
        return category.is_exempt == '101' if category else False

    @property
    def efris_is_zero_rate(self):
        """Check if category has zero rate."""
        category = self.efris_commodity_category
        return category.is_zero_rate == '101' if category else False

    @property
    def efris_is_leaf_node(self):
        """Check if category is a leaf node."""
        category = self.efris_commodity_category
        return category.is_leaf_node == '101' if category else False

    @property
    def efris_is_excisable(self):
        """Check if category is subject to excise duty."""
        category = self.efris_commodity_category
        return getattr(category, 'excisable', '102') == '101'

    @property
    def efris_status_display(self):
        """Human-readable EFRIS status."""
        if not self.efris_auto_sync:
            return "EFRIS Sync Disabled"
        elif self.efris_is_uploaded:
            upload_date = self.efris_upload_date.strftime('%d/%m/%Y') if self.efris_upload_date else 'Unknown date'
            return f"Uploaded to EFRIS ({upload_date})"
        else:
            return "Pending EFRIS Upload"

    @property
    def efris_configuration_complete(self):
        """Check if EFRIS configuration is complete."""
        return bool(
            self.name and
            self.efris_commodity_category_code and
            self.efris_is_leaf_node
        )

    @property
    def product_count(self):
        """Count of active products in this category."""
        return self.products.filter(is_active=True).count()

    # EFRIS Methods
    def mark_for_efris_upload(self):
        """Mark category for upload to EFRIS."""
        self.efris_is_uploaded = False
        self.save(update_fields=['efris_is_uploaded'])

    def mark_efris_uploaded(self, efris_category_id=None):
        """Mark category as successfully uploaded to EFRIS."""
        self.efris_is_uploaded = True
        self.efris_upload_date = timezone.now()
        if efris_category_id:
            self.efris_category_id = efris_category_id
        self.save(update_fields=['efris_is_uploaded', 'efris_upload_date', 'efris_category_id'])

    def enable_efris_sync(self):
        """Enable EFRIS auto-sync with validation."""
        if not self.efris_commodity_category_code:
            raise ValueError(
                f"Category '{self.name}' must have an EFRIS commodity category assigned before enabling EFRIS sync."
            )
        
        # Validate the EFRIS category before enabling sync
        if self.efris_commodity_category_code:
            from company.models import EFRISCommodityCategory
            efris_cat = EFRISCommodityCategory.objects.get(
                commodity_category_code=self.efris_commodity_category_code
            )
            
            # Validate it's a leaf node
            if efris_cat.is_leaf_node != '101':
                raise ValueError("Selected EFRIS category is not a leaf node.")
            
            # Validate type matches
            efris_type = 'service' if efris_cat.service_mark == '101' else 'product'
            if self.category_type != efris_type:
                raise ValueError(f"EFRIS category type ({efris_type}) doesn't match category type ({self.category_type})")
        
        self.efris_auto_sync = True
        self.save(update_fields=['efris_auto_sync'])

    def disable_efris_sync(self):
        """Disable EFRIS auto-sync."""
        self.efris_auto_sync = False
        self.save(update_fields=['efris_auto_sync'])

    def get_efris_errors(self):
        """Get list of EFRIS configuration errors."""
        errors = []
        if not self.efris_auto_sync:
            return errors

        if not self.name:
            errors.append("Category Name is required for EFRIS sync")
        if not self.efris_commodity_category_code:
            errors.append("Category must have an EFRIS Commodity Category assigned")
        elif not self.efris_commodity_category:
            errors.append(f"EFRIS Category code '{self.efris_commodity_category_code}' not found in system")
        elif not self.efris_is_leaf_node:
            errors.append("Selected EFRIS category is not a leaf node")

        return errors

    def get_efris_data(self):
        """Get category data formatted for EFRIS API."""
        return {
            'categoryCode': self.code or self.efris_commodity_category_code,
            'categoryName': self.name,
            'description': self.description or self.name,
            'commodityCategoryId': self.efris_commodity_category_code,
            'commodityCategoryName': self.efris_commodity_category_name,
            'isExempt': self.efris_is_exempt,
            'isZeroRate': self.efris_is_zero_rate,
        }

    def cascade_efris_sync_to_products(self):
        """Mark all products in this category for EFRIS re-upload."""
        if self.efris_auto_sync:
            self.products.filter(
                efris_auto_sync_enabled=True
            ).update(efris_is_uploaded=False)

    def save(self, *args, **kwargs):
        """Override save to handle EFRIS sync logic."""

        # Get EFRIS enabled status from company
        from django_tenants.utils import get_tenant_model
        from django.db import connection

        try:
            Company = get_tenant_model()
            current_company = Company.objects.get(schema_name=connection.schema_name)
            efris_enabled = current_company.efris_enabled
        except (Company.DoesNotExist, AttributeError):
            efris_enabled = False

        # ✅ If EFRIS is disabled, clear EFRIS fields
        if not efris_enabled:
            self.efris_auto_sync = False
            self.efris_commodity_category_code = None
            self.efris_is_uploaded = False

        # Track changes for EFRIS sync
        if self.pk:
            old_instance = Category.objects.filter(pk=self.pk).first()
            if old_instance and old_instance.efris_commodity_category_code != self.efris_commodity_category_code:
                # Only mark for re-upload if EFRIS is enabled and auto-sync is on
                if efris_enabled and self.efris_auto_sync:
                    self.efris_is_uploaded = False
                    should_cascade = True
                else:
                    should_cascade = False
            else:
                should_cascade = False
        else:
            should_cascade = False

        if not getattr(self, '_skip_full_clean', False):
            self.full_clean()

        super().save(*args, **kwargs)

        if should_cascade:
            self.cascade_efris_sync_to_products()

    # NEW: Manager methods for filtering
    @classmethod
    def get_product_categories(cls):
        """Get only product categories"""
        return cls.objects.filter(category_type='product', is_active=True)

    @classmethod
    def get_service_categories(cls):
        """Get only service categories"""
        return cls.objects.filter(category_type='service', is_active=True)

class Supplier(OfflineIDMixin, models.Model):
    name = models.CharField(
        max_length=200,
        verbose_name=_("Supplier Name")
    )
    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True, blank=True
    )
    tin = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name=_("Tax Identification Number (TIN)"),
        help_text=_("Supplier's TIN for tax compliance")
    )
    contact_person = models.CharField(
        max_length=100,
        blank=True,null=True,
        verbose_name=_("Contact Person")
    )
    phone = models.CharField(
        max_length=20,
        validators=[RegexValidator(r'^\+?[0-9]+$', 'Enter a valid phone number.')],
        verbose_name=_("Phone Number")
    )
    email = models.EmailField(
        blank=True,null=True,
        verbose_name=_("Email Address")
    )
    address = models.TextField(
        blank=True,null=True,
        verbose_name=_("Physical Address")
    )
    country = models.CharField(
        max_length=100,
        default="Uganda",
        verbose_name=_("Country")
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Active Supplier")
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Created At")
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Updated At")
    )

    class Meta:
        verbose_name = _("Supplier")
        verbose_name_plural = _("Suppliers")
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.phone})"

    @property
    def tax_details(self):
        """Returns supplier tax information for EFRIS compliance"""
        return {
            'supplier_name': self.name,
            'supplier_tin': self.tin,
            'supplier_address': self.address,
            'supplier_contact': self.phone
        }

class Product(OfflineIDMixin, models.Model, EFRISProductMixin):
    TAX_RATE_CHOICES = [
        ('A', 'Standard rate (18%)'),
        ('B', 'Zero rate (0%)'),
        ('C', 'Exempt (Not taxable)'),
        ('D', 'Deemed rate (18%)'),
        ('E', 'Excise Duty rate (as per excise duty rates)'),
    ]

    EFRIS_TAX_CATEGORIES = [
        ('101', 'Standard rate (18%)'),
        ('102', 'Zero rate (0%)'),
        ('103', 'Exempt (Not taxable)'),
        ('104', 'Deemed rate (18%)'),
        ('105', 'Excise Duty + VAT'),
    ]
    # First, define your choices from the JSON data
    UNIT_CHOICES = [
        ("216", "Per Shift"),
        ("215", "Head"),
        ("214", "Straw"),
        ("213", "Billing"),
        ("212", "Ream"),
        ("209", "MWh - Mega Watt Hour"),
        ("210", "Percentage"),
        ("211", "Tot"),
        ("201", "Cycle"),
        ("207", "Hours"),
        ("208", "Cost"),
        ("206", "KM - Kilometres"),
        ("205", "Manhours"),
        ("204", "Core"),
        ("203", "Time of use"),
        ("202", "KWh -Kilo Watt Hour"),
        ("PS", "Per person"),
        ("PD", "Per day"),
        ("kW", "kW"),
        ("MW", "MW"),
        ("PEP", "Per Trip"),
        ("QTR", "Per quarter"),
        ("KSD", "KSD-Kilogram of substance 90 % dry"),
        ("KSH", "KSH-Kilogram of caustic soda"),
        ("KUR", "KUR-Kilogram of uranium"),
        ("LBR", "LBR-Pound gb, us (0,45359237 kg)"),
        ("LBT", "LBT-Troy pound, us (373,242 g)"),
        ("LEF", "LEF-Leaf"),
        ("LPA", "LPA-Litre of pure alcohol"),
        ("LTN", "LTN-Long ton gb, us (1,0160469 t)"),
        ("LTR", "LTR-Litre (1 dm3)"),
        ("MAL", "MAL-Megalitre"),
        ("MAM", "MAM-Megametre"),
        ("MBF", "MBF-Thousand board feet (2,36 m3)"),
        ("MGM", "MGM-Milligram"),
        ("MIL", "MIL-Thousand"),
        ("MTK", "MTK-Square metre"),
        ("MTQ", "MTQ-Cubic metre"),
        ("MTR", "MTR-Metre"),
        ("NAR", "NAR-Number of articles"),
        ("NBB", "NBB-Number of bobbins"),
        ("NIU", "NIU-Number of international units"),
        ("NMB", "NMB-Number"),
        ("NMP", "NMP-Number of packs"),
        ("NPL", "NPL-Number of parcels"),
        ("NPR", "NPR-Number of pairs"),
        ("NPT", "NPT-Number of parts"),
        ("NRL", "NRL-Number of rolls"),
        ("NTT", "NTT-Net [register] ton"),
        ("ONZ", "ONZ-Ounce gb, us (28,349523 g)"),
        ("OZA", "OZA-Fluid ounce (29,5735 cm3)"),
        ("OZI", "OZI-Fluid ounce (28,4l3 cm3)"),
        ("PCE", "PCE-Piece"),
        ("PGL", "PGL-Proof gallon"),
        ("PTD", "PTD-Dry pint (0,55061 dm3)"),
        ("PTI", "PTI-Pint (0,568262 dm3)"),
        ("PTL", "PTL-Liquid pint (0,473l76 dm3)"),
        ("QTD", "QTD-Dry quart (1,101221 dm3)"),
        ("QTI", "QTI-Quart (1,136523 dm3)"),
        ("QTL", "QTL-Liquid quart (0,946353 dm3)"),
        ("QRT", "QRT-Quarter_ gb -12.700586 kg"),
        ("SET", "SET-Set"),
        ("SHT", "SHT-Shipping ton"),
        ("STI", "STI-Stone gb (6,350293 kg)"),
        ("STN", "STN-Short ton gb, us (0,90718474 t)"),
        ("TNE", "TNE-Metric ton (1000 kg)"),
        ("TPR", "TPR-Ten pairs"),
        ("TSD", "TSD-Tonne of substance 90 per cent dry"),
        ("WCD", "WCD-Cord  3-63 m3"),
        ("YDK", "YDK-Square yard"),
        ("YDQ", "YDQ-Cubic yard"),
        ("YRD", "YRD-Yard 0-9144 m"),
        ("APZ", "APZ-Ounce gb, us (31,10348 g)"),
        ("ASM", "ASM-Alcoholic strength by mass"),
        ("ASV", "ASV-Alcoholic strength by volume"),
        ("BFT", "BFT-Board foot"),
        ("AGE", "AGE-YEAR OF MANUFACTURE"),
        ("CCP", "CCP-ENGINE CAPACITY(c.c)"),
        ("BHX", "BHX-Hundred boxes"),
        ("BLD", "BLD-Dry barrel (115,627 dm3)"),
        ("BLL", "BLL-Barrel (petroleum) (158,987 dm3)"),
        ("BUA", "BUA-Bushel (35,2391 dm3)"),
        ("BUI", "BUI-Bushel (36,36874 dm3)"),
        ("CEN", "CEN-Hundred"),
        ("CGM", "CGM-Centigram"),
        ("CLF", "CLF-Hundred leaves"),
        ("CLT", "CLT-Centilitre"),
        ("CMK", "CMK-Square centimetre"),
        ("CMQ", "CMQ-Cubic centimetre"),
        ("CMT", "CMT-Centimetre"),
        ("CNP", "CNP-Hundred packs"),
        ("CNT", "CNT-Cental gb (45,359237 kg)"),
        ("CWA", "CWA-Hundredweight us (45,3592 kg)"),
        ("CWI", "CWI-Hundredweight gb (50,802345 kg)"),
        ("DLT", "DLT-Decilitre"),
        ("DMK", "DMK-Square decimetre"),
        ("DMQ", "DMQ-Cubic decimetre"),
        ("DMT", "DMT-Decimetre"),
        ("DPC", "DPC-Dozen pieces"),
        ("DPR", "DPR-Dozen pairs"),
        ("DRA", "DRA-Dram us (3,887935 g)"),
        ("DRI", "DRI-Dram gb (l,771745 g)"),
        ("DRL", "DRL-Dozen rolls"),
        ("DRM", "DRM-Drachm gb (3,887935 g)"),
        ("DTH", "DTH-Hectokilogram"),
        ("DTN", "DTN-Centner, metric (100 kg)"),
        ("DWT", "DWT-Pennyweight gb, us (1,555174 g)"),
        ("DZN", "DZN-Dozen"),
        ("DZP", "DZP-Dozen packs"),
        ("FOT", "FOT-Foot (0,3048 m)"),
        ("FTK", "FTK-Square foot"),
        ("FTQ", "FTQ-Cubic foot"),
        ("GGR", "GGR-Great gross (12 gross)"),
        ("GIA", "GIA-Gill (11,8294 cm3)"),
        ("GII", "GII-Gill (0,142065 dm3)"),
        ("GLD", "GLD-Dry gallon (4,404884 dm3)"),
        ("GLI", "GLI-Gallon (4,546092 dm3)"),
        ("GLL", "GLL-Liquid gallon (3,7854l dm3)"),
        ("GRM", "GRM-Gram"),
        ("GRN", "GRN-Grain gb, us (64,798910 mg)"),
        ("GRO", "GRO-Gross"),
        ("GRT", "GRT-Gross [register] ton"),
        ("HGM", "HGM-Hectogram"),
        ("HIU", "HIU-Hundred international units"),
        ("HLT", "HLT-Hectolitre"),
        ("HPA", "HPA-Hectolitre of pure alcohol"),
        ("INH", "INH-Inch (25,4 mm)"),
        ("INK", "INK-Square inch"),
        ("INQ", "INQ-Cubic inch"),
        ("KGM", "KGM-Kilogram"),
        ("KNI", "KNI-Kilogram of nitrogen"),
        ("KNS", "KNS-Kilogram of named substance"),
        ("KPH", "KPH-Kilogram of caustic potash"),
        ("KPO", "KPO-Kilogram of potassium oxide"),
        ("KPP", "KPP-Kilogram of phosphoric anhydride"),
        ("118", "1USD"),
        ("117", "1UGX"),
        ("114", "Per week"),
        ("116", "Per annum"),
        ("115", "Per month"),
        ("113", "Dozen"),
        ("112", "Yard"),
        ("111", "Pair"),
        ("110", "Box"),
        ("200", "Metre"),
        ("OT", "OT-Octabin"),
        ("OU", "OU-Container"),
        ("P2", "P2-Pan"),
        ("PA", "PA-Packet"),
        ("PB", "PB-Pallet, box"),
        ("PC", "PC-Parcel"),
        ("PLT", "PLT - Pallet_ modular_ collars 80cm x 100cms"),
        ("PE", "PE-Pallet, modular,collars 80cm*120cms"),
        ("PF", "PF-Pen"),
        ("PG", "PG-Plate"),
        ("PH", "PH-Pitcher"),
        ("PI", "PI-Pipe"),
        ("PJ", "PJ-Punnet"),
        ("PK", "PK-Package"),
        ("PL", "PL-Pail"),
        ("PN", "PN-Plank"),
        ("PO", "PO-Pouch"),
        ("PP", "PP-Piece"),
        ("PR", "PR-Receptable, plastic"),
        ("PT", "PT-Pot"),
        ("PU", "PU-Tray"),
        ("PV", "PV-Pipes, in bundle/bunch/truss"),
        ("PX", "PX-Pallet"),
        ("PY", "PY-Plates, in bundle/bunch/truss"),
        ("PZ", "PZ-Planks, in bundle/bunch/truss"),
        ("QA", "QA-Drum,steel,non-removable head"),
        ("QB", "QB-Drum, steel, removable head"),
        ("QC", "QC-Drum,aluminium,non-removable head"),
        ("QD", "QD-Drum, aluminium, removable head"),
        ("QF", "QF-Drum, plastic, non-removable head"),
        ("QG", "QG-Drum, plastic, removable head"),
        ("QH", "QH-Barrel, wooden, bung type"),
        ("QJ", "QJ-Barrel, wooden, removable head"),
        ("QK", "QK-Jerrican, steel, non-removable head"),
        ("QL", "QL-Jerrican, steel, removable head"),
        ("QM", "QM-Jerrican,plastic,non-removable head"),
        ("QN", "QN-Jerrican, plastic, removable head"),
        ("QP", "QP-Box, wooden, natural wood, ordinary"),
        ("QQ", "QQ-Box,natural wood,with sift walls 5"),
        ("QR", "QR-Box, plastic, expanded"),
        ("QS", "QS-Box, plastic, solid"),
        ("RD", "RD-Rod"),
        ("RG", "RG-Ring"),
        ("RJ", "RJ-Rack, clothing hanger"),
        ("RK", "RK-Rack"),
        ("RL", "RL-Reel"),
        ("RO", "RO-Roll"),
        ("RT", "RT-Rednet"),
        ("RZ", "RZ-Rods, in bundle/bunch/truss"),
        ("SA", "SA-Sack"),
        ("SB", "SB-Slab"),
        ("SC", "SC-Crate, shallow"),
        ("SD", "SD-Spindle"),
        ("SE", "SE-Sea-chest"),
        ("SH", "SH-Sachet"),
        ("SI", "SI-Skid"),
        ("SK", "SK-Case, skeleton"),
        ("SL", "SL-Slipsheet"),
        ("SM", "SM-Sheetmetal"),
        ("SO", "SO-Spool"),
        ("SP", "SP-Sheet, plastic wrapping"),
        ("SS", "SS-Case"),
        ("ST", "ST-Sheet"),
        ("SU", "SU-Suitcase"),
        ("SV", "SV-Envelope"),
        ("SW", "SW-Shrinkwrapped"),
        ("SX", "SX-Set"),
        ("SY", "SY-Sleeve"),
        ("SZ", "SZ-Sheets, in bundle/bunch/truss"),
        ("T1", "T1-Tablet"),
        ("TB", "TB-Tub"),
        ("TC", "TC-Tea-chest"),
        ("TD", "TD-Tube, collapsible"),
        ("TE", "TE-Tyre"),
        ("TG", "TG-Tank container"),
        ("TI", "TI-Tierce"),
        ("TK", "TK-Tank, rectangular"),
        ("TL", "TL-Tub"),
        ("TN", "TN-Tin"),
        ("TO", "TO-Tun"),
        ("TR", "TR-Trunk"),
        ("TS", "TS-Truss"),
        ("TT", "TT-Bag"),
        ("TU", "TU-Tube"),
        ("TV", "TV-Tube, with nozzle"),
        ("TW", "TW-Pallet"),
        ("TY", "TY-Tank, cylindrical"),
        ("TZ", "TZ-Tubes, in bundle/bunch/truss"),
        ("UC", "UC-Uncaged"),
        ("UN", "UN-Unit"),
        ("VA", "VA-Vat"),
        ("VEH", "VEH-Vehicle"),
        ("VG", "VG-Bulk"),
        ("VI", "VI-Vial"),
        ("VK", "VK-Vanpack"),
        ("VL", "VL-Bulk, liquid"),
        ("VN", "VN-Vehicle"),
        ("VO", "VO-Bulk,solid,large particles(nodules)"),
        ("VP", "VP-Vacuum-packed"),
        ("VQ", "VQ-Bulk,liquefied gas(abnormal temp/pr"),
        ("VR", "VR-Bulk, solid, granular particles"),
        ("VS", "VS-Bulk"),
        ("VY", "VY-Bulk, solid, fine particles(powder)"),
        ("WA", "WA-Intermediate bulk container"),
        ("WB", "WB-Wickerbottle"),
        ("WC", "WC-Intermediate bulk container,steel"),
        ("WD", "WD-Intermediate bulk container,alumini"),
        ("WF", "WF-Intermediate bulk container,metal"),
        ("WG", "WG-Intermediate bulk cont,steel,pressu"),
        ("WH", "WH-Inter bulk container,alumin,pressur"),
        ("WJ", "WJ-Inter bulk container,metal,pressure"),
        ("WK", "WK-Interme bulk container,steel,liquid"),
        ("WL", "WL-Inter bulk container,alumin liquid"),
        ("WM", "WM-Interm bulk container,metal,liquid"),
        ("WN", "WN-Int bulk cont,woven plastic,no coat"),
        ("WP", "WP-Inter bulk cont,woven plastic,coate"),
        ("WQ", "WQ-Inter bulk cont,woven plastic,liner"),
        ("WR", "WR-Inter bulk cont,woven plastic,coate"),
        ("WS", "WS-Interm bulk container, plastic film"),
        ("WT", "WT-Inter bulk cont,textile no coat/lin"),
        ("WU", "WU-Inter bulk cont,natural wood,liner"),
        ("WV", "WV-Inter bulk contain, textile, coated"),
        ("WW", "WW-Inter bulk conta,textile,with liner"),
        ("WX", "WX-Inter bulk cont,textile,coated/line"),
        ("WY", "WY-Inter bulk cont,plywood,inner liner"),
        ("WZ", "WZ-Interm bulk conta,reconsituted wood"),
        ("XA", "XA-Bag,woven plastic,without inner coa"),
        ("XB", "XB-Bag,woven plastic, sift proof"),
        ("XC", "XC-Bag, woven plastic, water resistant"),
        ("XD", "XD-Bag, plastics film"),
        ("XF", "XF-Bag, textile,without inner coat/lin"),
        ("XG", "XG-Bag, textile, sift proof"),
        ("XH", "XH-Bag, textile, water resistant"),
        ("XJ", "XJ-Bag, paper, multi-wall"),
        ("XK", "XK-Bag,paper,multi-wall,water resistan"),
        ("XX", "XX-SCT UN-IDENTIFIED"),
        ("YA", "YA-Composte pack,plast recp steel drum"),
        ("YB", "YB-Composte pack,plast recp steel crat"),
        ("YC", "YC-Composte pack,plast recp alumi drum"),
        ("YD", "YD-Composte pack,plast recp alum crate"),
        ("YF", "YF-Composte pack,plast recp wooden box"),
        ("YG", "YG-Composte pack,plast recp plywo drum"),
        ("YH", "YH-Composte pack,plast recp plywo box"),
        ("YJ", "YJ-Composte pack,plast recp fibre drum"),
        ("YK", "YK-Composte pack,plast recp fibreb box"),
        ("YL", "YL-Composte pack,plast recp plast drum"),
        ("YM", "YM-Composte pack,plast recp plastc box"),
        ("YN", "YN-Composte pack,glass recp steel drum"),
        ("YP", "YP-Composte pack,glass recp steel crat"),
        ("YQ", "YQ-Composte pack,glass recp alumi drum"),
        ("YR", "YR-Composte pack,glass recp alum crate"),
        ("YS", "YS-Composte pack,glass recp wooden box"),
        ("YT", "YT-Composte pack,glass recp plywo drum"),
        ("YV", "YV-Composte pack,glass recp wicker ham"),
        ("YW", "YW-Composte pack,glass recp fibre drum"),
        ("YX", "YX-Composte pack,glass recp fibreb box"),
        ("YY", "YY-Composte pack,glas rec ex plas pack"),
        ("YZ", "YZ-Composte pack,glas rec so plas pack"),
        ("ZA", "ZA-Interm bulk cont, paper, multi-wall"),
        ("ZB", "ZB-Bag, large"),
        ("ZC", "ZC-Inter bulk cont,paper,water resista"),
        ("ZD", "ZD-Int.bulk.cont,plast,struc equip sol"),
        ("ZF", "ZF-Int.bulk.cont,plast,free standing"),
        ("ZG", "ZG-Int.bulk.cont,plast,struc equp pres"),
        ("ZH", "ZH-Int.bulk.cont,plast,freestand,press"),
        ("ZJ", "ZJ-Int.bulk.cont,plast,struc equip liq"),
        ("ZK", "ZK-Int.bulk.cont,plast,freestand,liqui"),
        ("ZL", "ZL-Int.bulk.cont,comp,rigid plast,soli"),
        ("ZM", "ZM-Int.bulk.cont,comp,flexi plast,soli"),
        ("ZN", "ZN-Int.bulk.cont,comp,rigid plast,pres"),
        ("ZP", "ZP-Int.bulk.cont,comp,flex plast,press"),
        ("ZQ", "ZQ-Int.bulk.cont,comp,rigid plast,liqu"),
        ("ZR", "ZR-Int.bulk.cont,comp,flex plast,liqui"),
        ("ZS", "ZS-Intermediate bulk container"),
        ("ZT", "ZT-Intermediate bulk container"),
        ("ZU", "ZU-Intermediate bulk container"),
        ("ZV", "ZV-Intermediate bulk container"),
        ("ZW", "ZW-Intermediate bulk container"),
        ("ZX", "ZX-Intermediate bulk container"),
        ("ZY", "ZY-Intermediate bulk container"),
        ("ZZ", "ZZ-Mutually defined"),
        ("AA", "AA-Intermediate bulk container"),
        ("AB", "AB-Receptacle"),
        ("AC", "AC-Receptacle"),
        ("AD", "AD-Receptacle"),
        ("AE", "AE-Aerosol"),
        ("AF", "AF-Pallet"),
        ("AG", "AG-Pallet"),
        ("AH", "AH-Pallet"),
        ("AI", "AI-Clamshell"),
        ("AJ", "AJ-Cone"),
        ("AL", "AL-Ball"),
        ("AM", "AM-Ampoule, non protected"),
        ("AP", "AP-Ampoule, protected"),
        ("AT", "AT-Atomizer"),
        ("AV", "AV-Capsule"),
        ("BA", "BA-Barrel"),
        ("BB", "BB-Bobbin"),
        ("BC", "BC-Bottle crate / bottle rack"),
        ("BD", "BD-Board"),
        ("BE", "BE-Bundle"),
        ("BF", "BF-Ballon, non-protected"),
        ("BG", "BG-Bag"),
        ("BH", "BH-Bunch"),
        ("BI", "BI-Bin"),
        ("BJ", "BJ-Bucket"),
        ("BK", "BK-Basket"),
        ("BL", "BL-Bale, compressed"),
        ("BM", "BM-Basin 5"),
        ("BN", "BN-Bale, non compressed"),
        ("BO", "BO-Bottle, non protected, cylindrical"),
        ("BP", "BP-Ballon, protected"),
        ("BQ", "BQ-Bottle, protected cylindrical"),
        ("BR", "BR-Bar"),
        ("BS", "BS-Bottle, non protected, bulbous"),
        ("BT", "BT-Bolt"),
        ("BU", "BU-Butt"),
        ("BV", "BV-Bottle, protected bulbous"),
        ("BW", "BW-Box, for liquids"),
        ("BX", "BX-Box 21 to"),
        ("BY", "BY-Board, in bundle/bunch/truss"),
        ("BZ", "BZ-Bars, in bundle/bunch/truss"),
        ("CA", "CA-Can, rectangular"),
        ("CB", "CB-Crate, beer"),
        ("CC", "CC-Churn"),
        ("CD", "CD-Can, with handle and spout"),
        ("CE", "CE-Creel"),
        ("CF", "CF-Coffer"),
        ("CG", "CG-Cage"),
        ("CH", "CH-Chest"),
        ("CI", "CI-Canister"),
        ("CJ", "CJ-Coffin"),
        ("CK", "CK-Cask"),
        ("CL", "CL-Coil"),
        ("CM", "CM-Card"),
        ("CN", "CN-Container,nes as transport equipmen"),
        ("CO", "CO-Carboy, non-protected"),
        ("CP", "CP-Carboy, protected"),
        ("CQ", "CQ-Cartridge"),
        ("CR", "CR-Crate"),
        ("CS", "CS-Case"),
        ("CT", "CT-Carton"),
        ("CU", "CU-Cup"),
        ("CV", "CV-Cover"),
        ("CW", "CW-Cage, roll"),
        ("CX", "CX-Can, cylindrical"),
        ("CY", "CY-Cylinder"),
        ("CZ", "CZ-Canvas"),
        ("DA", "DA-Crate, multiple layer, plastic"),
        ("DB", "DB-Crate, multiple layer, wooden"),
        ("DC", "DC-Crate"),
        ("DG", "DG-Cage,commonwealth handlg equip pool"),
        ("DH", "DH-Box,commonwealth handlig equip pool"),
        ("DI", "DI-Drum, iron"),
        ("DJ", "DJ-Demijohn, non-protected"),
        ("DK", "DK-Crate, bulk, cardboard"),
        ("DL", "DL-Crate, bulk, plastic"),
        ("DM", "DM-Crate, bulk, wooden"),
        ("DN", "DN-Dispenser"),
        ("DP", "DP-Demijohn, protected"),
        ("DR", "DR-Drum"),
        ("DS", "DS-Tray, one layer no cover,plastic"),
        ("DT", "DT-Tray, one layer no cover, wooden"),
        ("DU", "DU-Tray, one layer no cover,polystyren"),
        ("DV", "DV-Tray, one layer no cover, cardboard"),
        ("DW", "DW-Tray,two layers no cover,platic tra"),
        ("DX", "DX-Tray, two layers no cover, wooden"),
        ("DY", "DY-Tray, two layers no cover,cardboard"),
        ("EC", "EC-Bag, plastic"),
        ("ED", "ED-Case, with pallet base"),
        ("EE", "EE-Case, with pallet base, wooden"),
        ("EF", "EF-Case, with pallet base, cardboard"),
        ("EG", "EG-Case, with pallet base, plastic"),
        ("EH", "EH-Case, with pallet base, metal"),
        ("EI", "EI-Case, isothermic"),
        ("EN", "EN-Envelope"),
        ("FB", "FB-Flexibag"),
        ("FC", "FC-Crate, friut"),
        ("FD", "FD-Crate, framed"),
        ("FE", "FE-Flexitank"),
        ("FI", "FI-Firkin"),
        ("FL", "FL-Flask"),
        ("FO", "FO-Footlocker"),
        ("FP", "FP-Filmpack"),
        ("FR", "FR-Frame"),
        ("FT", "FT-Foodtainer"),
        ("FW", "FW-Cart"),
        ("FX", "FX-Bag"),
        ("GB", "GB-Bottle, gas"),
        ("GI", "GI-Girder"),
        ("GL", "GL-Container"),
        ("GR", "GR-Receptable, glass"),
        ("GU", "GU-Tray"),
        ("GY", "GY-Bag"),
        ("GZ", "GZ-Girders, in bundle/bunch/truss"),
        ("HA", "HA-Basket, with handle, plastic"),
        ("HB", "HB-Basket, with handle, wooden"),
        ("HC", "HC-Basket, with handle, cardboard"),
        ("HG", "HG-Hogshead"),
        ("HN", "HN-Hanger"),
        ("HR", "HR-Hamper"),
        ("IA", "IA-Package, display, wooden"),
        ("IB", "IB-Package, display, cardboard"),
        ("IC", "IC-Package, display, plastic"),
        ("ID", "ID-Package, display, metal"),
        ("IE", "IE-Package, show"),
        ("IF", "IF-Package, flow"),
        ("IG", "IG-Package, paper wrapped"),
        ("IH", "IH-Drum, plastic"),
        ("IK", "IK-Package"),
        ("IL", "IL-Tray"),
        ("IN", "IN-Ingot"),
        ("IZ", "IZ-Ingots, in bundle/bunch/truss"),
        ("JB", "JB-Bag"),
        ("JC", "JC-Jerrican, rectangular"),
        ("JG", "JG-Jug"),
        ("JR", "JR-Jar"),
        ("JT", "JT-Jute bag"),
        ("JY", "JY-Jerrican, cylindrical"),
        ("KG", "KG-Keg"),
        ("KI", "KI-Kit"),
        ("LE", "LE-Luggage"),
        ("LG", "LG-Log"),
        ("LT", "LT-Lot"),
        ("LU", "LU-Lug"),
        ("LV", "LV-Liftvan"),
        ("LZ", "LZ-Logs, in bundle/bunch/truss"),
        ("MA", "MA-Crate"),
        ("MB", "MB-Bag, multiply"),
        ("MC", "MC-Crate, milk"),
        ("ME", "ME-Container"),
        ("MR", "MR-Receptable, metal"),
        ("MS", "MS-Sack, multi-wall"),
        ("MT", "MT-Mat"),
        ("MW", "MW-Receptable, plastic wrapped"),
        ("MX", "MX-Matchbox"),
        ("NA", "NA-Not available"),
        ("NE", "NE-Unpacked or unpackaged"),
        ("NF", "NF-Unpacked or unpackaged"),
        ("NG", "NG-Unpacked or unpackaged"),
        ("NS", "NS-Nest"),
        ("NT", "NT-Net"),
        ("NU", "NU-Net, tube, plastic"),
        ("NV", "NV-Net, tube, textile"),
        ("OA", "OA-Pallet"),
        ("OB", "OB-Pallet"),
        ("OC", "OC-Pallet"),
        ("OD", "OD-Pallet"),
        ("OE", "OE-Pallet"),
        ("OF", "OF-Platform"),
        ("OK", "OK-Block"),
        ("109", "g"),
        ("108", "-"),
        ("107", "50kgs"),
        ("106", "1000sticks"),
        ("104", "User per day of access"),
        ("103", "Kg"),
        ("105", "Minute"),
        ("102", "Litre"),
        ("101", "Stick"),
    ]

    EFRIS_UNIT_MEASURES = [
        ('U', 'Unit/Piece'),
        ('KG', 'Kilogram'),
        ('L', 'Litre'),
        ('M', 'Metre'),
        ('BOX', 'Box'),
        ('PKT', 'Packet'),
        ('G', 'Gram'),
        ('ML', 'Millilitre'),
        ('SET', 'Set'),
        ('PAIR', 'Pair'),
    ]
    BARCODE_TYPE_CHOICES = [
        ('manufacturer', 'Manufacturer barcode (EAN/UPC on product)'),
        ('internal',     'Internal barcode (generated by us)'),
    ]
    barcode_type = models.CharField(
        max_length=20,
        choices=BARCODE_TYPE_CHOICES,
        default='manufacturer',
        blank=True,
        verbose_name=_("Barcode type"),
        help_text=_("Manufacturer = barcode already on the product. "
                    "Internal = we generated and printed this barcode.")
    )

    barcode_image = models.ImageField(
        upload_to='barcodes/',
        null=True, blank=True,
        verbose_name=_("Barcode image"),
        help_text=_("Auto-generated barcode PNG for label printing")
    )

    is_bundle = models.BooleanField(
        default=False,
        verbose_name=_("Is a bundle / carton"),
        help_text=_("Enable if this product is a bundle/carton "
                    "that maps to child unit products.")
    )
    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True, blank=True
    )
    # Core Product Fields
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='products',
        verbose_name=_("Category"),
        help_text=_("Product category - EFRIS commodity category will be inherited from this")
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='products',
        verbose_name=_("Supplier")
    )
    name = models.CharField(
        max_length=255,
        verbose_name=_("Product Name")
    )
    sku = models.CharField(
        max_length=100,
        unique=True,
        verbose_name=_("SKU Code")
    )
    barcode = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        unique=True,
        verbose_name=_("Barcode")
    )
    description = models.TextField(
        blank=True,
        verbose_name=_("Description")
    )

    # Pricing
    selling_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name=_("Selling Price (UGX)")
    )
    cost_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name=_("Cost Price (UGX)")
    )
    discount_percentage = models.DecimalField(
        max_digits=5,
        null=True,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name=_("Discount Percentage")
    )

    # Tax Information
    tax_rate = models.CharField(
        max_length=1,
        choices=TAX_RATE_CHOICES,
        default='A',
        verbose_name=_("Tax Rate Category")
    )
    excise_duty_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name=_("Excise Duty Rate (%)"),
        help_text=_("Only applicable if tax rate is E")
    )

    # Unit and Stock
    unit_of_measure = models.CharField(
        max_length=20,
        choices=UNIT_CHOICES,
        default='103',
        verbose_name=_("Unit of Measure"),
        help_text=_("Select the unit of measure from the available options")
    )
    min_stock_level = models.PositiveIntegerField(
        default=5,
        verbose_name=_("Minimum Stock Level")
    )

    # EFRIS Excise Duty
    efris_excise_duty_code = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name=_("EFRIS Excise Duty Code")
    )

    # EFRIS Additional Fields
    efris_item_code = models.CharField(max_length=50, blank=True)
    efris_has_piece_unit = models.BooleanField(default=False)
    efris_piece_measure_unit = models.CharField(max_length=3, blank=True)
    efris_piece_unit_price = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    efris_goods_code_field = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name=_("EFRIS Goods Code"),
        help_text=_("Code assigned by EFRIS after goods registration")
    )

    # EFRIS Status Fields
    efris_is_uploaded = models.BooleanField(
        default=False,
        verbose_name=_("Uploaded to EFRIS")
    )
    efris_upload_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("EFRIS Upload Date")
    )
    efris_goods_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name=_("EFRIS Goods ID"),
        help_text=_("ID assigned by EFRIS after successful upload")
    )
    efris_auto_sync_enabled = models.BooleanField(
        default=True,
        verbose_name=_("EFRIS Auto Sync Enabled"),
        help_text=_("Automatically sync price and details changes to EFRIS")
    )
    efris_created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='efris_products_created',
        verbose_name=_("EFRIS Created By")
    )
    customs_measure_unit = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        verbose_name=_("Customs Measure Unit"),
        help_text=_("Customs measure unit for exports (from T115 exportRateUnit) - e.g., NTT, KGM, LTR")
    )

    customs_unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Customs Unit Price"),
        help_text=_("Unit price in customs measure unit (for export documentation)")
    )

    package_scaled_value_customs = models.DecimalField(
        max_digits=12,
        decimal_places=8,
        null=True,
        blank=True,
        default=1,
        verbose_name=_("Package Scaled Value (Customs)"),
        help_text=_("Package scaling factor for customs unit (usually 1)")
    )

    customs_scaled_value = models.DecimalField(
        max_digits=12,
        decimal_places=8,
        null=True,
        blank=True,
        default=1,
        verbose_name=_("Customs Scaled Value"),
        help_text=_("Conversion factor between units (usually 1)")
    )

    piece_measure_unit = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        verbose_name=_("Piece Measure Unit"),
        help_text=_("Piece measure unit (from T115 rateUnit) - e.g., 101=Per Stick, 102=Per Litre")
    )

    # T130 Piece Unit Fields (conditional)
    efris_package_scaled_value = models.DecimalField(
        max_digits=12,
        decimal_places=8,
        default=1,
        blank=True,null=True,
        verbose_name=_("Package Scaled Value"),
        help_text=_("MANDATORY when havePieceUnit=101")
    )

    efris_piece_scaled_value = models.DecimalField(
        max_digits=12,
        decimal_places=8,
        default=1,
        verbose_name=_("Piece Scaled Value"),
        help_text=_("MANDATORY when havePieceUnit=101")
    )

    # T130 Other Units Support
    efris_has_other_units = models.BooleanField(
        default=False,
        verbose_name=_("Has Other Units"),
        help_text=_("Product has alternative measurement units")
    )

    efris_other_units = models.JSONField(
        null=True,
        blank=True,
        verbose_name=_("Other Units"),
        help_text=_("Array of {otherUnit, otherPrice, otherScaled, packageScaled}")
    )

    # T130 Export/Customs Fields (for commodityGoodsExtendEntity)
    is_export_product = models.BooleanField(
        default=False,
        verbose_name=_("Export Product"),
        help_text=_("Product configured for export sales")
    )

    efris_customs_measure_unit = models.CharField(
        max_length=10,
        blank=True,
        verbose_name=_("Customs Measure Unit"),
        help_text=_("From T115 exportRateUnit (e.g., KGM, LTR, NTT)")
    )

    efris_customs_unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Customs Unit Price"),
        help_text=_("Unit price in customs measure unit")
    )

    efris_package_scaled_value_customs = models.DecimalField(
        max_digits=12,
        decimal_places=8,
        default=1,
        null=True,
        blank=True,
        verbose_name=_("Package Scaled Value (Customs)"),
        help_text=_("Package scaling for customs unit")
    )

    efris_customs_scaled_value = models.DecimalField(
        max_digits=12,
        decimal_places=8,
        default=1,
        null=True,
        blank=True,
        verbose_name=_("Customs Scaled Value"),
        help_text=_("Conversion factor for customs unit")
    )

    # T109 Export - HS Code Fields
    hs_code = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("HS Code"),
        help_text=_("Harmonized System code for exports")
    )

    hs_name = models.CharField(
        max_length=1000,
        blank=True,
        verbose_name=_("HS Description"),
        help_text=_("Description of HS code")
    )
    item_weight = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Weight per unit in KG (required for export)"
    )
    piece_qty = models.IntegerField(
        null=True,
        blank=True,
        default=1,
        help_text="Number of pieces per unit"
    )
    # Service Mark (T130 field)
    efris_service_mark = models.CharField(
        max_length=3,
        blank=True,
        default='102',
        verbose_name=_("Service Mark"),
        help_text=_("101=Service, 102=Product")
    )

    # Other Fields
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Active")
    )
    image = models.ImageField(
        upload_to='products/images/',
        blank=True,
        null=True,
        verbose_name=_("Product Image")
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Created At")
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Updated At")
    )
    imported_at = models.DateTimeField(
        null=True,
        blank=True
    )
    import_session = models.ForeignKey(
        'ImportSession',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='imported_products'
    )

    class Meta:
        verbose_name = _("Product")
        verbose_name_plural = _("Products")
        ordering = ['name']
        indexes = [
            models.Index(fields=['efris_is_uploaded']),
            models.Index(fields=['efris_auto_sync_enabled']),
        ]

    def __str__(self):
        return f"{self.name} ({self.sku})"

    @property
    def is_export_ready(self):
        '''Check if product has all required export configuration'''
        return bool(
            self.hs_code and
            self.item_weight and
            self.item_weight > 0 and
            self.customs_measure_unit
        )

    def _scaled(self, value):
        """Return value if truthy, otherwise Decimal('1')."""
        from decimal import Decimal
        return value if value is not None else Decimal('1')

    # ── clean() ──────────────────────────────────────────────────────────────
    def clean(self):
        """Validate product data before saving."""
        super().clean()

        # Get EFRIS status — default to False for safety
        efris_enabled = getattr(self, '_efris_enabled', False)

        if efris_enabled:
            if self.category and not self.category.efris_commodity_category_code:
                raise ValidationError({
                    'category': _(
                        "Selected category does not have an EFRIS commodity category assigned."
                    )
                })

            if self.category and not self.category.efris_is_leaf_node:
                raise ValidationError({
                    'category': _(
                        "Selected category's EFRIS commodity category is not a leaf node."
                    )
                })

        # Ensure scaled values are never stored as None
        if self.efris_package_scaled_value is None:
            self.efris_package_scaled_value = 1
        if self.efris_piece_scaled_value is None:
            self.efris_piece_scaled_value = 1
        if self.efris_package_scaled_value_customs is None:
            self.efris_package_scaled_value_customs = 1
        if self.efris_customs_scaled_value is None:
            self.efris_customs_scaled_value = 1


    @property
    def effective_tax_rate(self):
        """
        Get the effective tax rate considering company VAT status
        """
        from django_tenants.utils import get_tenant_model
        from django.db import connection

        try:
            Company = get_tenant_model()
            current_company = Company.objects.get(schema_name=connection.schema_name)
            return current_company.get_effective_tax_rate(self.tax_rate)
        except (Company.DoesNotExist, AttributeError):
            return self.tax_rate  # Fallback to product's rate

    # DRY Properties - Everything inherits from Category
    @property
    def efris_commodity_category_id(self):
        """
        Get EFRIS commodity category code from the product's category.
        Returns default if category or EFRIS category not set.
        """
        if self.category and self.category.efris_commodity_category:
            return self.category.efris_commodity_category.commodity_category_code
        return '101113010000000000'  # Default fallback

    @property
    def efris_commodity_category_name(self):
        """
        Get EFRIS commodity category name from the product's category.
        Returns default if category or EFRIS category not set.
        """
        if self.category and self.category.efris_commodity_category:
            return self.category.efris_commodity_category.commodity_category_name
        return 'General Goods'

    # EFRIS Properties - Direct mapping from business data
    @property
    def efris_goods_code(self):
        """
        Get the EFRIS-assigned goods code.
        Falls back to SKU if not yet assigned by EFRIS.
        """
        return self.efris_goods_code_field or self.sku

    @efris_goods_code.setter
    def efris_goods_code(self, value):
        """
        Set or update the EFRIS goods code (from EFRIS 'goodsCode' field).
        This value is persisted to the database.
        """
        # Save only if a valid non-empty value is provided
        if value:
            self.efris_goods_code_field = value
            self.save(update_fields=["efris_goods_code_field"])

    @property
    def efris_goods_name(self):
        """EFRIS product name - uses product name"""
        return self.name

    @property
    def efris_goods_description(self):
        """EFRIS product description - uses description or name as fallback"""
        return self.description or self.name

    @property
    def efris_tax_category_id(self):
        """Auto-mapped EFRIS tax category from effective tax rate"""
        tax_rate_mapping = {
            'A': '101',  # Standard (18%)
            'B': '102',  # Zero (0%)
            'C': '103',  # Exempt
            'D': '104',  # Deemed (18%)
            'E': '105',  # Excise Duty + VAT
        }
        effective_rate = self.effective_tax_rate
        return tax_rate_mapping.get(effective_rate, '102')

    @property
    def efris_tax_rate(self):
        """Auto-calculated EFRIS tax rate from effective tax rate"""
        tax_rate_values = {
            'A': 18.00,
            'B': 0.00,
            'C': 0.00,
            'D': 18.00,
            'E': 18.00,  # Plus excise duty
        }
        effective_rate = self.effective_tax_rate
        return tax_rate_values.get(effective_rate, 0.00)

    @property
    def efris_excise_duty_rate(self):
        """EFRIS excise duty rate from excise_duty_rate field"""
        return self.excise_duty_rate

    @property
    def efris_unit_of_measure_code(self):
        return self.unit_of_measure or '103'

    @property
    def final_price(self):
        from decimal import Decimal
        """Calculate final price after discount, safely handling None and type issues."""
        selling_price = self.selling_price or Decimal('0')
        discount_percentage = self.discount_percentage or Decimal('0')

        # Ensure both are Decimals
        if not isinstance(discount_percentage, Decimal):
            discount_percentage = Decimal(str(discount_percentage))
        if not isinstance(selling_price, Decimal):
            selling_price = Decimal(str(selling_price))

        discount_amount = (discount_percentage / Decimal('100')) * selling_price
        return selling_price - discount_amount

    @property
    def image_url(self):
        """Return image URL or placeholder if not set"""
        if self.image:
            return self.image.url
        return "/static/images/placeholder.png"

    @property
    def tax_details(self):
        """Returns product tax information for EFRIS compliance - using effective rate"""
        return {
            'product_name': self.efris_goods_name,
            'product_code': self.efris_goods_code,
            'tax_rate': self.get_tax_rate_display(),
            'effective_tax_rate': self.effective_tax_rate,
            'efris_tax_category': self.efris_tax_category_id,
            'efris_tax_rate': str(self.efris_tax_rate),
            'unit_price': str(self.final_price),
            'unit_of_measure': self.unit_of_measure
        }

    @property
    def total_stock(self):
        """Total stock across all stores."""
        return sum(stock.quantity for stock in self.store_inventory.all())

    @property
    def stock_percentage(self):
        """Global stock percentage compared to Product.min_stock_level."""
        if not self.min_stock_level or self.min_stock_level <= 0:
            return 100
        percentage = (self.total_stock / self.min_stock_level) * 100
        return min(100, max(0, round(percentage)))

    @property
    def store_stock_percentages(self):
        """Returns stock percentages per store compared to store-specific reorder_level."""
        results = {}
        for stock in self.store_inventory.select_related("store"):
            results[stock.store.name] = stock.stock_percentage
        return results

    @property
    def efris_status_display(self):
        """Human-readable EFRIS status for this product."""
        if not self.efris_auto_sync_enabled:
            return "EFRIS Sync Disabled"
        elif self.efris_is_uploaded:
            upload_date = self.efris_upload_date.strftime('%d/%m/%Y') if self.efris_upload_date else 'Unknown date'
            return f"Uploaded to EFRIS ({upload_date})"
        else:
            return "Pending EFRIS Upload"

    @property
    def efris_configuration_complete(self):
        """Check if EFRIS configuration is complete for this product."""
        # Check all required fields
        required_fields = [
            self.name,
            self.sku,
            self.tax_rate,
            self.unit_of_measure,
            self.category,  # Must have a category
            self.efris_commodity_category_id  # Category must have EFRIS category
        ]
        return all(required_fields)

    @property
    def current_price(self):
        """Get current selling price (for compatibility)"""
        return self.selling_price

    @property
    def current_stock(self):
        """Get current total stock (for compatibility)"""
        return self.total_stock

    # EFRIS Methods
    def mark_for_efris_upload(self):
        """Mark product for upload to EFRIS"""
        self.efris_is_uploaded = False
        self.save(update_fields=['efris_is_uploaded'])

    def get_efris_commodity_goods_extend(self):
        """Get commodityGoodsExtendEntity for export products."""
        if not self.is_export_product:
            return None

        return {
            "customsMeasureUnit": self.efris_customs_measure_unit or "",
            "customsUnitPrice": (
                f"{self.efris_customs_unit_price:.2f}"
                if self.efris_customs_unit_price else ""
            ),
            "packageScaledValueCustoms": str(self._scaled(self.efris_package_scaled_value_customs)),
            "customsScaledValue": str(self._scaled(self.efris_customs_scaled_value)),
        }

    def get_efris_other_units(self):
        """Get goodsOtherUnits array for T130"""
        if not self.efris_has_other_units or not self.efris_other_units:
            return []

        # Validate that otherUnit != measureUnit and != pieceMeasureUnit
        other_units = []
        for unit_data in self.efris_other_units:
            other_unit = unit_data.get('otherUnit', '')
            if other_unit and other_unit != self.unit_of_measure and other_unit != self.efris_piece_measure_unit:
                other_units.append({
                    "otherUnit": other_unit,
                    "otherPrice": str(unit_data.get('otherPrice', 0)),
                    "otherScaled": str(unit_data.get('otherScaled', 1)),
                    "packageScaled": str(unit_data.get('packageScaled', 1)),
                })

        return other_units

    def validate_efris_piece_unit_fields(self):
        """Validate conditional piece unit fields per T130 spec."""
        errors = []

        if self.efris_has_piece_unit:
            # MANDATORY fields when havePieceUnit=101
            if not self.efris_piece_measure_unit:
                errors.append("pieceMeasureUnit MANDATORY when havePieceUnit=101")
            if not self.efris_piece_unit_price:
                errors.append("pieceUnitPrice MANDATORY when havePieceUnit=101")
            # Scaled values default to 1 — only flag if explicitly set to zero
            if self._scaled(self.efris_package_scaled_value) <= 0:
                errors.append("packageScaledValue must be greater than 0 when havePieceUnit=101")
            if self._scaled(self.efris_piece_scaled_value) <= 0:
                errors.append("pieceScaledValue must be greater than 0 when havePieceUnit=101")
        else:
            # MUST BE EMPTY when havePieceUnit=102
            if self.efris_piece_measure_unit:
                errors.append("pieceMeasureUnit must be empty when havePieceUnit=102")
            if self.efris_piece_unit_price:
                errors.append("pieceUnitPrice must be empty when havePieceUnit=102")

        return errors

    @property
    def efris_have_piece_unit(self):
        """Return EFRIS havePieceUnit code"""
        return '101' if self.efris_has_piece_unit else '102'

    @property
    def efris_have_other_unit(self):
        """Return EFRIS haveOtherUnit code"""
        return '101' if self.efris_has_other_units else '102'

    def save(self, *args, **kwargs):
        # Get the company (tenant) context
        from django_tenants.utils import get_tenant_model
        from django.db import connection

        # Auto-enforce VAT compliance
        try:
            Company = get_tenant_model()
            current_company = Company.objects.get(schema_name=connection.schema_name)

            # If company VAT is disabled, force tax rate to B
            if not current_company.is_vat_enabled:
                self.tax_rate = 'B'

        except (Company.DoesNotExist, AttributeError):
            # Fallback if tenant context not available
            pass

        super().save(*args, **kwargs)

    def mark_efris_uploaded(self, efris_goods_id=None):
        """Mark product as successfully uploaded to EFRIS"""
        self.efris_is_uploaded = True
        self.efris_upload_date = timezone.now()
        if efris_goods_id:
            self.efris_goods_id = efris_goods_id
        self.save(update_fields=['efris_is_uploaded', 'efris_upload_date', 'efris_goods_id'])

    def enable_efris_sync(self):
        """Enable EFRIS auto-sync for this product"""
        self.efris_auto_sync_enabled = True
        self.save(update_fields=['efris_auto_sync_enabled'])

    def disable_efris_sync(self):
        """Disable EFRIS auto-sync for this product"""
        self.efris_auto_sync_enabled = False
        self.save(update_fields=['efris_auto_sync_enabled'])

    def get_efris_errors(self):
        """Get list of EFRIS configuration errors for this product."""
        errors = []

        if not self.efris_auto_sync_enabled:
            return errors

        # Check required business fields
        required_fields = {
            'name': 'Product Name',
            'sku': 'SKU Code',
            'tax_rate': 'Tax Rate',
            'unit_of_measure': 'Unit of Measure',
        }

        for field, label in required_fields.items():
            if not getattr(self, field):
                errors.append(f"{label} is required for EFRIS sync")

        # Check category and commodity category
        if not self.category:
            errors.append("Product must have a category for EFRIS sync")
        elif not self.category.efris_commodity_category:
            errors.append(f"Category '{self.category.name}' must have an EFRIS Commodity Category assigned")

        return errors

    def get_efris_data(self):
        """Get product data formatted for EFRIS API."""
        data = {
            'goodsCode': self.efris_goods_code,
            'goodsName': self.efris_goods_name,
            'goodsDescription': self.efris_goods_description,
            'commodityCategoryId': self.efris_commodity_category_id,
            'commodityCategoryName': self.efris_commodity_category_name,
            'taxCategoryId': self.efris_tax_category_id,
            'taxRate': float(self.efris_tax_rate),
            'exciseDutyCode': self.efris_excise_duty_code or '',
            'exciseDutyRate': float(self.efris_excise_duty_rate),
            'unitOfMeasureCode': self.efris_unit_of_measure_code,
            'unitPrice': float(self.final_price),
            'currency': 'UGX',
            # Scaled values — always 1 if not explicitly set
            'packageScaledValue': float(self._scaled(self.efris_package_scaled_value)),
            'pieceScaledValue': float(self._scaled(self.efris_piece_scaled_value)),
        }

        # Include piece unit data if enabled
        if self.efris_has_piece_unit:
            data.update({
                'havePieceUnit': '101',
                'pieceMeasureUnit': self.efris_piece_measure_unit or '',
                'pieceUnitPrice': float(self.efris_piece_unit_price or 0),
            })
        else:
            data['havePieceUnit'] = '102'

        # Include export/customs data if applicable
        extend = self.get_efris_commodity_goods_extend()
        if extend:
            data['commodityGoodsExtend'] = extend

        return data


class Service(OfflineIDMixin, models.Model):
    TAX_RATE_CHOICES = [
        ('A', 'Standard rate (18%)'),
        ('B', 'Zero rate (0%)'),
        ('C', 'Exempt (Not taxable)'),
        ('D', 'Deemed rate (18%)'),
        ('E', 'Excise Duty rate (as per excise duty rates)'),
    ]

    EFRIS_TAX_CATEGORIES = [
        ('101', 'Standard rate (18%)'),
        ('102', 'Zero rate (0%)'),
        ('103', 'Exempt (Not taxable)'),
        ('104', 'Deemed rate (18%)'),
        ('105', 'Excise Duty + VAT'),
    ]
    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True, blank=True
    )
    # Core Service Fields
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={'category_type': 'service'},
        related_name='services',
        verbose_name=_("Service Category"),
        help_text=_("Service category - EFRIS commodity category will be inherited from this")
    )

    name = models.CharField(
        max_length=255,
        verbose_name=_("Service Name")
    )

    code = models.CharField(
        max_length=100,
        unique=True,
        verbose_name=_("Service Code"),
        help_text=_("Unique identifier for this service")
    )

    description = models.TextField(
        blank=True,
        verbose_name=_("Description")
    )

    # Pricing
    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        verbose_name=_("Unit Price (UGX)"),
        help_text=_("Price per unit of service")
    )
    # Service should always have serviceMark=101
    efris_service_mark = models.CharField(
        max_length=3,
        default='101',
        verbose_name=_("Service Mark"),
        help_text=_("Always 101 for services")
    )
    # Tax Information
    tax_rate = models.CharField(
        max_length=1,
        choices=TAX_RATE_CHOICES,
        default='A',
        verbose_name=_("Tax Rate Category")
    )

    excise_duty_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name=_("Excise Duty Rate (%)"),
        help_text=_("Only applicable if tax rate is E")
    )

    # Unit of Measure (for services like hours, sessions, etc.)
    unit_of_measure = models.CharField(
        max_length=20,
        choices=Product.UNIT_CHOICES,
        default='207',  # Hours
        verbose_name=_("Unit of Measure"),
        help_text=_("Unit for measuring this service (e.g., Hours, Sessions)")
    )

    # EFRIS Status Fields
    efris_is_uploaded = models.BooleanField(
        default=False,
        verbose_name=_("Uploaded to EFRIS")
    )

    efris_upload_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("EFRIS Upload Date")
    )

    efris_service_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name=_("EFRIS Service ID"),
        help_text=_("ID assigned by EFRIS after successful upload")
    )

    efris_auto_sync_enabled = models.BooleanField(
        default=True,
        verbose_name=_("EFRIS Auto Sync Enabled"),
        help_text=_("Automatically sync price and details changes to EFRIS")
    )

    # Other Fields
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Active")
    )

    image = models.ImageField(
        upload_to='services/images/',
        blank=True,
        null=True,
        verbose_name=_("Service Image")
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Created At")
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Updated At")
    )

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='services_created',
        verbose_name=_("Created By")
    )

    class Meta:
        verbose_name = _("Service")
        verbose_name_plural = _("Services")
        ordering = ['name']
        indexes = [
            models.Index(fields=['efris_is_uploaded']),
            models.Index(fields=['efris_auto_sync_enabled']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return f"⚙️ {self.name} ({self.code})"

    def clean(self):
        """Validate service data before saving"""
        super().clean()

        # Get EFRIS status - default to False for safety
        efris_enabled = getattr(self, '_efris_enabled', False)

        # Validate category is a service category
        if self.category and self.category.category_type != 'service':
            raise ValidationError({
                'category': _("Selected category is not a service category. Please select a service category.")
            })

        # ✅ FIXED: Only validate EFRIS fields if BOTH conditions are true:
        # 1. EFRIS is enabled for the company
        # 2. Auto-sync is enabled for this service
        if efris_enabled and self.efris_auto_sync_enabled:
            # Validate category is set when EFRIS sync is enabled
            if not self.category:
                raise ValidationError({
                    'category': _("Service category is required when EFRIS auto-sync is enabled.")
                })

            # Validate EFRIS commodity category exists
            if self.category and not self.category.efris_commodity_category_code:
                raise ValidationError({
                    'category': _("Selected category does not have an EFRIS commodity category assigned. "
                                  "Please update the category settings first or disable EFRIS auto-sync.")
                })

            # Validate it's a leaf node
            if self.category and not self.category.efris_is_leaf_node:
                raise ValidationError({
                    'category': _(
                        "Selected category's EFRIS commodity category is not a leaf node. "
                        "Only leaf nodes can be used for services.")
                })

    # Properties - Inherit from Category
    @property
    def efris_commodity_category_id(self):
        """Get EFRIS commodity category code from the service's category."""
        if self.category and self.category.efris_commodity_category:
            return self.category.efris_commodity_category.commodity_category_code
        return '100000000'  # Default fallback

    @property
    def efris_commodity_category_name(self):
        """Get EFRIS commodity category name from the service's category."""
        if self.category and self.category.efris_commodity_category:
            return self.category.efris_commodity_category.commodity_category_name
        return 'General Services'

    @property
    def efris_service_code(self):
        """Service code for EFRIS"""
        return self.code

    @property
    def efris_service_name(self):
        """EFRIS service name"""
        return self.name

    @property
    def efris_service_description(self):
        """EFRIS service description"""
        return self.description or self.name

    @property
    def efris_tax_category_id(self):
        """Auto-mapped EFRIS tax category from tax_rate"""
        tax_rate_mapping = {
            'A': '101',  # Standard (18%)
            'B': '102',  # Zero (0%)
            'C': '103',  # Exempt
            'D': '104',  # Deemed (18%)
            'E': '105',  # Excise Duty + VAT
        }
        return tax_rate_mapping.get(self.tax_rate, '101')

    @property
    def efris_tax_rate(self):
        """Auto-calculated EFRIS tax rate from tax_rate"""
        tax_rate_values = {
            'A': 18.00,
            'B': 0.00,
            'C': 0.00,
            'D': 18.00,
            'E': 18.00,
        }
        return tax_rate_values.get(self.tax_rate, 18.00)

    @property
    def efris_excise_duty_rate(self):
        """EFRIS excise duty rate"""
        return self.excise_duty_rate

    @property
    def efris_unit_of_measure_code(self):
        """EFRIS unit of measure code"""
        return self.unit_of_measure or '207'  # Default to Hours

    @property
    def final_price(self):
        """Calculate final price after discount"""
        from decimal import Decimal
        unit_price = self.unit_price or Decimal('0')

        if not isinstance(unit_price, Decimal):
            unit_price = Decimal(str(unit_price))

        return unit_price

    @property
    def efris_status_display(self):
        """Human-readable EFRIS status"""
        if not self.efris_auto_sync_enabled:
            return "EFRIS Sync Disabled"
        elif self.efris_is_uploaded:
            upload_date = self.efris_upload_date.strftime('%d/%m/%Y') if self.efris_upload_date else 'Unknown date'
            return f"Uploaded to EFRIS ({upload_date})"
        else:
            return "Pending EFRIS Upload"

    @property
    def efris_configuration_complete(self):
        """Check if EFRIS configuration is complete"""
        required_fields = [
            self.name,
            self.code,
            self.tax_rate,
            self.unit_of_measure,
            self.category,
            self.efris_commodity_category_id
        ]
        return all(required_fields) and (self.category and self.category.efris_is_leaf_node)

    # EFRIS Methods
    def mark_for_efris_upload(self):
        """Mark service for upload to EFRIS"""
        self.efris_is_uploaded = False
        self.save(update_fields=['efris_is_uploaded'])

    def mark_efris_uploaded(self, efris_service_id=None):
        """Mark service as successfully uploaded to EFRIS"""
        self.efris_is_uploaded = True
        self.efris_upload_date = timezone.now()
        if efris_service_id:
            self.efris_service_id = efris_service_id
        self.save(update_fields=['efris_is_uploaded', 'efris_upload_date', 'efris_service_id'])

    def enable_efris_sync(self):
        """Enable EFRIS auto-sync with validation"""
        if not self.category:
            raise ValueError(
                f"Service '{self.name}' must have a category assigned before enabling EFRIS sync."
            )

        if not self.category.efris_commodity_category_code:
            raise ValueError(
                f"Category '{self.category.name}' must have an EFRIS commodity category assigned before enabling EFRIS sync."
            )

        # Validate the EFRIS category before enabling sync
        if self.category.efris_commodity_category_code:
            from company.models import EFRISCommodityCategory
            efris_cat = EFRISCommodityCategory.objects.get(
                commodity_category_code=self.category.efris_commodity_category_code
            )

            # Validate it's a leaf node
            if efris_cat.is_leaf_node != '101':
                raise ValueError("Selected EFRIS category is not a leaf node.")

            # Validate type matches (should be service)
            if efris_cat.service_mark != '101':
                raise ValueError("Selected EFRIS category is not a service category.")

        self.efris_auto_sync_enabled = True
        self.save(update_fields=['efris_auto_sync_enabled'])

    def disable_efris_sync(self):
        """Disable EFRIS auto-sync"""
        self.efris_auto_sync_enabled = False
        self.save(update_fields=['efris_auto_sync_enabled'])

    def get_efris_errors(self):
        """Get list of EFRIS configuration errors"""
        errors = []

        if not self.efris_auto_sync_enabled:
            return errors

        required_fields = {
            'name': 'Service Name',
            'code': 'Service Code',
            'tax_rate': 'Tax Rate',
            'unit_of_measure': 'Unit of Measure',
        }

        for field, label in required_fields.items():
            if not getattr(self, field):
                errors.append(f"{label} is required for EFRIS sync")

        if not self.category:
            errors.append("Service must have a category for EFRIS sync")
        elif not self.category.efris_commodity_category:
            errors.append(f"Category '{self.category.name}' must have an EFRIS Commodity Category assigned")
        elif not self.category.efris_is_leaf_node:
            errors.append("Selected category's EFRIS commodity category is not a leaf node")

        return errors

    def get_efris_data(self):
        """Get service data formatted for EFRIS API"""
        return {
            'serviceCode': self.efris_service_code,
            'serviceName': self.efris_service_name,
            'serviceDescription': self.efris_service_description,
            'commodityCategoryId': self.efris_commodity_category_id,
            'commodityCategoryName': self.efris_commodity_category_name,
            'taxCategoryId': self.efris_tax_category_id,
            'taxRate': float(self.efris_tax_rate),
            'exciseDutyRate': float(self.efris_excise_duty_rate),
            'unitOfMeasureCode': self.efris_unit_of_measure_code,
            'unitPrice': float(self.final_price),
            'currency': 'UGX'
        }

    def save(self, *args, **kwargs):
        """Override save to handle EFRIS sync logic and VAT enforcement"""

        # Store original values for comparison (only if instance already exists)
        original_tax_rate = None
        original_unit_price = None
        original_category_id = None
        old_instance = None
        tax_rate_changed_by_vat = False

        if self.pk:
            try:
                old_instance = Service.objects.get(pk=self.pk)
                original_tax_rate = old_instance.tax_rate
                original_unit_price = old_instance.unit_price
                original_category_id = old_instance.category_id
            except Service.DoesNotExist:
                pass

        # VAT ENFORCEMENT LOGIC
        from django_tenants.utils import get_tenant_model
        from django.db import connection

        try:
            Company = get_tenant_model()
            current_company = Company.objects.get(schema_name=connection.schema_name)

            # ✅ Set EFRIS status for clean() validation
            self._efris_enabled = current_company.efris_enabled

            # Enforce VAT compliance
            if not current_company.is_vat_enabled and self.tax_rate != 'B':
                self.tax_rate = 'B'
                self.excise_duty_rate = 0  # Also reset excise duty
                tax_rate_changed_by_vat = True

        except (Company.DoesNotExist, AttributeError):
            # Fallback if tenant context not available
            self._efris_enabled = False

        # EFRIS SYNC LOGIC - Only mark for re-upload if changes occurred
        if self.pk and old_instance:
            # Check if critical fields changed
            price_changed = original_unit_price != self.unit_price
            tax_changed = original_tax_rate != self.tax_rate
            category_changed = original_category_id != self.category_id


            if (price_changed or tax_changed or category_changed or tax_rate_changed_by_vat):
                if self.efris_auto_sync_enabled and self._efris_enabled:
                    self.efris_is_uploaded = False
                    logger.info(
                        f"Service '{self.name}' marked for EFRIS re-upload due to changes: "
                        f"price_changed={price_changed}, tax_changed={tax_changed}, "
                        f"category_changed={category_changed}, vat_enforced={tax_rate_changed_by_vat}"
                    )
        else:
            # New instance - mark for EFRIS upload if auto-sync is enabled
            if self.efris_auto_sync_enabled and self._efris_enabled:
                self.efris_is_uploaded = False
                logger.info(f"New service '{self.name}' marked for EFRIS upload")

        # ✅ If EFRIS is disabled, ensure EFRIS flags are off
        if not self._efris_enabled:
            self.efris_auto_sync_enabled = False
            self.efris_is_uploaded = False

        # Run full validation (this will call clean())
        if not getattr(self, '_skip_full_clean', False):
            try:
                self.full_clean()
            except ValidationError as e:
                logger.error(f"Validation error saving service '{self.name}': {e}")
                raise

        # Save the instance
        super().save(*args, **kwargs)

        logger.info(
            f"Service saved: {self.name} (ID: {self.pk}) - "
            f"EFRIS enabled: {self._efris_enabled}, "
            f"Auto-sync: {self.efris_auto_sync_enabled}, "
            f"Uploaded: {self.efris_is_uploaded}"
        )

    @property
    def effective_tax_rate(self):
        """Get effective tax rate considering company VAT status"""
        from django_tenants.utils import get_tenant_model
        from django.db import connection

        try:
            Company = get_tenant_model()
            current_company = Company.objects.get(schema_name=connection.schema_name)
            return current_company.get_effective_tax_rate(self.tax_rate)
        except (Company.DoesNotExist, AttributeError):
            return self.tax_rate

class Stock(OfflineIDMixin, models.Model):
    product = models.ForeignKey(
        'inventory.Product',
        on_delete=models.CASCADE,
        related_name='store_inventory',
        verbose_name=_("Product")
    )
    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.CASCADE,
        related_name='inventory_items',
        verbose_name=_("Store")
    )
    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True, blank=True
    )
    # Quantity tracking
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name=_("Quantity")
    )

    # Reorder management
    low_stock_threshold = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=5,
        verbose_name=_("Low Stock Threshold")
    )
    reorder_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=10,
        verbose_name=_("Reorder Quantity")
    )

    # Timestamps
    last_updated = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Last Updated")
    )
    last_physical_count = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name=_("Last Physical Count")
    )
    last_physical_count_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        default=0,
        verbose_name=_("Last Physical Count Quantity")
    )

    last_efris_sync = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Last EFRIS Sync")
    )
    efris_sync_required = models.BooleanField(
        default=False,
        verbose_name=_("EFRIS Sync Required"),
        help_text=_("Flag to indicate inventory changes need EFRIS sync")
    )

    # Import tracking
    last_import_update = models.DateTimeField(null=True, blank=True)
    import_session = models.ForeignKey(
        'ImportSession',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_stock'
    )

    class Meta:
        verbose_name = _("Stock")
        verbose_name_plural = _("Store Inventory")  # User-friendly plural
        constraints = [
            models.UniqueConstraint(
                fields=['store', 'product'],
                name='unique_store_product_stock'
            )
        ]
        ordering = ['product__name']
        indexes = [
            models.Index(fields=['store', 'product']),
            models.Index(fields=['efris_sync_required']),
            models.Index(fields=['quantity']),
        ]

    def __str__(self):
        return f"{self.product.name} at {self.store.name} - {self.quantity} units"

    # Stock status properties
    @property
    def is_low_stock(self):
        """Check if stock is below threshold"""
        return self.quantity <= self.low_stock_threshold

    @property
    def needs_reorder(self):
        """Check if stock needs to be reordered"""
        return self.is_low_stock

    @property
    def status(self):
        """Get current stock status"""
        if self.quantity == 0:
            return 'Out of Stock'
        elif self.is_low_stock:
            return 'Low Stock'
        elif self.quantity <= self.low_stock_threshold * 2:
            return 'Medium Stock'
        else:
            return 'Good Stock'

    @property
    def stock_percentage(self):
        """Stock percentage compared to this store's reorder_level."""
        if not self.low_stock_threshold or self.low_stock_threshold <= 0:
            return 100
        percentage = (self.quantity / self.low_stock_threshold) * 100
        return min(100, max(0, round(percentage)))

    @property
    def variance_from_last_count(self):
        """Calculate variance from last physical count"""
        if self.last_physical_count_quantity is not None:
            return self.quantity - self.last_physical_count_quantity
        return None

    @property
    def variance_percentage(self):
        """Calculate variance percentage from last physical count"""
        if self.last_physical_count_quantity and self.last_physical_count_quantity > 0:
            variance = self.variance_from_last_count
            if variance is not None:
                return (variance / self.last_physical_count_quantity) * 100
        return None

    def save(self, *args, **kwargs):
        # Mark for EFRIS sync if store reports stock movements
        if (hasattr(self.store, 'report_stock_movements') and
                self.store.report_stock_movements and
                hasattr(self.store, 'efris_enabled') and
                self.store.efris_enabled):

            # Check if quantity changed (for existing records)
            if self.pk:
                try:
                    old_instance = Stock.objects.get(pk=self.pk)
                    if old_instance.quantity != self.quantity:
                        self.efris_sync_required = True
                except Stock.DoesNotExist:
                    pass
            else:
                # New record
                self.efris_sync_required = True

        super().save(*args, **kwargs)

    def record_physical_count(self, counted_quantity, user=None):
        """Record a physical stock count"""
        self.last_physical_count = timezone.now()
        self.last_physical_count_quantity = self.quantity  # Save current before update

        # Create adjustment movement if there's a difference
        difference = counted_quantity - self.quantity
        if difference != 0:
            from .models import StockMovement  # Avoid circular import
            StockMovement.objects.create(
                product=self.product,
                store=self.store,
                movement_type='ADJUSTMENT',
                quantity=difference,
                reference=f'Physical Count - {timezone.now().strftime("%Y-%m-%d")}',
                notes=f'Physical count adjustment. Previous: {self.quantity}, Counted: {counted_quantity}',
                created_by=user or self.store.created_by if hasattr(self.store, 'created_by') else None
            )
            # Note: StockMovement.save() will update the quantity

        self.save()

    def mark_efris_synced(self):
        """Mark inventory as synced with EFRIS"""
        self.efris_sync_required = False
        self.last_efris_sync = timezone.now()
        self.save(update_fields=['efris_sync_required', 'last_efris_sync'])

    def get_recent_movements(self, days=30):
        """Get recent stock movements for this product/store combination"""
        from django.utils import timezone
        from datetime import timedelta

        cutoff_date = timezone.now() - timedelta(days=days)
        return self.product.movements.filter(
            store=self.store,
            created_at__gte=cutoff_date
        ).order_by('-created_at')

    # Class methods for bulk operations
    @classmethod
    def get_low_stock_items(cls, store=None):
        """Get all low stock items, optionally filtered by store"""
        queryset = cls.objects.select_related('product', 'store')
        if store:
            queryset = queryset.filter(store=store)

        # Use database-level filtering for better performance
        return queryset.extra(where=["quantity <= low_stock_threshold"])

    @classmethod
    def get_reorder_items(cls, store=None):
        """Get all items that need reordering"""
        queryset = cls.objects.select_related('product', 'store')
        if store:
            queryset = queryset.filter(store=store)

        return queryset.extra(where=["quantity <= reorder_quantity"])

    @classmethod
    def items_needing_efris_sync(cls, store=None):
        """Get items that need EFRIS sync"""
        queryset = cls.objects.filter(efris_sync_required=True)
        if store:
            queryset = queryset.filter(store=store)
        return queryset.select_related('product', 'store')


class ProductBundle(models.Model):
    """
    Links a bundle/carton product to its constituent child product.

    Two use cases:
      A) Carton IS its own product (separate SKU, separate barcode,
         tracked on shelf as a carton).  is_separate_product = True.

      B) Carton is just a receive-mode shortcut: scanning the carton
         barcode adds N units of the child product and the carton
         itself is NOT stocked separately.  is_separate_product = False.
    """
    sync_id = models.UUIDField(
        default=uuid.uuid4, unique=True, db_index=True,
        editable=False, null=True, blank=True
    )

    # The bundle / carton / pack product
    parent_product = models.ForeignKey(
        'inventory.Product',
        on_delete=models.CASCADE,
        related_name='bundle_definitions',
        verbose_name=_("Bundle / Carton Product"),
        help_text=_("The product that represents the bundle (e.g. 'Soda Carton x24')")
    )

    # The individual item inside the bundle
    child_product = models.ForeignKey(
        'inventory.Product',
        on_delete=models.CASCADE,
        related_name='contained_in_bundles',
        verbose_name=_("Child / Unit Product"),
        help_text=_("The individual item (e.g. 'Soda Bottle 300ml')")
    )

    # How many child units are in one parent unit
    child_qty = models.PositiveIntegerField(
        default=1,
        verbose_name=_("Units per Bundle"),
        help_text=_("e.g. 24 for a carton of 24 bottles")
    )

    # If True: carton is stocked as its own product (has its own Stock row).
    # If False: scanning the parent just adds child_qty to the child product.
    is_separate_product = models.BooleanField(
        default=False,
        verbose_name=_("Track carton stock separately"),
        help_text=_(
            "ON = carton has its own stock level. "
            "OFF = scanning carton adds units directly to child product."
        )
    )

    # When receiving a bundle, what cost price to record per child unit
    # (optional — falls back to child_product.cost_price)
    cost_price_per_unit = models.DecimalField(
        max_digits=12, decimal_places=2,
        null=True, blank=True,
        verbose_name=_("Cost price per unit (override)"),
        help_text=_("Leave blank to use child product's cost price")
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Product Bundle")
        verbose_name_plural = _("Product Bundles")
        unique_together = [('parent_product', 'child_product')]
        ordering = ['parent_product__name']

    def __str__(self):
        return (
            f"{self.parent_product.name} "
            f"→ {self.child_qty}x {self.child_product.name}"
        )

    @property
    def effective_cost_per_unit(self):
        if self.cost_price_per_unit:
            return self.cost_price_per_unit
        return self.child_product.cost_price


# ------------------------------------------------------------------ #
#  2. BarcodeLabel                                                     #
#     Print queue: when a product needs a label printed,              #
#     a row is created here.  The PDF generator reads pending rows.   #
# ------------------------------------------------------------------ #

class BarcodeLabel(models.Model):
    """
    Print queue for barcode labels.

    When staff need to print labels (for new products, cartons, or
    re-labelling), a BarcodeLabel row is created.  The label PDF
    view reads all 'pending' rows and renders a printable A4 sheet.
    """

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('printed', 'Printed'),
        ('cancelled', 'Cancelled'),
    ]

    LABEL_SIZE_CHOICES = [
        ('small', 'Small (38×19mm)'),
        ('medium', 'Medium (57×32mm)'),
        ('large', 'Large (100×50mm)'),
    ]

    sync_id = models.UUIDField(
        default=uuid.uuid4, unique=True, db_index=True,
        editable=False, null=True, blank=True
    )

    product = models.ForeignKey(
        'inventory.Product',
        on_delete=models.CASCADE,
        related_name='barcode_labels',
        verbose_name=_("Product")
    )

    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='barcode_labels',
        verbose_name=_("Store"),
        help_text=_("Store requesting the print (optional)")
    )

    quantity = models.PositiveIntegerField(
        default=1,
        verbose_name=_("Number of labels to print")
    )

    label_size = models.CharField(
        max_length=10,
        choices=LABEL_SIZE_CHOICES,
        default='medium',
        verbose_name=_("Label size")
    )

    # Whether to include price on label
    include_price = models.BooleanField(
        default=True,
        verbose_name=_("Print price on label")
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True
    )

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='barcode_label_requests',
        verbose_name=_("Requested by")
    )

    printed_at = models.DateTimeField(null=True, blank=True)
    printed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='barcode_labels_printed',
        verbose_name=_("Printed by")
    )

    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = _("Barcode Label")
        verbose_name_plural = _("Barcode Labels")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['product', 'status']),
        ]

    def __str__(self):
        return f"{self.product.name} x{self.quantity} [{self.status}]"

    def mark_printed(self, user):
        self.status = 'printed'
        self.printed_at = timezone.now()
        self.printed_by = user
        self.save(update_fields=['status', 'printed_at', 'printed_by'])


# ------------------------------------------------------------------ #
#  3. ScanSession                                                      #
#     Logs each scan session (who, which store, which mode,           #
#     how many items scanned).  Useful for audit + error tracing.     #
# ------------------------------------------------------------------ #

class ScanSession(models.Model):
    """
    Tracks a scanning session.

    A session starts when a user opens the scan UI and ends
    when they close/submit.  Each ScanEvent row belongs to a session.
    """

    MODE_CHOICES = [
        ('receive_stock', 'Receive Stock'),
        ('stock_count', 'Stock Count'),
        ('product_lookup', 'Product Lookup'),
        ('pos_checkout', 'POS Checkout'),
    ]

    STATUS_CHOICES = [
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('abandoned', 'Abandoned'),
    ]

    sync_id = models.UUIDField(
        default=uuid.uuid4, unique=True, db_index=True,
        editable=False, null=True, blank=True
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='scan_sessions'
    )

    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='scan_sessions'
    )

    mode = models.CharField(
        max_length=20,
        choices=MODE_CHOICES,
        default='receive_stock',
        verbose_name=_("Scan mode")
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='active',
        db_index=True
    )

    # Running totals (updated on each scan event)
    total_scans = models.PositiveIntegerField(default=0)
    successful_scans = models.PositiveIntegerField(default=0)
    failed_scans = models.PositiveIntegerField(default=0)
    new_products_created = models.PositiveIntegerField(default=0)

    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = _("Scan Session")
        verbose_name_plural = _("Scan Sessions")
        ordering = ['-started_at']

    def __str__(self):
        return (
            f"{self.user} | {self.get_mode_display()} | "
            f"{self.store} | {self.started_at:%Y-%m-%d %H:%M}"
        )

    def complete(self):
        self.status = 'completed'
        self.completed_at = timezone.now()
        self.save(update_fields=['status', 'completed_at'])

    @property
    def duration(self):
        end = self.completed_at or timezone.now()
        return end - self.started_at


class ScanEvent(models.Model):
    """
    One barcode scan within a ScanSession.

    Records what was scanned, what happened, and any error.
    Used for the session summary and audit trail.
    """

    OUTCOME_CHOICES = [
        ('stock_added', 'Stock Added'),
        ('product_created', 'Product Created'),
        ('product_found', 'Product Found (lookup)'),
        ('added_to_cart', 'Added to Cart (POS)'),
        ('not_found', 'Not Found'),
        ('error', 'Error'),
    ]

    session = models.ForeignKey(
        ScanSession,
        on_delete=models.CASCADE,
        related_name='events'
    )

    barcode_scanned = models.CharField(max_length=100, db_index=True)

    product = models.ForeignKey(
        'inventory.Product',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='scan_events'
    )

    outcome = models.CharField(
        max_length=20,
        choices=OUTCOME_CHOICES,
        db_index=True
    )

    # For stock_added outcome
    quantity_added = models.DecimalField(
        max_digits=10, decimal_places=2,
        null=True, blank=True
    )

    # Bundle expansion: was this a carton scan?
    was_bundle_scan = models.BooleanField(default=False)
    bundle = models.ForeignKey(
        ProductBundle,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='scan_events'
    )

    error_message = models.TextField(blank=True)
    scanned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Scan Event")
        verbose_name_plural = _("Scan Events")
        ordering = ['-scanned_at']
        indexes = [
            models.Index(fields=['session', 'scanned_at']),
            models.Index(fields=['barcode_scanned']),
        ]

    def __str__(self):
        return f"{self.barcode_scanned} → {self.outcome} @ {self.scanned_at:%H:%M:%S}"


class StockMovement(OfflineIDMixin, models.Model):
    MOVEMENT_TYPES = [
        ('PURCHASE', 'Purchase'),
        ('SALE', 'Sale'),
        ('RETURN', 'Return'),
        ('VOID', 'Void'),
        ('REFUND', 'Refund'),
        ('ADJUSTMENT', 'Adjustment'),
        ('TRANSFER_IN', 'Transfer In'),
        ('TRANSFER_OUT', 'Transfer Out'),
    ]
    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True, blank=True
    )
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='movements', verbose_name=_("Product"))
    store = models.ForeignKey('stores.Store', on_delete=models.CASCADE, related_name='stock_movements',
                              verbose_name=_("Store"))
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_TYPES, verbose_name=_("Movement Type"))
    quantity = models.DecimalField(max_digits=12, decimal_places=3, verbose_name=_("Quantity"))
    reference = models.CharField(max_length=100, blank=True, null=True, verbose_name=_("Reference"))
    notes = models.TextField(blank=True, null=True, verbose_name=_("Notes"))
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True,
                                     verbose_name=_("Unit Price"))
    total_value = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True,
                                      verbose_name=_("Total Value"))
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created At"))

    # ==================== NEW: EFRIS Sync Fields ====================
    defer_efris_sync = models.BooleanField(default=False, verbose_name=_("Defer EFRIS Sync"))
    synced_to_efris = models.BooleanField(default=False, verbose_name=_("Synced to EFRIS"))
    efris_sync_attempted = models.BooleanField(default=False, verbose_name=_("EFRIS Sync Attempted"))
    efris_sync_error = models.TextField(blank=True, verbose_name=_("EFRIS Sync Error"))
    efris_synced_at = models.DateTimeField(null=True, blank=True, verbose_name=_("EFRIS Synced At"))

    class Meta:
        verbose_name = _("Stock Movement")
        verbose_name_plural = _("Stock Movements")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['store', 'product', '-created_at']),
            models.Index(fields=['movement_type', '-created_at']),
            models.Index(fields=['reference']),
            models.Index(fields=['synced_to_efris', 'efris_sync_attempted']),
        ]

    def __str__(self):
        return f"{self.movement_type} of {self.product.name} at {self.store.name}"

    def save(self, *args, **kwargs):
        import logging
        from django.db import transaction, connection
        from decimal import Decimal, InvalidOperation
        logger = logging.getLogger(__name__)

        # Calculate total value if unit price provided
        if self.unit_price is not None and self.total_value is None:
            # Force both operands to Decimal before multiplying
            self.total_value = Decimal(str(self.unit_price)) * Decimal(str(self.quantity))

        logger.info(f"💾 StockMovement.save() called - Type: {self.movement_type}, Qty: {self.quantity}")

        is_new = self.pk is None

        # ========== CRITICAL: Only skip stock update for SALE movements ==========
        # Stock is already deducted by SaleItem.deduct_stock()
        if self.movement_type == 'SALE':
            logger.info(f"⏭️ Skipping stock update for {self.movement_type} - already handled by SaleItem")
            super().save(*args, **kwargs)

            # ✅ DEFER EFRIS sync for SALE movements until sale is fiscalized
            if is_new and not self.defer_efris_sync:
                # Check if the related sale is already fiscalized
                if self._should_sync_to_efris():
                    self._queue_efris_sync()
                else:
                    logger.info(f"⏸️ Deferring EFRIS sync for movement {self.id} - sale not yet fiscalized")
            return
        # ========================================================================

        # Save the movement first
        super().save(*args, **kwargs)

        # Update stock for all other movement types
        stock_record, created = Stock.objects.get_or_create(
            product=self.product,
            store=self.store,
            defaults={'quantity': 0}
        )

        old_qty = stock_record.quantity
        logger.info(f"📊 Stock BEFORE movement save update: {old_qty}")

        # Define which movements increase vs decrease stock
        INCREASE_MOVEMENTS = ['PURCHASE', 'RETURN', 'TRANSFER_IN']
        DECREASE_MOVEMENTS = ['TRANSFER_OUT']

        movement_qty = Decimal(str(self.quantity))  # guarantee Decimal regardless of input type

        if self.movement_type in INCREASE_MOVEMENTS:
            stock_record.quantity = Decimal(str(stock_record.quantity)) + movement_qty
        elif self.movement_type in DECREASE_MOVEMENTS:
            stock_record.quantity = Decimal(str(stock_record.quantity)) - movement_qty
        elif self.movement_type == 'ADJUSTMENT':
            stock_record.quantity = Decimal(str(stock_record.quantity)) + movement_qty

        stock_record.save()
        logger.info(f"📊 Stock AFTER movement save update: {stock_record.quantity} (was {old_qty})")

        # Queue EFRIS sync for non-SALE movements
        if is_new and not self.defer_efris_sync:
            self._queue_efris_sync()

    def _should_sync_to_efris(self):
        """
        Check if this SALE movement should be synced to EFRIS.
        Only sync if the related sale is already fiscalized.
        """
        if self.movement_type != 'SALE' or not self.reference:
            return True  # Non-SALE movements can sync immediately

        try:
            from sales.models import Sale

            # Extract sale number from reference
            # Reference format: "Sale #RCP-20240101-0001" or just "RCP-20240101-0001"
            sale_number = self.reference.replace('Sale #', '').strip()

            # Find the related sale
            sale = Sale.objects.filter(
                document_number=sale_number,
                store=self.store
            ).first()

            if not sale:
                logger.warning(f"Sale {sale_number} not found for movement {self.id}")
                return False

            # Check if sale is fiscalized
            if sale.is_fiscalized:
                logger.info(f"✅ Sale {sale_number} is fiscalized - can sync movement")
                return True
            else:
                logger.info(f"⏸️ Sale {sale_number} not yet fiscalized - deferring movement sync")
                return False

        except Exception as e:
            logger.error(f"Error checking sale fiscalization status: {e}")
            return False

    def _queue_efris_sync(self):
        """Queue EFRIS sync task"""
        try:
            from inventory.tasks import sync_stock_movement_to_efris
            from django.db import connection, transaction

            # Use on_commit to ensure transaction is complete
            transaction.on_commit(
                lambda: sync_stock_movement_to_efris.apply_async(
                    args=[self.id, connection.schema_name],
                    countdown=5  # Wait 5 seconds before syncing
                )
            )
            logger.info(f"📤 Queued EFRIS sync for stock movement {self.id}")
        except Exception as e:
            logger.error(f"Error queuing EFRIS sync: {e}")

    def sync_to_efris_now(self):
        """
        Manually trigger EFRIS sync.
        Called after sale is fiscalized.
        """
        try:
            from inventory.tasks import sync_stock_movement_to_efris
            from django.db import connection

            # Check if already synced
            if self.synced_to_efris:
                logger.info(f"Stock movement {self.id} already synced to EFRIS")
                return True

            # Queue the sync task
            sync_stock_movement_to_efris.apply_async(
                args=[self.id, connection.schema_name],
                countdown=2  # Small delay
            )

            logger.info(f"📤 Manually queued EFRIS sync for stock movement {self.id}")
            return True

        except Exception as e:
            logger.error(f"Error manually syncing movement to EFRIS: {e}")
            return False

class ImportLog(OfflineIDMixin, models.Model):
    """Detailed log entries for import operations"""
    LOG_LEVELS = [
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('success', 'Success'),
    ]
    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True, blank=True
    )
    session = models.ForeignKey(ImportSession, on_delete=models.CASCADE, related_name='logs')
    level = models.CharField(max_length=10, choices=LOG_LEVELS)
    message = models.TextField()
    row_number = models.PositiveIntegerField(null=True, blank=True)
    details = models.JSONField(default=dict)
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['timestamp']
    
    def __str__(self):
        return f"{self.level.upper()}: {self.message[:50]}"

class ImportResult(OfflineIDMixin, models.Model):
    """Store detailed results for each imported item"""
    RESULT_TYPES = [
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('skipped', 'Skipped'),
        ('error', 'Error'),
    ]
    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True, blank=True
    )
    session = models.ForeignKey(ImportSession, on_delete=models.CASCADE, related_name='results')
    result_type = models.CharField(max_length=10, choices=RESULT_TYPES)
    row_number = models.PositiveIntegerField()
    
    # Item details
    product_name = models.CharField(max_length=255, blank=True)
    sku = models.CharField(max_length=100, blank=True)
    store_name = models.CharField(max_length=255, blank=True)
    quantity = models.IntegerField(null=True, blank=True)
    old_quantity = models.IntegerField(null=True, blank=True)  # For updates
    
    # Error details (for failed items)
    error_message = models.TextField(blank=True)
    error_details = models.JSONField(default=dict)
    
    # Raw data
    raw_data = models.JSONField(default=dict)  # Original row data
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['row_number']
    
    def __str__(self):
        return f"{self.result_type}: {self.product_name or 'Row ' + str(self.row_number)}"


class StockTransfer(OfflineIDMixin, models.Model):
    """Track stock transfers between stores"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_transit', 'In Transit'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('rejected', 'Rejected'),
    ]
    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True, blank=True
    )
    # Transfer identification
    transfer_number = models.CharField(
        max_length=50,
        unique=True,
        verbose_name=_("Transfer Number")
    )

    # Stores
    from_store = models.ForeignKey(
        'stores.Store',
        on_delete=models.PROTECT,
        related_name='transfers_out',
        verbose_name=_("From Store")
    )
    to_store = models.ForeignKey(
        'stores.Store',
        on_delete=models.PROTECT,
        related_name='transfers_in',
        verbose_name=_("To Store")
    )
    transfer_date = models.DateField(
        verbose_name=_("Transfer Date"),
        blank=True,null=True,
        help_text=_("Actual date when the stock was physically transferred."),
    )
    # Product and quantity
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='transfers',
        verbose_name=_("Product")
    )
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        validators=[MinValueValidator(0.001)],
        verbose_name=_("Quantity")
    )

    # Status tracking
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        verbose_name=_("Status")
    )

    # Notes and reference
    notes = models.TextField(
        blank=True,
        verbose_name=_("Notes")
    )
    reference = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("Reference")
    )

    # User tracking
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='transfer_requests',
        verbose_name=_("Requested By")
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transfer_approvals',
        verbose_name=_("Approved By")
    )
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transfer_completions',
        verbose_name=_("Completed By")
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("Stock Transfer")
        verbose_name_plural = _("Stock Transfers")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['transfer_number']),
            models.Index(fields=['from_store', 'to_store']),
            models.Index(fields=['status', 'created_at']),
        ]

    def __str__(self):
        return f"{self.transfer_number}: {self.product.name} ({self.from_store.name} → {self.to_store.name})"

    def save(self, *args, **kwargs):
        # Generate transfer number if not exists
        if not self.transfer_number:
            self.transfer_number = self.generate_transfer_number()

        super().save(*args, **kwargs)

    @staticmethod
    def generate_transfer_number():
        """Generate unique transfer number"""
        prefix = "TRF"
        date_part = timezone.now().strftime('%Y%m%d')

        # Get last transfer number for today
        last_transfer = StockTransfer.objects.filter(
            transfer_number__startswith=f"{prefix}-{date_part}"
        ).order_by('-transfer_number').first()

        if last_transfer:
            # Extract sequence number and increment
            last_seq = int(last_transfer.transfer_number.split('-')[-1])
            new_seq = last_seq + 1
        else:
            new_seq = 1

        return f"{prefix}-{date_part}-{new_seq:04d}"

    def clean(self):
        """Validate transfer data"""
        super().clean()

        # Cannot transfer to same store
        if self.from_store == self.to_store:
            raise ValidationError({
                'to_store': _("Cannot transfer to the same store.")
            })

        # Check if source store has enough stock
        if self.status == 'pending':
            try:
                source_stock = Stock.objects.get(
                    product=self.product,
                    store=self.from_store
                )

                if source_stock.quantity < self.quantity:
                    raise ValidationError({
                        'quantity': _(
                            f"Insufficient stock at {self.from_store.name}. "
                            f"Available: {source_stock.quantity}, Requested: {self.quantity}"
                        )
                    })
            except Stock.DoesNotExist:
                raise ValidationError({
                    'product': _(f"Product not available at {self.from_store.name}")
                })

    def approve(self, user):
        """Approve the transfer and deduct stock from source"""
        if self.status != 'pending':
            raise ValidationError("Only pending transfers can be approved.")

        with transaction.atomic():
            # Check stock availability again
            source_stock = Stock.objects.select_for_update().get(
                product=self.product,
                store=self.from_store
            )

            if source_stock.quantity < self.quantity:
                raise ValidationError(
                    f"Insufficient stock. Available: {source_stock.quantity}, "
                    f"Requested: {self.quantity}"
                )

            # Create TRANSFER_OUT movement (stock deduction happens in StockMovement.save())
            StockMovement.objects.create(
                product=self.product,
                store=self.from_store,
                movement_type='TRANSFER_OUT',
                quantity=self.quantity,
                reference=self.transfer_number,
                notes=f"Transfer to {self.to_store.name}. {self.notes}",
                created_by=user
            )

            # Update transfer status
            self.status = 'in_transit'
            self.approved_by = user
            self.approved_at = timezone.now()
            self.save()

            logger.info(
                f"Transfer {self.transfer_number} approved by {user.username}. "
                f"Stock deducted from {self.from_store.name}"
            )

    def complete(self, user):
        """Complete the transfer and add stock to destination"""
        if self.status != 'in_transit':
            raise ValidationError("Only in-transit transfers can be completed.")

        with transaction.atomic():
            # Create TRANSFER_IN movement (stock addition happens in StockMovement.save())
            StockMovement.objects.create(
                product=self.product,
                store=self.to_store,
                movement_type='TRANSFER_IN',
                quantity=self.quantity,
                reference=self.transfer_number,
                notes=f"Transfer from {self.from_store.name}. {self.notes}",
                created_by=user
            )

            # Update transfer status
            self.status = 'completed'
            self.completed_by = user
            self.completed_at = timezone.now()
            self.save()

            logger.info(
                f"Transfer {self.transfer_number} completed by {user.username}. "
                f"Stock added to {self.to_store.name}"
            )

    def cancel(self, user, reason=""):
        """Cancel the transfer and restore stock if already deducted"""
        if self.status not in ['pending', 'in_transit']:
            raise ValidationError("Cannot cancel completed or already cancelled transfers.")

        with transaction.atomic():
            # If already approved (in_transit), restore stock to source
            if self.status == 'in_transit':
                StockMovement.objects.create(
                    product=self.product,
                    store=self.from_store,
                    movement_type='ADJUSTMENT',
                    quantity=self.quantity,  # Positive to add back
                    reference=f"CANCELLED-{self.transfer_number}",
                    notes=f"Transfer cancelled. Stock restored. Reason: {reason}",
                    created_by=user
                )

            # Update transfer status
            self.status = 'cancelled'
            self.cancelled_at = timezone.now()
            self.notes = f"{self.notes}\n\nCancelled by {user.username}: {reason}"
            self.save()

            logger.info(
                f"Transfer {self.transfer_number} cancelled by {user.username}. "
                f"Reason: {reason}"
            )

    @property
    def can_be_approved(self):
        """Check if transfer can be approved"""
        return self.status == 'pending'

    @property
    def can_be_completed(self):
        """Check if transfer can be completed"""
        return self.status == 'in_transit'

    @property
    def can_be_cancelled(self):
        """Check if transfer can be cancelled"""
        return self.status in ['pending', 'in_transit']

    @property
    def duration(self):
        """Calculate transfer duration"""
        if self.completed_at and self.created_at:
            return self.completed_at - self.created_at
        return None


