"""
stores/mixins.py
================
Central store-scoped access control.

HOW IT WORKS
------------
`get_user_accessible_stores(user)` already returns the correct set of stores
for any user (full company for admins/managers, specific assigned stores for
cashiers/stock managers, etc.).

Every piece of the system that needs to respect store access imports from here:

  • Views   → StoreQuerysetMixin  (filters list views & CBVs automatically)
  • Forms   → StoreRestrictedModelForm  (scopes every ModelChoiceField/
              ModelMultipleChoiceField whose queryset touches Store)
  • Admin   → StoreRestrictedAdmin  (scopes Django admin change lists & forms)
  • FBVs    → get_scoped_queryset()  helper for function-based views

USAGE
-----

### Class-based views (ListView, CreateView, UpdateView …)

    from stores.mixins import StoreQuerysetMixin

    class SaleListView(StoreQuerysetMixin, ListView):
        model = Sale
        # store_field = 'store'   ← default; change if FK has a different name

    class ProductCreateView(StoreQuerysetMixin, CreateView):
        model = Product
        form_class = ProductForm

    # The mixin:
    #   • Filters get_queryset() to only records the user can see
    #   • Passes the accessible stores to the form so dropdowns are scoped
    #   • Validates that the store chosen in a POST belongs to the user


### Forms

    from stores.mixins import StoreRestrictedModelForm

    class ProductForm(StoreRestrictedModelForm):
        class Meta:
            model = Product
            fields = ['name', 'store', 'price', ...]

    # Any ModelChoiceField / ModelMultipleChoiceField whose model is Store
    # (or whose queryset is a Store queryset) is automatically restricted to
    # the stores passed in via `accessible_stores`.


### Function-based views

    from stores.mixins import get_scoped_queryset, get_scoped_store_queryset

    def product_list(request):
        products = get_scoped_queryset(request.user, Product)
        stores   = get_scoped_store_queryset(request.user)
        ...

    def product_create(request):
        form = ProductForm(
            request.POST or None,
            accessible_stores=get_scoped_store_queryset(request.user)
        )
        ...


### Django Admin

    from stores.mixins import StoreRestrictedAdmin

    @admin.register(Product)
    class ProductAdmin(StoreRestrictedAdmin, admin.ModelAdmin):
        pass
"""

import logging
from django import forms
from django.core.exceptions import PermissionDenied

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_store_model():
    from stores.models import Store
    return Store


def get_scoped_store_queryset(user, include_inactive=False):
    """
    Return the Store queryset this user is allowed to see/choose from.
    Single source of truth — wraps get_user_accessible_stores.
    """
    from stores.utils import get_user_accessible_stores
    return get_user_accessible_stores(user, include_inactive=include_inactive)


def get_scoped_queryset(user, model, store_field='store', include_inactive=False):
    """
    Filter *any* model's queryset to records that belong to stores the user
    can access.

    Args:
        user:             The requesting user.
        model:            Django model class (e.g. Product, Sale, Stock …).
        store_field:      Name of the ForeignKey on `model` that points to
                          Store. Supports double-underscore traversal
                          (e.g. 'branch__store').
        include_inactive: Include inactive stores in the filter.

    Returns:
        A filtered queryset.  Returns model.objects.none() if the user has
        no accessible stores.

    Example:
        products = get_scoped_queryset(request.user, Product)
        sales    = get_scoped_queryset(request.user, Sale)
        items    = get_scoped_queryset(request.user, StockMovement,
                                       store_field='stock__store')
    """
    Store = _get_store_model()

    # SaaS admins get everything unfiltered
    if getattr(user, 'is_saas_admin', False):
        return model.objects.all()

    accessible_stores = get_scoped_store_queryset(user, include_inactive)
    store_ids = accessible_stores.values_list('id', flat=True)

    if not store_ids:
        return model.objects.none()

    filter_kwarg = {f'{store_field}__in': store_ids}
    return model.objects.filter(**filter_kwarg)


def _is_store_field(field):
    """
    Return True if a form field is a ModelChoiceField / ModelMultiple-
    ChoiceField whose queryset is a Store queryset.
    """
    Store = _get_store_model()
    if not isinstance(field, (forms.ModelChoiceField,
                               forms.ModelMultipleChoiceField)):
        return False
    try:
        return issubclass(field.queryset.model, Store)
    except AttributeError:
        return False


def _scope_form_store_fields(form, accessible_stores):
    """
    Iterate over every field in `form` and restrict any Store-related
    ModelChoiceField / ModelMultipleChoiceField to `accessible_stores`.
    """
    for field_name, field in form.fields.items():
        if _is_store_field(field):
            field.queryset = accessible_stores
            logger.debug(
                f"Scoped field '{field_name}' on {form.__class__.__name__} "
                f"to {accessible_stores.count()} stores"
            )


# ---------------------------------------------------------------------------
# Form mixins
# ---------------------------------------------------------------------------

