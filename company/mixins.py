from django.core.exceptions import PermissionDenied
from django.contrib import messages
from django.utils.translation import gettext_lazy as _


class EFRISRequiredMixin:
    """Require EFRIS to be enabled for this view"""

    def dispatch(self, request, *args, **kwargs):
        if not getattr(request, 'efris', {}).get('enabled', False):
            raise PermissionDenied("EFRIS is not enabled for your company")
        return super().dispatch(request, *args, **kwargs)


class EFRISConditionalMixin:
    """Add EFRIS context to views"""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        efris_status = getattr(self.request, 'efris', {})
        context['efris_enabled'] = efris_status.get('enabled', False)
        context['efris_is_active'] = efris_status.get('is_active', False)
        context['efris_company'] = efris_status.get('company')
        return context


class CompanyFieldLockMixin:
    """
    Mixin to automatically lock company field to current user's company.

    - Preselects user's company
    - Disables the field (frontend lock)
    - Validates on backend to prevent manipulation
    - Works with both CreateView and UpdateView

    Usage:
        class MyCreateView(CompanyFieldLockMixin, LoginRequiredMixin, CreateView):
            model = MyModel
            fields = ['company', 'name', ...]
    """

    company_field_name = 'company'  # Override if your field has a different name

    def get_form(self, form_class=None):
        form = super().get_form(form_class)

        # Check if form has company field
        if self.company_field_name not in form.fields:
            return form

        current_user = self.request.user

        if hasattr(current_user, 'company') and current_user.company:
            company = current_user.company

            # Lock field to user's company only
            form.fields[self.company_field_name].queryset = type(company).objects.filter(
                company_id=company.company_id
            )
            form.fields[self.company_field_name].initial = company
            form.fields[self.company_field_name].disabled = True
        else:
            # User has no company - show empty queryset
            form.fields[self.company_field_name].queryset = type(
                form.fields[self.company_field_name].queryset.model
            ).objects.none()

        return form

    def form_valid(self, form):
        """
        Backend security validation - prevents form manipulation.
        Even if user tampers with disabled field via browser tools,
        this ensures the company matches their assigned company.
        """
        current_user = self.request.user

        # Check if user has a company assigned
        if not hasattr(current_user, 'company') or not current_user.company:
            messages.error(
                self.request,
                _('You must be assigned to a company to perform this action.')
            )
            raise PermissionDenied(_('No company assigned to user.'))

        # Get the company from form (could be manipulated)
        submitted_company = form.cleaned_data.get(self.company_field_name)
        user_company = current_user.company

        # Security check: ensure submitted company matches user's company
        if submitted_company and submitted_company.company_id != user_company.company_id:
            messages.error(
                self.request,
                _('You can only create/update records for your assigned company.')
            )
            raise PermissionDenied(_('Company mismatch detected.'))

        # Force set the company to user's company (extra security layer)
        form.instance.company = user_company

        return super().form_valid(form)