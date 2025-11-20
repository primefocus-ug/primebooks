from django.db import models
from django.core.validators import MinValueValidator
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.core.validators import RegexValidator
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.exceptions import ValidationError
from .managers import ProductCategoryManager, ServiceCategoryManager
from .efris import EFRISProductMixin

User = get_user_model()


class ImportSession(models.Model):
    """Track import sessions and their results"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
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


class Category(models.Model):
    CATEGORY_TYPE_CHOICES = [
        ('product', 'Product Category'),
        ('service', 'Service Category'),
    ]

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

        # Only validate EFRIS commodity category if provided AND sync is enabled
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
                efris_type = 'service' if efris_cat.service_mark == '102' else 'product'
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
            efris_type = 'service' if efris_cat.service_mark == '102' else 'product'
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
        if self.pk:
            old_instance = Category.objects.filter(pk=self.pk).first()
            if old_instance and old_instance.efris_commodity_category_code != self.efris_commodity_category_code:
                self.efris_is_uploaded = False
                should_cascade = True
            else:
                should_cascade = False
        else:
            should_cascade = False

        # Run validation
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

class Supplier(models.Model):
    name = models.CharField(
        max_length=200,
        verbose_name=_("Supplier Name")
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
        blank=True,
        verbose_name=_("Contact Person")
    )
    phone = models.CharField(
        max_length=20,
        validators=[RegexValidator(r'^\+?[0-9]+$', 'Enter a valid phone number.')],
        verbose_name=_("Phone Number")
    )
    email = models.EmailField(
        blank=True,
        verbose_name=_("Email Address")
    )
    address = models.TextField(
        blank=True,
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

class Product(models.Model, EFRISProductMixin):
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

    def clean(self):
        """Validate product data before saving"""
        super().clean()
        
        # Get EFRIS status - default to False for safety
        efris_enabled = getattr(self, '_efris_enabled', False)
        
        # Only validate EFRIS fields if EFRIS is explicitly enabled
        if efris_enabled:
            if self.category and not self.category.efris_commodity_category_code:
                raise ValidationError({
                    'category': _("Selected category does not have an EFRIS commodity category assigned.")
                })
            
            if self.category and not self.category.efris_is_leaf_node:
                raise ValidationError({
                    'category': _("Selected category's EFRIS commodity category is not a leaf node.")
                })

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
            'E': 18.00,  # Plus excise duty
        }
        return tax_rate_values.get(self.tax_rate, 18.00)

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
        """Returns product tax information for EFRIS compliance"""
        return {
            'product_name': self.efris_goods_name,
            'product_code': self.efris_goods_code,
            'tax_rate': self.get_tax_rate_display(),
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
        return {
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
            'currency': 'UGX'
        }


class Service(models.Model):
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

        # Only validate EFRIS fields if EFRIS is explicitly enabled
        if efris_enabled:
            # Validate category is set when EFRIS sync is enabled
            if self.efris_auto_sync_enabled and not self.category:
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
            if efris_cat.service_mark != '102':
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
        """Override save to handle EFRIS sync logic"""
        if self.pk:
            old_instance = Service.objects.filter(pk=self.pk).first()
            if old_instance:
                # Check if price or critical fields changed
                if (old_instance.unit_price != self.unit_price or
                        old_instance.tax_rate != self.tax_rate or
                        old_instance.category_id != self.category_id):
                    self.efris_is_uploaded = False

        # Run validation
        self.full_clean()

        super().save(*args, **kwargs)

class Stock(models.Model):
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

class StockMovement(models.Model):
    MOVEMENT_TYPES = [
        ('PURCHASE', 'Purchase'),
        ('SALE', 'Sale'),
        ('RETURN', 'Return'),
        ('ADJUSTMENT', 'Adjustment'),
        ('TRANSFER_IN', 'Transfer In'),
        ('TRANSFER_OUT', 'Transfer Out'),
    ]
    product = models.ForeignKey( Product, on_delete=models.CASCADE, related_name='movements', verbose_name=_("Product") )
    store = models.ForeignKey( 'stores.Store', on_delete=models.CASCADE, related_name='stock_movements', verbose_name=_("Store") )
    movement_type = models.CharField( max_length=20, choices=MOVEMENT_TYPES, verbose_name=_("Movement Type") )
    quantity = models.DecimalField( max_digits=12, decimal_places=3,  verbose_name=_("Quantity") )
    reference = models.CharField( max_length=100, blank=True, null=True,  verbose_name=_("Reference"))
    notes = models.TextField( blank=True, null=True, verbose_name=_("Notes") )
    unit_price = models.DecimalField( max_digits=12, decimal_places=2, blank=True,null=True, verbose_name=_("Unit Price") )
    total_value = models.DecimalField( max_digits=12,decimal_places=2,blank=True,null=True,verbose_name=_("Total Value"))
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True,verbose_name=_("Created At"))

    class Meta:
        verbose_name = _("Stock Movement")
        verbose_name_plural = _("Stock Movements")
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.movement_type} of {self.product.name} at {self.store.name}"

    def save(self, *args, **kwargs):
        import logging
        logger = logging.getLogger(__name__)

        # Calculate total value if unit price provided
        if self.unit_price is not None and self.total_value is None:
            self.total_value = self.unit_price * self.quantity

        logger.info(f"💾 StockMovement.save() called - Type: {self.movement_type}, Qty: {self.quantity}")

        super().save(*args, **kwargs)

        # Get stock BEFORE update
        stock_record, created = Stock.objects.get_or_create(
            product=self.product,
            store=self.store,
            defaults={'quantity': 0}
        )

        old_qty = stock_record.quantity
        logger.info(f"📊 Stock BEFORE movement save update: {old_qty}")

        if self.movement_type in ['PURCHASE', 'RETURN', 'TRANSFER_IN', 'ADJUSTMENT']:
            stock_record.quantity += self.quantity  # ADDS stock
            logger.info(f"➕ ADDING {self.quantity} to stock")
        elif self.movement_type in ['SALE', 'TRANSFER_OUT']:
            stock_record.quantity -= self.quantity  # SUBTRACTS stock
            logger.info(f"➖ SUBTRACTING {self.quantity} from stock")

        stock_record.save()
        logger.info(f"📊 Stock AFTER movement save update: {stock_record.quantity} (was {old_qty})")


class ImportLog(models.Model):
    """Detailed log entries for import operations"""
    LOG_LEVELS = [
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('success', 'Success'),
    ]
    
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

class ImportResult(models.Model):
    """Store detailed results for each imported item"""
    RESULT_TYPES = [
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('skipped', 'Skipped'),
        ('error', 'Error'),
    ]
    
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