class StoreRestrictedFormMixin:
    """
    Mixin that can be added to ANY form class — plain Form, ModelForm,
    or a search/filter form — to scope Store-related fields.

    It pops `accessible_stores` from kwargs before calling super().__init__,
    so it never interferes with the parent class's __init__ signature and
    does NOT require the form to have a Meta.model.

    Usage on a plain search/filter form:
        class CustomerSearchForm(StoreRestrictedFormMixin, forms.Form):
            store = forms.ModelChoiceField(queryset=Store.objects.all())
            q     = forms.CharField(required=False)

    Usage on a ModelForm:
        class ProductForm(StoreRestrictedFormMixin, forms.ModelForm):
            class Meta:
                model = Product
                fields = ['name', 'store', 'price']
    """

    def __init__(self, *args, accessible_stores=None, **kwargs):
        # Pop accessible_stores BEFORE calling super() so it never leaks
        # into Django's Form/ModelForm __init__ which doesn't know about it.
        super().__init__(*args, **kwargs)
        if accessible_stores is not None:
            _scope_form_store_fields(self, accessible_stores)


class StoreRestrictedModelForm(StoreRestrictedFormMixin, forms.ModelForm):
    """
    Drop-in replacement for forms.ModelForm.
    Backward-compatible alias — StoreRestrictedFormMixin is the real logic.

    Any ModelChoiceField / ModelMultipleChoiceField that points to the Store
    model is automatically scoped to the stores passed via `accessible_stores`.

    Usage:
        class ProductForm(StoreRestrictedModelForm):
            class Meta:
                model = Product
                fields = ['name', 'store', 'price']

        # In the view:
        form = ProductForm(
            request.POST or None,
            accessible_stores=get_scoped_store_queryset(request.user),
        )

        # Or let StoreQuerysetMixin inject it automatically.

    For non-model forms, use StoreRestrictedFormMixin directly instead:
        class CustomerSearchForm(StoreRestrictedFormMixin, forms.Form):
            ...
    """
    pass


# ---------------------------------------------------------------------------
# View mixin (CBV)
# ---------------------------------------------------------------------------

class StoreQuerysetMixin:
    """
    Mixin for any Django class-based view that operates on models with a
    store FK.

    What it does automatically:
      1. get_queryset()  — filters to records belonging to accessible stores
      2. get_form()      — scopes Store dropdowns in the form
      3. form_valid()    — validates that the submitted store is one the user
                           can access (guards against form tampering)

    Configuration:
        store_field = 'store'          # FK name on the model (default)
        store_form_field = 'store'     # Field name in the form (default same)
        bypass_store_filter = False    # Set True to opt out (e.g. company-wide views)
    """

    store_field = 'store'
    store_form_field = None          # Defaults to store_field
    bypass_store_filter = False

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _accessible_stores(self):
        """Cached per-request accessible stores queryset."""
        if not hasattr(self, '_accessible_stores_cache'):
            self._accessible_stores_cache = get_scoped_store_queryset(
                self.request.user
            )
        return self._accessible_stores_cache

    def _form_store_field(self):
        return self.store_form_field or self.store_field

    # ------------------------------------------------------------------ #
    # get_queryset                                                         #
    # ------------------------------------------------------------------ #

    def get_queryset(self):
        qs = super().get_queryset()

        if self.bypass_store_filter:
            return qs

        user = self.request.user

        # SaaS admins see everything
        if getattr(user, 'is_saas_admin', False):
            return qs

        accessible = self._accessible_stores()
        store_ids = accessible.values_list('id', flat=True)

        if not store_ids:
            return qs.none()

        filter_kwarg = {f'{self.store_field}__in': store_ids}
        return qs.filter(**filter_kwarg)

    # ------------------------------------------------------------------ #
    # Form scoping                                                         #
    # ------------------------------------------------------------------ #

    def get_form(self, form_class=None):
        form = super().get_form(form_class)

        if self.bypass_store_filter:
            return form

        user = self.request.user
        if getattr(user, 'is_saas_admin', False):
            return form

        # Only scope if the form did NOT already receive accessible_stores
        # via get_form_kwargs (i.e. it doesn't use StoreRestrictedFormMixin).
        # This avoids double-scoping.
        if not isinstance(form, StoreRestrictedFormMixin):
            _scope_form_store_fields(form, self._accessible_stores())

        return form

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()

        if self.bypass_store_filter:
            return kwargs

        user = self.request.user
        if getattr(user, 'is_saas_admin', False):
            return kwargs

        # Only inject accessible_stores if the form class supports it.
        # Forms that inherit from StoreRestrictedFormMixin accept this kwarg;
        # plain forms (search forms, filter forms) do not — passing it to them
        # would cause a TypeError inside Django's Form.__init__.
        form_class = self.get_form_class()
        if form_class is not None and issubclass(form_class, StoreRestrictedFormMixin):
            kwargs['accessible_stores'] = self._accessible_stores()

        return kwargs

    # ------------------------------------------------------------------ #
    # Validation on POST                                                   #
    # ------------------------------------------------------------------ #

    def form_valid(self, form):
        """
        Before saving, verify the chosen store is one the user can access.
        Prevents a malicious user from posting a store_id they don't own.
        """
        if not self.bypass_store_filter:
            user = self.request.user
            if not getattr(user, 'is_saas_admin', False):
                store_field_name = self._form_store_field()
                chosen_store = form.cleaned_data.get(store_field_name)
                if chosen_store is not None:
                    if not self._accessible_stores().filter(
                        pk=chosen_store.pk
                    ).exists():
                        raise PermissionDenied(
                            f"You do not have access to store: {chosen_store}"
                        )

        return super().form_valid(form)


