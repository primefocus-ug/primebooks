class NavigationItem:
    def __init__(self, name, url_name=None, url=None, icon=None, permission=None,
                 children=None, visible_func=None, css_class="", url_params=None,
                 url_kwargs_func=None, requires_efris=False, requires_module=None,
                 is_divider=False, url_query_func=None, onclick=None):
        self.name = name
        self.url_name = url_name
        self.url = url
        self.icon = icon
        self.permission = permission
        self.children = children or []
        self.visible_func = visible_func
        self.css_class = css_class
        self.url_params = url_params or []
        self.url_kwargs_func = url_kwargs_func
        self.requires_efris = requires_efris
        self.requires_module = requires_module
        self.is_divider = is_divider
        # Optional callable(request) → dict of query string params to append
        self.url_query_func = url_query_func
        # Optional JS expression — renders as onclick="..." and skips URL resolution
        self.onclick = onclick

    def is_efris_enabled(self, request):
        """Check if EFRIS is enabled for current tenant/company"""
        if not request:
            return False

        # Check tenant
        if hasattr(request, 'tenant'):
            return getattr(request.tenant, 'efris_enabled', False)

        # Check user's company
        if hasattr(request, 'user') and request.user.is_authenticated:
            if hasattr(request.user, 'company'):
                return getattr(request.user.company, 'efris_enabled', False)

            # Check via store
            if hasattr(request.user, 'stores') and request.user.stores.exists():
                store = request.user.stores.first()
                if store and hasattr(store, 'company'):
                    return getattr(store.company, 'efris_enabled', False)

        return False

    def is_visible(self, user, request=None):
        """Return True if this item should appear in the navigation."""
        # Dividers: always show (they're hidden automatically when they'd be
        # adjacent to nothing, because filter_items strips empty sections)
        if self.is_divider:
            return True

        # Module guard — must come BEFORE permission check
        if self.requires_module:
            active = getattr(request, 'active_modules', set()) if request else set()
            if self.requires_module not in active:
                return False

        # EFRIS guard
        if self.requires_efris and not self.is_efris_enabled(request):
            return False

        # Custom function (e.g. staff-only)
        if self.visible_func:
            return self.visible_func(user)

        if not user.is_authenticated:
            return False

        # Permission check
        if self.permission:
            if isinstance(self.permission, str):
                return user.has_perm(self.permission)
            elif isinstance(self.permission, list):
                return any(user.has_perm(p) for p in self.permission)

        return True

    def get_url(self, request=None, **kwargs):
        """
        Get URL with support for parameters
        """
        if self.url:
            return self.url

        if self.url_name:
            try:
                from django.urls import reverse

                # If we have a function to generate kwargs, use it
                if self.url_kwargs_func and request:
                    url_kwargs = self.url_kwargs_func(request, **kwargs)
                    return reverse(self.url_name, kwargs=url_kwargs)

                # If we have static kwargs provided, use them
                if kwargs:
                    # Filter kwargs to only include those needed for this URL
                    if self.url_params:
                        filtered_kwargs = {k: v for k, v in kwargs.items() if k in self.url_params}
                        if filtered_kwargs:
                            return reverse(self.url_name, kwargs=filtered_kwargs)

                base_url = reverse(self.url_name)

                # Append query string if url_query_func is provided
                if self.url_query_func and request:
                    try:
                        from urllib.parse import urlencode
                        params = self.url_query_func(request)
                        if params:
                            return f"{base_url}?{urlencode(params)}"
                    except Exception:
                        pass

                return base_url
            except Exception:
                return '#'

        return '#'

    def matches_url(self, request):
        """
        Check if this navigation item matches the current request
        """
        if not request or not hasattr(request, 'resolver_match') or not request.resolver_match:
            return False

        current_url_name = request.resolver_match.url_name
        current_namespace = request.resolver_match.namespace

        if current_namespace and ':' in str(self.url_name):
            namespace, view_name = str(self.url_name).split(':', 1)
            return current_namespace == namespace and current_url_name == view_name

        return current_url_name == str(self.url_name)


# ── URL query helpers ──────────────────────────────────────────────────────────

def _today_sales_query(request):
    """Returns date_from / date_to query params pinned to today's date."""
    from django.utils import timezone
    today = timezone.now().strftime("%Y-%m-%d")
    return {"date_from": today, "date_to": today}


