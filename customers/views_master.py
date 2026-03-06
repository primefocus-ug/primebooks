"""
customers/views_master.py
─────────────────────────────────────────────────────────────────────────────
Drop-in replacement for every page-rendering view in customers/views.py.

Strategy
--------
* Import every existing class-based view directly from views.py.
* Subclass each one, override ONLY:
    template_name = 'customers/customers_master.html'
    active_tab    = '<value>'
  and inject  active_tab  into the context.
* All business logic (get_queryset, get_context_data, form_valid …)
  lives in the parent class — nothing is duplicated.
* Function-based views (import, notes, bulk actions, AJAX) are
  re-exported unchanged so urls.py needs only one import change.

Usage in urls.py
----------------
  # Old:
  from .views import CustomerListView, CustomerDetailView, ...
  # New:
  from .views_master import (
      CustomerListView, CustomerDetailView, CustomerCreateView,
      CustomerUpdateView, CustomerDeleteView,
      CustomerGroupListView, CustomerGroupCreateView,
      CustomerGroupUpdateView, CustomerGroupDeleteView,
      CustomerDashboardView, EFRISCustomerDashboardView,
      CustomerCreditReportView,
      # FBVs — pass-throughs, no change needed:
      customer_import, add_customer_note, bulk_customer_action,
      sync_customer_to_efris, retry_failed_efris_sync,
      adjust_customer_credit, bulk_update_credit_limits,
      store_customer_credit_info, customer_search_with_store,
      get_store_customers, customer_autocomplete,
      customer_stats_api, validate_customer_field,
      efris_sync_status_api,
  )
"""

# ── master template ───────────────────────────────────────────────────────────
MASTER = "customers/customers_master.html"

# ── import every existing view (keep all logic) ───────────────────────────────
from .views import (
    # class-based
    CustomerListView          as _CustomerListView,
    CustomerDetailView        as _CustomerDetailView,
    CustomerCreateView        as _CustomerCreateView,
    CustomerUpdateView        as _CustomerUpdateView,
    CustomerDeleteView        as _CustomerDeleteView,
    CustomerDashboardView     as _CustomerDashboardView,
    EFRISCustomerDashboardView as _EFRISCustomerDashboardView,
    CustomerCreditReportView  as _CustomerCreditReportView,
    CustomerGroupListView     as _CustomerGroupListView,
    CustomerGroupCreateView   as _CustomerGroupCreateView,
    CustomerGroupUpdateView   as _CustomerGroupUpdateView,
    CustomerGroupDeleteView   as _CustomerGroupDeleteView,

    # function-based — re-export as-is (no template involved)
    customer_import,
    add_customer_note,
    bulk_customer_action,
    sync_customer_to_efris,
    retry_failed_efris_sync,
    adjust_customer_credit,
    bulk_update_credit_limits,
    store_customer_credit_info,
    customer_search_with_store,
    get_store_customers,
    customer_autocomplete,
    customer_stats_api,
    validate_customer_field,
    efris_sync_status_api,
    export_credit_report,
    export_customers,
)


# ── tiny mixin: all the magic is here ────────────────────────────────────────
class _MasterMixin:
    """
    Override template_name → master template.
    Inject active_tab into every context automatically.
    All child classes set  active_tab = '<string>'  as a class attribute.
    """
    template_name = MASTER
    active_tab: str = "list"

    # Django's get_template_names() is used by TemplateResponseMixin
    def get_template_names(self):
        return [MASTER]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["active_tab"] = self.active_tab
        return ctx


# ─────────────────────────────────────────────────────────────────────────────
# PAGE VIEWS  (one subclass per page, zero logic duplication)
# ─────────────────────────────────────────────────────────────────────────────

class CustomerDashboardView(_MasterMixin, _CustomerDashboardView):
    active_tab = "dashboard"


class CustomerListView(_MasterMixin, _CustomerListView):
    active_tab = "list"


class CustomerDetailView(_MasterMixin, _CustomerDetailView):
    active_tab = "detail"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # DeleteView / DetailView stores the object as 'customer' already,
        # but the master template also needs it under that exact key — confirmed.
        return ctx


class CustomerCreateView(_MasterMixin, _CustomerCreateView):
    active_tab = "create"


class CustomerUpdateView(_MasterMixin, _CustomerUpdateView):
    active_tab = "edit"


class CustomerDeleteView(_MasterMixin, _CustomerDeleteView):
    active_tab = "delete"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Parent uses 'object'; template expects 'customer'
        ctx.setdefault("customer", self.get_object())
        return ctx


class EFRISCustomerDashboardView(_MasterMixin, _EFRISCustomerDashboardView):
    active_tab = "efris_dash"


class CustomerCreditReportView(_MasterMixin, _CustomerCreditReportView):
    active_tab = "credit"


class CustomerGroupListView(_MasterMixin, _CustomerGroupListView):
    active_tab = "groups"


class CustomerGroupCreateView(_MasterMixin, _CustomerGroupCreateView):
    active_tab = "group_form"


class CustomerGroupUpdateView(_MasterMixin, _CustomerGroupUpdateView):
    active_tab = "group_form"


class CustomerGroupDeleteView(_MasterMixin, _CustomerGroupDeleteView):
    active_tab = "group_delete"