# ---------------------------------------------------------------------------
# Django Admin mixin
# ---------------------------------------------------------------------------

class StoreRestrictedAdmin:
    """
    Mixin for Django ModelAdmin classes.

    Restricts:
      • change list  — only shows records from accessible stores
      • formfield    — scopes Store dropdowns in add/change forms
      • save_model   — validates store ownership before save

    Usage:
        from stores.mixins import StoreRestrictedAdmin

        @admin.register(Product)
        class ProductAdmin(StoreRestrictedAdmin, admin.ModelAdmin):
            store_field = 'store'   # optional, default is 'store'
    """

    store_field = 'store'

    def _accessible_stores(self, request):
        return get_scoped_store_queryset(request.user)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        user = request.user
        if getattr(user, 'is_saas_admin', False) or user.is_superuser:
            return qs
        accessible = self._accessible_stores(request)
        return qs.filter(**{f'{self.store_field}__in': accessible})

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        Store = _get_store_model()
        if db_field.related_model is Store:
            if not getattr(request.user, 'is_saas_admin', False):
                kwargs['queryset'] = self._accessible_stores(request)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        Store = _get_store_model()
        if db_field.related_model is Store:
            if not getattr(request.user, 'is_saas_admin', False):
                kwargs['queryset'] = self._accessible_stores(request)
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        Store = _get_store_model()
        user = request.user
        if not getattr(user, 'is_saas_admin', False) and not user.is_superuser:
            store_val = getattr(obj, self.store_field, None)
            if store_val and isinstance(store_val, Store):
                if not self._accessible_stores(request).filter(
                    pk=store_val.pk
                ).exists():
                    raise PermissionDenied(
                        f"You do not have access to store: {store_val}"
                    )
        super().save_model(request, obj, form, change)


# ---------------------------------------------------------------------------
# API / DRF serializer helper
# ---------------------------------------------------------------------------

class StoreRestrictedSerializerMixin:
    """
    Mixin for Django REST Framework serializers.

    Scopes any PrimaryKeyRelatedField / SlugRelatedField whose queryset is
    a Store queryset to the requesting user's accessible stores.

    The view must pass `request` in the serializer context (which DRF does
    automatically for generic views).

    Usage:
        from stores.mixins import StoreRestrictedSerializerMixin
        from rest_framework import serializers

        class ProductSerializer(StoreRestrictedSerializerMixin,
                                 serializers.ModelSerializer):
            class Meta:
                model = Product
                fields = ['id', 'name', 'store', 'price']
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request is None:
            return

        user = request.user
        if getattr(user, 'is_saas_admin', False):
            return

        try:
            from rest_framework import serializers as drf_serializers
            Store = _get_store_model()
            accessible = get_scoped_store_queryset(user)

            for field_name, field in self.fields.items():
                if isinstance(field, (
                    drf_serializers.PrimaryKeyRelatedField,
                    drf_serializers.SlugRelatedField,
                )):
                    qs = getattr(field, 'queryset', None)
                    if qs is not None:
                        try:
                            if issubclass(qs.model, Store):
                                field.queryset = accessible
                        except AttributeError:
                            pass
        except ImportError:
            pass  # DRF not installed — silently skip


# ---------------------------------------------------------------------------
# Template tag helper (used in templates to scope store dropdowns manually)
# ---------------------------------------------------------------------------

def get_store_choices_for_user(user, empty_label='— Select Store —'):
    """
    Returns a list of (id, name) tuples for all stores accessible to `user`.
    Useful in function-based views or template contexts where you need to
    build a select manually.

    Example in a view:
        context['store_choices'] = get_store_choices_for_user(request.user)

    Example in a template:
        <select name="store">
          {% for id, name in store_choices %}
            <option value="{{ id }}">{{ name }}</option>
          {% endfor %}
        </select>
    """
    choices = []
    if empty_label:
        choices.append(('', empty_label))
    qs = get_scoped_store_queryset(user).values_list('id', 'name')
    choices.extend(list(qs))
    return choices