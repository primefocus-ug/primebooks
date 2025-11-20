class NavigationItem:
    def __init__(self, name, url_name=None, url=None, icon=None, permission=None,
                 children=None, visible_func=None, css_class="", url_params=None,
                 url_kwargs_func=None):
        self.name = name
        self.url_name = url_name
        self.url = url
        self.icon = icon
        self.permission = permission
        self.children = children or []
        self.visible_func = visible_func
        self.css_class = css_class
        self.url_params = url_params or []  # List of parameter names
        self.url_kwargs_func = url_kwargs_func  # Function to generate kwargs

    def is_visible(self, user):
        if self.visible_func:
            return self.visible_func(user)

        if not user.is_authenticated:
            return False

        if self.permission:
            if isinstance(self.permission, str):
                return user.has_perm(self.permission)
            elif isinstance(self.permission, list):
                return any(user.has_perm(perm) for perm in self.permission)

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

                # Try simple reverse without parameters
                return reverse(self.url_name)
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


# Enhanced navigation items with parameter support
NAVIGATION_ITEMS = [
    NavigationItem(
        name="Users Dashboard",
        url_name="user_dashboard",
        icon="bi bi-speedometer2"
    ),
    NavigationItem(
        name="Profile & Settings",
        icon="bi bi-speedometer2",
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
                url_name="user_notification_settings",
                icon="bi bi-bell"
            ),
            NavigationItem(
                name="Preferences",
                url_name="user_preferences",
                icon="bi bi-sliders"
            ),
            NavigationItem(
                name="Analytics",
                url_name="user_analytics",
                icon="bi bi-graph-up"
            ),
        ]
    ),
    NavigationItem(
        name="User Management",
        icon="bi bi-people",
        permission="accounts.view_customuser",
        children=[
            NavigationItem(
                name="All Users",
                url_name="user_list",
                icon="bi bi-people-fill",
                permission="accounts.view_customuser"
            ),
            NavigationItem(
                name="Add User",
                url_name="user_create",
                icon="bi bi-person-plus",
                permission="accounts.add_customuser"
            ),
            NavigationItem(
                name="Roles",
                url_name="role_list",
                icon="bi bi-person-badge",
                permission="auth.view_group"
            ),
            NavigationItem(
                name="Add Role",
                url_name="role_create",
                icon="bi bi-shield-plus",
                permission="auth.add_group"
            ),
            NavigationItem(
                name="Bulk Role Assignment",
                url_name="role_bulk_assignment",
                icon="bi bi-shield-lock",
                permission="accounts.assign_role_users"
            ),
            NavigationItem(
                name="User Analytics",
                url_name="user_analytics",
                icon="bi bi-graph-up",
                permission="accounts.view_customuser"
            ),
        ]
    ),
    NavigationItem(
        name="Companies",
        icon="bi bi-building",
        children=[
            NavigationItem(
                name="Dashboard",
                url_name="companies:dashboard",
                icon="bi bi-speedometer2",
                permission="companies.view_company",
            ),
            NavigationItem(
                name="Subscription Plans",
                url_name="companies:subscription_plans",
                icon="bi bi-diagram-3",
                permission="companies.view_subscription"
            ),
            NavigationItem(
            name="Billing History",
            url_name="companies:billing_history",
            icon="bi bi-receipt",
            permission="companies.view_billing"
            ),
            NavigationItem(
                name="Branches",
                url_name="companies:branch_list",
                icon="bi bi-diagram-3",
                permission="branches.view_branch"
            ),
            NavigationItem(
                name="Employees",
                icon="bi bi-people-fill",
                permission="companies.view_employee",
                children=[
                    NavigationItem(
                        name="All Employees",
                        url_name="user_list",
                        icon="bi bi-list-ul",
                        permission="companies.view_employee"
                    ),
                    NavigationItem(
                        name="Export Employees",
                        url_name="companies:employee_export",
                        icon="bi bi-download",
                        permission="companies.view_employee"
                    ),
                ]
            ),
            NavigationItem(
                name="Domains",
                url_name="companies:domain_list",
                icon="bi bi-globe",
                permission="companies.view_domain"
            ),
        ]
    ),

    NavigationItem(
        name="Stores Dashboard",
        url_name="stores:store_dashboard",
        icon="bi bi-speedometer2",
    ),

    NavigationItem(
        name="Stores Management",
        icon="bi bi-shop",
        children=[
            NavigationItem(
                name="All Stores",
                url_name="stores:store_list",
                icon="bi bi-shop-window",
                permission="stores.view_store"
            ),
            NavigationItem(
            name="All Inventory",
            url_name="stores:inventory_list",
            icon="bi bi-box-seam",
            permission="stores.view_storeinventory"
            ),
            NavigationItem(
                name="Low Stock Alerts",
                url_name="stores:low_stock_alert",
                icon="bi bi-exclamation-circle",
                permission="stores.view_storeinventory"
            ),
            NavigationItem(
                name="Reports",
                url_name="stores:generate_report",
                icon="bi bi-file-earmark-text",
                permission="stores.view_storeinventory"
            ),
            NavigationItem(
                name="Device Sessions",
                url_name="stores:device_sessions_dashboard",
                icon="bi bi-activity",
                permission="stores.view_storesdevice"
            ),
            NavigationItem(
                name="Security Alerts",
                url_name="stores:security_alerts",
                icon="bi bi-exclamation-triangle",
                permission="stores.view_securityalert"
            ),
            NavigationItem(
                name="Sales Reports",
                url_name="stores:analytics",
                icon="bi bi-graph-up"
            ),
        ]
    ),

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
        name="Inventory",
        icon="bi bi-boxes",
        permission="inventory.view_product",
        children=[
            NavigationItem(
                name="Inventory Dashboard",
                url_name="inventory:dashboard",
                icon="bi bi-speedometer2",
                permission="inventory.view_product"
            ),
            NavigationItem(
                name="Stock Dashboard",
                url_name="efris:stock_management_dashboard",
                icon="bi bi-speedometer2",
                permission="inventory.view_product"
            ),
            NavigationItem(
                name="All Products",
                url_name="inventory:product_list",
                icon="bi bi-basket",
            ),
            NavigationItem(
                name="Add Product",
                url_name="inventory:product_create",
                icon="bi bi-plus-circle",
            ),
        NavigationItem(
            name="Services",
            icon="bi bi-briefcase",
            children=[
                NavigationItem(
                    name="All Services",
                    url_name="inventory:service_list",
                    icon="bi bi-list-task",
                ),
                NavigationItem(
                    name="Add Service",
                    url_name="inventory:service_create",
                    icon="bi bi-plus-circle",
                ),
            ],
        ),
            NavigationItem(
                name="Bulk Import",
                url_name="inventory:stock_import",
                icon="bi bi-upload",
            ),
            NavigationItem(
                name="All Categories",
                url_name="inventory:category_list",
                icon="bi bi-list-ul",
            ),
            NavigationItem(
                name="Add Category",
                url_name="inventory:category_create",
                icon="bi bi-plus-circle",
            ),
            NavigationItem(
                name="Suppliers",
                icon="bi bi-truck",
                children=[
                    NavigationItem(
                        name="All Suppliers",
                        url_name="inventory:supplier_list",
                        icon="bi bi-person-lines-fill",
                    ),
                    NavigationItem(
                        name="Add Supplier",
                        url_name="inventory:supplier_create",
                        icon="bi bi-plus-circle",
                    ),
                ],
            ),
            NavigationItem(
                name="Stock Management",
                icon="bi bi-warehouse",
                permission="inventory.view_stock",
                children=[
                    NavigationItem(
                        name="Current Stock",
                        url_name="inventory:stock_list",
                        icon="bi bi-boxes",
                        permission="inventory.view_stock"
                    ),
                    NavigationItem(
                        name="Stock Adjustment",
                        url_name="inventory:movement_create",
                        icon="bi bi-sliders",
                        permission="inventory.change_stock"
                    ),
                    NavigationItem(
                        name="Stock Movements",
                        url_name="inventory:movement_list",
                        icon="bi bi-arrow-left-right",
                        permission="inventory.view_stockmovement"
                    ),
                ]
            ),
            NavigationItem(
                name="Reports",
                icon="bi bi-graph-up",
                permission="inventory.view_product",
                children=[
                    NavigationItem(
                        name="Low Stock Report",
                        url_name="stores:low_stock_alert",
                        icon="bi bi-exclamation-triangle",
                        css_class="text-warning"
                    ),
                    NavigationItem(
                        name="Inventory Valuation",
                        url_name="inventory:valuation_report",
                        icon="bi bi-calculator"
                    ),
                    NavigationItem(
                        name="Movement Analytics",
                        url_name="inventory:movement_analytics",
                        icon="bi bi-graph-up-arrow"
                    ),
                ]
            ),
        ]
    ),

    NavigationItem(
        name="Sales",
        icon="bi bi-cart-check",
        permission="sales.view_sale",
        children=[
            NavigationItem(
                name="All Sales",
                url_name="sales:sales_list",
                icon="bi bi-list-check",
                permission="sales.view_sale"
            ),
            NavigationItem(
                name="Create Sale",
                url_name="sales:create_sale",
                icon="bi bi-plus-circle",
                permission="sales.add_sale"
            ),
            NavigationItem(
                name="Sales Analytics",
                url_name="sales:analytics",
                icon="bi bi-graph-up",
                permission="sales.view_sale"
            ),
        ]
    ),
    NavigationItem(
        name="Finance & Expenses",
        icon="bi bi-cash-stack",
        children=[
            NavigationItem(
                name="Dashboard",
                url_name="expenses:dashboard",
                icon="bi bi-speedometer2",
            ),
            NavigationItem(
                name="Expense List",
                url_name="expenses:expense_list",
                icon="bi bi-coin",
            ),
            NavigationItem(
                name="Reports",
                url_name="expense:reports",
                icon="bi bi-file-earmark-bar-graph",
            ),
            NavigationItem(
                name="Category List",
                url_name="expenses:category_list",
                icon="bi bi-coin",
            ),

        ],),
    NavigationItem(
        name="Customers",
        icon="bi bi-people",
        permission="customers.view_customer",
        children=[
            NavigationItem(
                name="Customers Dashboard",
                url_name="customers:dashboard",
                icon="bi bi-graph-up",
                permission="customers.view_customer"
            ),
            NavigationItem(
                name="All Customers",
                url_name="customers:customer_list",
                icon="bi bi-people-fill",
                permission="customers.view_customer"
            ),
            NavigationItem(
                name="Customer Groups",
                url_name="customers:group_list",
                icon="bi bi-collection",
                permission="customers.view_customergroup"
            ),
            NavigationItem(
                name="Add Customer",
                url_name="customers:create",
                icon="bi bi-person-plus",
                permission="customers.add_customer"
            ),
            NavigationItem(
                name="Add Group",
                url_name="customers:group_create",
                icon="bi bi-people-fill",
                permission="customers.add_customergroup"
            ),
            NavigationItem(
                name="Import Customers",
                url_name="customers:customer_import",
                icon="bi bi-upload",
                permission="customers.add_customer"
            ),
        ]
    ),

    NavigationItem(
        name="Invoices",
        icon="bi bi-receipt",
        permission="invoices.view_invoice",
        children=[
            NavigationItem(
                name="Dashboard",
                url_name="invoices:dashboard",
                icon="bi bi-speedometer2",
                permission="invoices.view_invoice"
            ),
            NavigationItem(
                name="All Invoices",
                url_name="invoices:list",
                icon="bi bi-receipt-cutoff",
                permission="invoices.view_invoice"
            ),
            NavigationItem(
                name="Create Invoice",
                url_name="invoices:create",
                icon="bi bi-plus-circle",
                permission="invoices.add_invoice"
            ),
            NavigationItem(
                name="Invoice Analytics",
                url_name="invoices:analytics",
                icon="bi bi-graph-up",
                permission="invoices.view_invoice"
            ),
            NavigationItem(
                name="Payments",
                url_name="invoices:payments",
                icon="bi bi-credit-card",
                permission="invoices.view_payment"
            ),
            NavigationItem(
                name="Templates",
                url_name="invoices:templates",
                icon="bi bi-file-earmark-text",
                permission="invoices.view_invoicetemplate"
            ),
            NavigationItem(
                name="Fiscalization Audit",
                url_name="invoices:fiscalization_audit",
                icon="bi bi-shield-check",
                permission="invoices.view_invoice"
            ),
        ]
    ),

    NavigationItem(
        name="Reports",
        icon="bi bi-file-earmark-bar-graph",
        permission="reports.view_report",
        children=[
            NavigationItem(
                name="Dashboard",
                url_name="reports:dashboard",
                icon="bi bi-speedometer2",
                permission="reports.view_report"
            ),
            NavigationItem(
                name="Saved Reports",
                url_name="reports:saved_reports",
                icon="bi bi-bookmark",
                permission="reports.view_savedreport"
            ),
            NavigationItem(
                name="Create Report",
                url_name="reports:create_saved_report",
                icon="bi bi-plus-circle",
                permission="reports.add_savedreport"
            ),
            NavigationItem(
                name="Report Schedules",
                url_name="reports:schedules",
                icon="bi bi-calendar-check",
                permission="reports.view_reportschedule"
            ),
            NavigationItem(
                name="EFRIS Templates",
                url_name="reports:efris_templates_list",
                icon="bi bi-file-earmark-code",
                permission="reports.view_efristemplate"
            ),
            NavigationItem(
                name="Analytics",
                url_name="reports:analytics",
                icon="bi bi-graph-up",
                permission="reports.view_report"
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
                icon="bi bi-person"
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
]


def get_navigation_for_user(user, request=None, **context_kwargs):
    """
    Returns navigation items that are visible to the given user
    Enhanced to support URL parameters from context
    """

    def filter_items(items):
        visible_items = []
        for item in items:
            if item.is_visible(user):
                # Filter children recursively
                filtered_children = filter_items(item.children)

                # Create a copy of the item with filtered children
                filtered_item = NavigationItem(
                    name=item.name,
                    url_name=item.url_name,
                    url=item.url,
                    icon=item.icon,
                    permission=item.permission,
                    children=filtered_children,
                    visible_func=item.visible_func,
                    css_class=item.css_class,
                    url_params=item.url_params,
                    url_kwargs_func=item.url_kwargs_func
                )

                # Only include if has children or has its own URL
                if filtered_children or item.url_name or item.url:
                    visible_items.append(filtered_item)

        return visible_items

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