# Enhanced navigation items with parameter support
NAVIGATION_ITEMS = [
    NavigationItem(
            name="App Store",
            url_name="companies:module_store",
            icon="bi bi-bag-check",
        ),
    NavigationItem(
        name="Tracker",
        url_name="tracker-report",
        permission="company.view_company"
    ),
    NavigationItem(
        name="Create Sale",
        url_name="sales:create_sale",
        icon="bi bi-receipt-cutoff",
        permission="sales.add_sale",
        css_class="nav-highlight-pulse",
        requires_module="sales",
    ),
    NavigationItem(
        name="Quick Sale",
        url_name="sales:quick_sale",
        icon="bi bi-lightning-charge",
        permission="sales.add_sale",
        css_class="nav-highlight-success",
        requires_module="sales",
    ),
    NavigationItem(
        name="Add Product",
        icon="bi bi-plus-square",
        permission="inventory.add_product",
        requires_module="inventory",
        onclick="event.preventDefault(); GPM.open();",
    ),
    NavigationItem(
        name="Today's Sales",
        url_name="sales:sales_list",
        icon="bi bi-calendar-day",
        permission="sales.view_sale",
        css_class="nav-highlight-today",
        requires_module="sales",
        url_query_func=_today_sales_query,
    ),
    NavigationItem(
        name="Create Expense",
        url_name="expenses:expense_create",
        icon="bi bi-plus-circle",
        permission="expenses.expense_create",
        css_class="nav-highlight-danger",
        requires_module="expenses",
    ),
    NavigationItem(
        name="Customers",
        icon="bi bi-people",
        url_name="customers:dashboard",
        permission="customers.view_customer",
        requires_module='customers',
    ),
    NavigationItem(name="--", is_divider=True),
    NavigationItem(
        name="Sales",
        icon="bi bi-cart-check",
        permission="sales.view_sale",
        requires_module="sales",
        children=[
            NavigationItem(
                name="All Sales",
                url_name="sales:sales_list",
                icon="bi bi-list-check",
                permission="sales.view_sale",
                requires_module = "sales",
            ),
            NavigationItem(
                name="Create Sale",
                url_name="sales:create_sale",
                icon="bi bi-plus-circle",
                permission="sales.add_sale",
                css_class="nav-highlight-pulse",
                requires_module = "sales",
            ),
            NavigationItem(
                name="Quick Sale",
                url_name="sales:quick_sale",
                icon="bi bi-plus-circle",
                permission="sales.add_sale",
                css_class="nav-highlight-success",
                requires_module="sales",
            ),
            NavigationItem(
                name="Today's Sales",
                url_name="sales:sales_list",
                icon="bi bi-calendar-day",
                permission="sales.view_sale",
                css_class="nav-highlight-today",
                requires_module="sales",
                url_query_func=_today_sales_query,
            ),
        ]
    ),
    NavigationItem(
        name="Inventory",
        icon="bi bi-boxes",
        permission="inventory.view_product",
        requires_module="inventory",
        children=[
            NavigationItem(
                name="Inventory Dashboard",
                url_name="inventory:dashboard",
                icon="bi bi-speedometer2",
                permission="inventory.view_product",
                requires_module="inventory",
            ),
            NavigationItem(
                name="Low Stock Report",
                url_name="stores:low_stock_alert",
                icon="bi bi-exclamation-triangle",
                css_class="text-warning",
                permission="inventory.view_stock",
                requires_module="inventory",
            ),
            NavigationItem(
                name="All Products",
                url_name="inventory:product_list",
                icon="bi bi-basket",
                permission="inventory.view_product",
                requires_module="inventory",
            ),
            NavigationItem(
                name="Stock Transfers",
                url_name="inventory:transfer_list",
                icon="bi bi-arrow-left-right",
                permission="inventory.view_stocktransfer",
                requires_module="inventory",
            ),
            NavigationItem(
                name="Bulk Import",
                url_name="inventory:product_import",
                icon="bi bi-upload",
                permission="inventory.add_product",
                requires_module="inventory",
            ),
        ]
    ),
    NavigationItem(name="--", is_divider=True),
    NavigationItem(
        name="Services",
        icon="bi bi-briefcase",
        permission="inventory.view_service",
        requires_module="inventory",
        children=[
            NavigationItem(
                name="All Services",
                url_name="inventory:service_list",
                icon="bi bi-list-task",
                permission="inventory.view_service",
                requires_module='inventory',
            ),
            NavigationItem(
                name="Add Service",
                url_name="inventory:service_create",
                icon="bi bi-plus-circle",
                permission="inventory.add_service",
                requires_module="inventory",
            ),
        ],
    ),
    NavigationItem(name="--", is_divider=True),
    NavigationItem(
        name="Finance & Expenses",
        icon="bi bi-cash-stack",
        permission="expenses.view_expense",
        requires_module="expenses",
        children=[
            NavigationItem(
                name="Dashboard",
                url_name="expenses:dashboard",
                icon="bi bi-speedometer2",
                permission="expenses.view_expense",
                requires_module='expenses',
            ),
            NavigationItem(
                name="Create Expense",
                url_name="expenses:expense_create",
                icon="bi bi-coin",
                permission="expenses.add_expense",
                requires_module="expenses",
            ),
            NavigationItem(
                name="Expense List",
                url_name="expenses:expense_list",
                icon="bi bi-coin",
                permission="expenses.view_expense",
                requires_module='expenses',
            ),
            NavigationItem(
                name="Reports",
                url_name="expenses:analytics",
                icon="bi bi-file-earmark-bar-graph",
                permission="expenses.view_expense",
                requires_module='expenses',
            ),
            NavigationItem(
                name="Budget",
                url_name="expenses:budget_list",
                icon="bi bi-file-earmark-bar-graph",
                permission="expenses.view_budget",
                requires_module='expenses',
            ),


        ],),
    NavigationItem(name="--", is_divider=True),
    NavigationItem(
        name="EFRIS",
        requires_efris=True,
        icon="bi bi-receipt",  # Fiscal / invoicing system
        requires_module="efris",
        children=[
            NavigationItem(
                name="Connect EFRIS",
                url_name="efris:configuration",
                icon="bi bi-plug",  # Connection / integration
                permission="efris.view_efrisconfiguration",
                requires_efris=True,
                requires_module='efris',
            ),
            NavigationItem(
                name="System Dictionary",
                url_name="efris:system_dictionary",
                icon="bi bi-journal-text",  # Reference / dictionary data
                permission="efris.view_efrissystemdictionary",
                requires_efris=True,
                requires_module='efris',
            ),
            NavigationItem(
                name="Dashboard",
                url_name="efris:dashboard",
                icon="bi bi-speedometer2",  # Overview / metrics
                permission="company.view_company",
                requires_efris=True,
                requires_module='efris',
            ),
            NavigationItem(
                name="Commodity Categories",
                url_name="efris:commodity_categories",
                icon="bi bi-tags",  # Categories / classification
                permission="company.view_efriscommoditycategory",
                requires_efris=True,
                requires_module='efris',
            ),
            NavigationItem(
                name="Commodity Updates",
                url_name="efris:commodity_category_updates",
                icon="bi bi-arrow-repeat",  # Sync / updates
                permission="company.view_efriscommoditycategory",
                requires_efris=True,
                requires_module='efris',
            ),
            NavigationItem(
                name="EFRIS Products",
                url_name="efris:product_list",
                icon="bi bi-box-seam",  # Products / inventory items
                permission="inventory.add_products",
                requires_efris=True,
                requires_module='efris',
            ),
            NavigationItem(
                name="EFRIS Invoices",
                url_name="efris:invoice_list",
                icon="bi bi-receipt-cutoff",  # Invoices / receipts
                permission="invoices.view_invoices",
                requires_efris=True,
                requires_module='efris',
            ),
            NavigationItem(
                name="Stock Management",
                url_name="efris:stock_management_dashboard",
                icon="bi bi-clipboard-data",  # Stock levels / management
                permission="inventory.view_stock",
                requires_efris=True,
                requires_module='efris',
            ),
            NavigationItem(
                name="ZReports",
                url_name="efris:zreport_list",
                icon="bi bi-bookmark",
                permission="reports.view_savedreport",
                requires_efris=True,
                requires_module='efris',
            ),
        ]
    ),
    NavigationItem(
        name="Reports",
        icon="bi bi-file-earmark-bar-graph",
        permission="reports.view_savedreport",
        requires_module='reports',
        children=[
            NavigationItem(
                name="Dashboard",
                url_name="reports:dashboard",
                icon="bi bi-speedometer2",
                permission="reports.view_savedreport",
                requires_module='reports',
            ),
            NavigationItem(
                name="Download Reports",
                url_name="reports:history",
                icon="bi bi-bookmark",
                permission="reports.view_savedreport",
                requires_module='reports',
            ),
            NavigationItem(
                name="Saved Reports",
                url_name="reports:saved_reports",
                icon="bi bi-bookmark",
                permission="reports.view_savedreport",
                requires_module='reports',
            ),
            NavigationItem(
                name="Create Report",
                url_name="reports:create_saved_report",
                icon="bi bi-plus-circle",
                permission="reports.add_savedreport",
                requires_module='reports',
            ),
            NavigationItem(
                name="Report Schedules",
                url_name="reports:schedules",
                icon="bi bi-calendar-check",
                permission="reports.view_reportschedule",
                requires_module='reports',
            ),
            NavigationItem(
                name="Business Health",
                url_name="reports:combined_business",
                icon="bi bi-calendar-check",
                permission="reports.view_reportschedule",
                requires_module='reports',
            ),
            NavigationItem(
                name="Analytics",
                url_name="reports:analytics",
                icon="bi bi-graph-up",
                permission="reports.view_report",
                requires_module='reports',
            ),
        ]
    ),
    NavigationItem(name="--", is_divider=True),
    NavigationItem(
        name="Invoices",
        icon="bi bi-receipt",
        permission="invoices.view_invoice",
        requires_module='invoices',
        children=[
            NavigationItem(
                name="Dashboard",
                url_name="invoices:dashboard",
                icon="bi bi-speedometer2",
                permission="invoices.view_invoice",
                requires_module='invoices',
            ),
            NavigationItem(
                name="All Invoices",
                url_name="invoices:list",
                icon="bi bi-receipt-cutoff",
                permission="invoices.view_invoice",
                requires_module='invoices',
            ),
            NavigationItem(
                name="Create Invoice",
                url_name="sales:create_sale",
                icon="bi bi-plus-circle",
                permission="sales.add_sale",
                requires_module='invoices',
            ),
            NavigationItem(
                name="Invoice Analytics",
                url_name="invoices:analytics",
                icon="bi bi-graph-up",
                permission="invoices.view_invoice",
                requires_module='invoices',
            ),
            NavigationItem(
                name="Payments",
                url_name="invoices:payments",
                icon="bi bi-credit-card",
                permission="invoices.view_invoicepayment",
                requires_module='invoices',
            ),
        ]
    ),
    NavigationItem(
        name="Company",
        icon="bi bi-building",
        permission="company.view_company",
        children=[
            NavigationItem(
                name="Dashboard",
                url_name="stores:tenant_overview",
                icon="bi bi-speedometer2",
                permission="company.view_company",
            ),
            NavigationItem(
                name="Subscription Plans",
                url_name="companies:subscription_plans",
                icon="bi bi-diagram-3",
                permission="company.view_subscriptionplan"
            ),
            NavigationItem(
            name="Billing History",
            url_name="companies:billing_history",
            icon="bi bi-receipt",
            permission="company.view_subscriptionplan"
            ),
            NavigationItem(
                name="Branches",
                url_name="companies:branch_list",
                icon="bi bi-diagram-3",
                permission="stores.view_store"
            ),
            NavigationItem(
                name="Employees",
                icon="bi bi-people-fill",
                permission="accounts.add_customuser",
                children=[
                    NavigationItem(
                        name="All Employees",
                        url_name="user_list",
                        icon="bi bi-list-ul",
                        permission="accounts.add_customuser"
                    ),
                    NavigationItem(
                        name="Export Employees",
                        url_name="companies:employee_export",
                        icon="bi bi-download",
                        permission="accounts.add_customuser"
                    ),
                ]
            ),
        ]
    ),

    NavigationItem(name="--", is_divider=True),

    NavigationItem(
        name="Branch Management",
        icon="bi bi-shop",
        requires_module='stores',
        children=[
            NavigationItem(
                name="Branch Dashboard",
                url_name="stores:store_dashboard",
                icon="bi bi-speedometer2",
                permission='stores.view_store',
                requires_module='stores',
                ),
            NavigationItem(
                name="All Branches",
                url_name="stores:store_list",
                icon="bi bi-shop-window",
                permission="stores.view_store",
                requires_module='stores',
            ),
            NavigationItem(
                name="All Inventory",
                url_name="stores:inventory_list",
                icon="bi bi-box-seam",
                permission="stores.view_storeinventory",
                requires_module='stores',
            ),
            NavigationItem(
                name="Low Stock Alerts",
                url_name="stores:low_stock_alert",
                icon="bi bi-exclamation-circle",
                permission="stores.view_storeinventory",
                requires_module='stores',
            ),
            NavigationItem(
                name="Reports",
                url_name="stores:generate_report",
                icon="bi bi-file-earmark-text",
                permission="stores.view_storeinventory",
                requires_module='stores',
            ),
            NavigationItem(
                name="Device Sessions",
                url_name="stores:device_sessions_dashboard",
                icon="bi bi-activity",
                permission="stores.view_storesdevice",
                requires_module='stores',
            ),
            NavigationItem(
                name="Security Alerts",
                url_name="stores:security_alerts",
                icon="bi bi-exclamation-triangle",
                permission="stores.view_securityalert",
                requires_module='stores',
            ),
            NavigationItem(
                name="Sales Reports",
                url_name="stores:analytics",
                icon="bi bi-graph-up",
                permission='stores.add_store',
                requires_module='stores',
            ),
        ]
    ),
    NavigationItem(name="--", is_divider=True),
    NavigationItem(
        name="User Management",
        icon="bi bi-people",
        permission="accounts.add_customuser",
        children=[
            NavigationItem(
                name="All Users",
                url_name="user_list",
                icon="bi bi-people-fill",
                permission="accounts.view_customuser"
            ),
            NavigationItem(
                    name="Users Dashboard",
                    url_name="user_dashboard",
                    icon="bi bi-speedometer2",
                    permission="accounts.view_customuser"
                ),
            NavigationItem(
                name="Add User",
                url_name="invite_user",
                icon="bi bi-person-plus",
                permission="accounts.add_customuser"
            ),
            NavigationItem(
                name="Roles",
                url_name="role_list",
                icon="bi bi-person-badge",
                permission="accounts.view_role"
            ),
            NavigationItem(
                name="Add Role",
                url_name="role_create",
                icon="bi bi-shield-plus",
                permission="accounts.add_role"
            ),
            NavigationItem(
                name="Bulk Role Assignment",
                url_name="role_bulk_assignment",
                icon="bi bi-shield-lock",
                permission="accounts.add_role"
            ),
            NavigationItem(
                name="User Analytics",
                url_name="user_analytics",
                icon="bi bi-graph-up",
                permission="accounts.view_customuser"
            ),
        ]
    ),
    NavigationItem(name="--", is_divider=True),
    NavigationItem(
        name="Sessions & Security",
        icon="bi bi-shield-lock",
        children=[
            NavigationItem(
                name="My Sessions",
                url_name="stores:user_sessions",
                icon="bi bi-person-lines-fill"
            ),
            NavigationItem(
                name="Device Fingerprints",
                url_name="stores:device_fingerprints",
                icon="bi bi-fingerprint"
            ),
        ]
    ),

    NavigationItem(
        name="Profile",
        icon="bi bi-person-circle",
        children=[
            NavigationItem(
                name="My Profile",
                url_name="user_profile",
                icon="bi bi-person-circle"
            ),
            NavigationItem(
                name="Security Settings",
                url_name="user_security_settings",
                icon="bi bi-shield-lock"
            ),
            NavigationItem(
                name="Notifications",
                url_name="notifications:notification_list",
                icon="bi bi-bell"
            ),
            NavigationItem(
                name="Analytics",
                url_name="user_analytics",
                icon="bi bi-graph-up"
            ),
            NavigationItem(
                name="Change Password",
                url_name="change_password",
                icon="bi bi-key"
            ),
            NavigationItem(
                name="Privacy Settings",
                url_name="privacy_settings",
                icon="bi bi-shield"
            ),
            NavigationItem(
                name="Activity",
                url_name="user_activity_log",
                icon="bi bi-clock-history"
            ),
        ]
    ),

    NavigationItem(
        name="Settings",
        icon="bi bi-gear",
        visible_func=lambda user: user.is_staff or user.is_superuser,
        children=[
            NavigationItem(
                name="System Settings",
                url_name="saas_admin_system_settings",
                icon="bi bi-sliders"
            ),
            NavigationItem(
                name="Audit Log",
                url_name="saas_admin_audit_log",
                icon="bi bi-clipboard-data"
            ),
            NavigationItem(
                name="Company List",
                url_name="system_companies_list",
                icon="bi bi-building"
            ),
            NavigationItem(
                name="Security Center",
                url_name="user_security_settings",
                icon="bi bi-shield-lock"
            ),
        ]
    ),
    NavigationItem(name="--", is_divider=True),
    NavigationItem(
        name="Logout",
        url_name="custom_logout",
    ),
]


