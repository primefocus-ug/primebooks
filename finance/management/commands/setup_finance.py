from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction
from datetime import date
from finance.models import (
    ChartOfAccounts, AccountType, Journal, JournalType,
    FiscalYear, TaxCode, AssetCategory
)

User = get_user_model()


class Command(BaseCommand):
    help = "Setup initial finance data (Chart of Accounts, Journals, Fiscal Year, etc.)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--schema",
            type=str,
            help="Tenant schema name (for multi-tenant setup)",
        )

    def handle(self, *args, **options):
        schema = options.get("schema")
        if schema:
            from django_tenants.utils import schema_context
            with schema_context(schema):
                self._run_setup(schema)
        else:
            self._run_setup()

    @transaction.atomic
    def _run_setup(self, schema=None):
        schema_display = f" for schema '{schema}'" if schema else ""
        self.stdout.write(self.style.SUCCESS(f"🚀 Starting Finance Setup{schema_display}"))

        admin = User.objects.filter(is_superuser=True).first()
        if not admin:
            self.stdout.write(self.style.ERROR("No admin user found. Please create one first."))
            return

        self.stdout.write("📘 Creating Chart of Accounts...")
        self._create_chart_of_accounts(admin)

        self.stdout.write("🧾 Creating Journals...")
        self._create_journals()

        self.stdout.write("📅 Creating Fiscal Year...")
        self._create_fiscal_year()

        self.stdout.write("💰 Creating Tax Codes...")
        self._create_tax_codes()

        self.stdout.write("🏢 Creating Asset Categories...")
        self._create_asset_categories()

        self.stdout.write(self.style.SUCCESS("✅ Finance setup completed successfully!"))

    # ----------------------------------------------------------------------
    # CHART OF ACCOUNTS
    # ----------------------------------------------------------------------
    def _create_chart_of_accounts(self, admin):
        """Creates hierarchical Chart of Accounts safely"""

        def create_account(code, name, account_type, parent=None,
                           is_header=False, allow_manual_entries=None,
                           **extra):
            """Helper to create accounts with validation logic"""
            if allow_manual_entries is None:
                allow_manual_entries = not is_header

            acc, _ = ChartOfAccounts.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "account_type": account_type,
                    "parent": parent,
                    "is_header": is_header,
                    "allow_manual_entries": allow_manual_entries,
                    "is_active": True,
                    "created_by": admin,
                    **extra,
                },
            )
            return acc

        # ---- ASSETS ----
        assets = create_account("1000", "ASSETS", AccountType.ASSET, is_header=True)
        current_assets = create_account("1100", "Current Assets", AccountType.ASSET, parent=assets, is_header=True)
        create_account("1110", "Cash on Hand", AccountType.ASSET, parent=current_assets)
        create_account("1120", "Bank Account", AccountType.ASSET, parent=current_assets, is_reconcilable=True)
        create_account("1130", "Accounts Receivable", AccountType.ASSET, parent=current_assets)
        create_account("1140", "Inventory", AccountType.ASSET, parent=current_assets)

        fixed_assets = create_account("1200", "Fixed Assets", AccountType.ASSET, parent=assets, is_header=True)
        create_account("1210", "Equipment", AccountType.ASSET, parent=fixed_assets)
        create_account("1220", "Accumulated Depreciation", AccountType.ASSET, parent=fixed_assets)

        # ---- LIABILITIES ----
        liabilities = create_account("2000", "LIABILITIES", AccountType.LIABILITY, is_header=True)
        current_liabilities = create_account("2100", "Current Liabilities", AccountType.LIABILITY, parent=liabilities, is_header=True)
        create_account("2110", "Accounts Payable", AccountType.LIABILITY, parent=current_liabilities)
        create_account("2120", "Tax Payable", AccountType.LIABILITY, parent=current_liabilities, is_tax_account=True)
        create_account("2130", "Salary Payable", AccountType.LIABILITY, parent=current_liabilities)

        # ---- EQUITY ----
        equity = create_account("3000", "EQUITY", AccountType.EQUITY, is_header=True)
        create_account("3100", "Owner Equity", AccountType.EQUITY, parent=equity)
        create_account("3200", "Retained Earnings", AccountType.EQUITY, parent=equity)

        # ---- REVENUE ----
        revenue = create_account("4000", "REVENUE", AccountType.REVENUE, is_header=True)
        create_account("4100", "Sales Revenue", AccountType.REVENUE, parent=revenue)
        create_account("4200", "Service Revenue", AccountType.REVENUE, parent=revenue)
        create_account("4300", "Other Income", AccountType.REVENUE, parent=revenue)

        # ---- EXPENSES ----
        expenses = create_account("5000", "EXPENSES", AccountType.EXPENSE, is_header=True)
        operating_expenses = create_account("5100", "Operating Expenses", AccountType.EXPENSE, parent=expenses, is_header=True)
        create_account("5110", "Salaries & Wages", AccountType.EXPENSE, parent=operating_expenses, require_cost_center=True)
        create_account("5120", "Rent Expense", AccountType.EXPENSE, parent=operating_expenses)
        create_account("5130", "Utilities", AccountType.EXPENSE, parent=operating_expenses)
        create_account("5140", "Office Supplies", AccountType.EXPENSE, parent=operating_expenses)
        create_account("5150", "Depreciation Expense", AccountType.EXPENSE, parent=operating_expenses)

        # ---- COST OF GOODS SOLD ----
        cogs = create_account("6000", "COST OF GOODS SOLD", AccountType.COST_OF_SALES, is_header=True)
        create_account("6100", "Cost of Sales", AccountType.COST_OF_SALES, parent=cogs)

        self.stdout.write(self.style.SUCCESS("  ✓ Chart of Accounts created"))

    # ----------------------------------------------------------------------
    # JOURNALS
    # ----------------------------------------------------------------------
    def _create_journals(self):
        journals = [
            ("GJ", "General Journal", JournalType.GENERAL, "GJ"),
            ("SJ", "Sales Journal", JournalType.SALES, "SJ"),
            ("PJ", "Purchase Journal", JournalType.PURCHASE, "PJ"),
            ("CR", "Cash Receipts", JournalType.CASH_RECEIPTS, "CR"),
            ("CP", "Cash Payments", JournalType.CASH_PAYMENTS, "CP"),
            ("BJ", "Bank Journal", JournalType.BANK, "BJ"),
            ("PRJ", "Payroll Journal", JournalType.PAYROLL, "PRJ"),
            ("DEP", "Depreciation Journal", JournalType.DEPRECIATION, "DEP"),
            ("ADJ", "Adjustment Journal", JournalType.ADJUSTMENT, "ADJ"),
        ]

        for code, name, journal_type, prefix in journals:
            Journal.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "journal_type": journal_type,
                    "entry_prefix": prefix,
                    "is_active": True,
                },
            )

        self.stdout.write(self.style.SUCCESS("  ✓ Journals created"))

    # ----------------------------------------------------------------------
    # FISCAL YEAR
    # ----------------------------------------------------------------------
    def _create_fiscal_year(self):
        today = date.today()

        if today.month >= 7:
            start_date = date(today.year, 7, 1)
            end_date = date(today.year + 1, 6, 30)
            name = f"FY {today.year}-{today.year + 1}"
        else:
            start_date = date(today.year - 1, 7, 1)
            end_date = date(today.year, 6, 30)
            name = f"FY {today.year - 1}-{today.year}"

        fiscal_year, created = FiscalYear.objects.get_or_create(
            start_date=start_date,
            defaults={
                "name": name,
                "code": f"FY{today.year}",
                "end_date": end_date,
                "is_current": True,
            },
        )

        if created:
            self.stdout.write(self.style.SUCCESS(f"  ✓ Fiscal Year created: {name}"))
        else:
            self.stdout.write(self.style.WARNING(f"  ⚠ Fiscal Year already exists: {name}"))

    # ----------------------------------------------------------------------
    # TAX CODES
    # ----------------------------------------------------------------------
    def _create_tax_codes(self):
        tax_payable = ChartOfAccounts.objects.get(code="2120")

        TaxCode.objects.get_or_create(
            code="VAT18",
            defaults={
                "name": "VAT 18%",
                "default_rate": 18.00,
                "tax_collected_account": tax_payable,
                "tax_paid_account": tax_payable,
                "efris_tax_category": "01",
                "is_active": True,
            },
        )

        TaxCode.objects.get_or_create(
            code="VAT0",
            defaults={
                "name": "VAT 0% (Zero-rated)",
                "default_rate": 0.00,
                "tax_collected_account": tax_payable,
                "tax_paid_account": tax_payable,
                "efris_tax_category": "02",
                "is_active": True,
            },
        )

        self.stdout.write(self.style.SUCCESS("  ✓ Tax codes created"))

    # ----------------------------------------------------------------------
    # ASSET CATEGORIES
    # ----------------------------------------------------------------------
    def _create_asset_categories(self):
        equipment_account = ChartOfAccounts.objects.get(code="1210")
        accumulated_dep = ChartOfAccounts.objects.get(code="1220")
        dep_expense = ChartOfAccounts.objects.get(code="5150")

        AssetCategory.objects.get_or_create(
            code="COMP",
            defaults={
                "name": "Computer Equipment",
                "asset_account": equipment_account,
                "depreciation_account": accumulated_dep,
                "depreciation_expense_account": dep_expense,
                "default_depreciation_method": "STRAIGHT_LINE",
                "default_useful_life_years": 3,
                "default_salvage_value_percentage": 10,
                "is_active": True,
            },
        )

        AssetCategory.objects.get_or_create(
            code="FURN",
            defaults={
                "name": "Furniture & Fixtures",
                "asset_account": equipment_account,
                "depreciation_account": accumulated_dep,
                "depreciation_expense_account": dep_expense,
                "default_depreciation_method": "STRAIGHT_LINE",
                "default_useful_life_years": 5,
                "default_salvage_value_percentage": 10,
                "is_active": True,
            },
        )

        self.stdout.write(self.style.SUCCESS("  ✓ Asset categories created"))