def get_navigation_for_user(user, request=None, **context_kwargs):
    """
    Returns navigation items visible to the given user.
    - Respects permission, EFRIS, and module guards (via is_visible)
    - Supports per-user hidden-item preferences (UserNavigationPreference)
    - Strips leading/trailing/consecutive dividers after filtering
    """

    # ── Load the user's hidden-item keys e.g. ["Sales", "Inventory.Low Stock Report"]
    hidden_keys: set = set()
    if user and user.is_authenticated:
        try:
            from .models import UserNavigationPreference
            pref = UserNavigationPreference.get_for_user(user)
            hidden_keys = set(pref.hidden_items)
        except Exception:
            pass  # Gracefully degrade if the table doesn't exist yet

    def _copy(item, filtered_children):
        """Return a shallow copy of item with replaced children list."""
        return NavigationItem(
            name=item.name,
            url_name=item.url_name,
            url=item.url,
            icon=item.icon,
            permission=item.permission,
            children=filtered_children,
            visible_func=item.visible_func,
            css_class=item.css_class,
            url_params=item.url_params,
            url_kwargs_func=item.url_kwargs_func,
            requires_efris=item.requires_efris,
            requires_module=item.requires_module,
            is_divider=item.is_divider,
            url_query_func=item.url_query_func,
            onclick=item.onclick,
        )

    def filter_items(items, parent_key=None):
        visible = []
        for item in items:
            if not item.is_visible(user, request):
                continue

            item_key = f"{parent_key}.{item.name}" if parent_key else item.name
            if item_key in hidden_keys:
                continue

            filtered_children = filter_items(item.children, parent_key=item_key)

            if item.url_name or item.url or item.onclick or filtered_children or item.is_divider:
                visible.append(_copy(item, filtered_children))

        return _clean_dividers(visible)

    def _clean_dividers(items):
        """
        Remove dividers orphaned after permission/preference filtering:
        - leading dividers  (nothing real before them)
        - trailing dividers (nothing real after them)
        - consecutive dividers (two or more in a row)
        """
        cleaned = []
        for item in items:
            if item.is_divider:
                if cleaned and not cleaned[-1].is_divider:
                    cleaned.append(item)
            else:
                cleaned.append(item)
        while cleaned and cleaned[-1].is_divider:
            cleaned.pop()
        return cleaned

    return filter_items(NAVIGATION_ITEMS)

def get_contextual_navigation(user, request, **context):
    """
    Get navigation items with context-specific parameters
    Use this when you have specific objects (like company, store, etc.)
    """
    nav_items = get_navigation_for_user(user, request, **context)

    # Add contextual navigation based on current page
    contextual_items = []


    # Add contextual items to appropriate section
    if contextual_items and nav_items:
        for section in nav_items:
            if section.name == "Companies":
                # Insert contextual items at the beginning of children
                section.children = contextual_items + section.children
                break

    return nav_items


# Context processor update
def navigation_context_processor(request):
    """
    Enhanced context processor with parameter support
    """
    nav_items = []
    if hasattr(request, 'user') and request.user.is_authenticated:
        # Get context from request (you might want to enhance this)
        context = getattr(request, 'nav_context', {})

        if context:
            nav_items = get_contextual_navigation(request.user, request, **context)
        else:
            nav_items = get_navigation_for_user(request.user, request)

    return {
        'navigation_items': nav_items,
    }


# Middleware to add navigation context (optional)
class NavigationContextMiddleware:
    """
    Middleware to automatically detect and add navigation context
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Add navigation context based on URL patterns
        request.nav_context = self.get_nav_context(request)

        response = self.get_response(request)
        return response

    def get_nav_context(self, request):
        """
        Extract navigation context from request
        """
        context = {}

        if hasattr(request, 'resolver_match') and request.resolver_match:
            # Add URL kwargs to context
            context.update(request.resolver_match.kwargs)

            # You can add more sophisticated context detection here
            # For example, fetch objects based on URL parameters

        return context


# Template tag enhancements
def render_navigation_with_context(context):
    """
    Enhanced template tag that handles URL parameters
    """
    user = context.get('user')
    request = context.get('request')

    # Extract navigation context from template context
    nav_context = {}

    # Common context objects that might be in templates
    for key in ['company', 'store', 'user_obj', 'product', 'invoice']:
        if key in context:
            nav_context[key] = context[key]

    if user and user.is_authenticated:
        if nav_context:
            nav_items = get_contextual_navigation(user, request, **nav_context)
        else:
            nav_items = get_navigation_for_user(user, request)
    else:
        nav_items = []

    return {
        'navigation_items': nav_items,
        'request': request,
        'nav_context': nav_context,
    }