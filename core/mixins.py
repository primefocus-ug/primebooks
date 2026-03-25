from django.contrib import messages
from django.shortcuts import redirect
from company.models import Company


class RequireModuleMixin:
    """
    Mixin for class-based views.
    Blocks access if the tenant has not activated the required module.

    Usage:
        class AppointmentListView(RequireModuleMixin, LoginRequiredMixin, ListView):
            required_module = 'salon'
            model = Appointment
            template_name = 'salon/appointments.html'

    Notice the pattern:
    - RequireModuleMixin comes FIRST in the class parents
    - This ensures dispatch() is checked before Django tries
      to load any data for the view
    """
    required_module = None  # Set this on every CBV that uses this mixin

    def dispatch(self, request, *args, **kwargs):
        if not self.required_module:
            raise ValueError(
                f"{self.__class__.__name__} must define required_module. "
                f"Example: required_module = 'salon'"
            )

        active = getattr(request, 'active_modules', set())

        if self.required_module not in active:
            messages.warning(
                request,
                f"'{self.required_module.replace('_', ' ').title()}' module is not enabled. "
                f"Enable it from your App Store."
            )
            return redirect('company:module_store')

        return super().dispatch(request, *args, **kwargs)


class CompanyRestrictedFormMixin:
    company_field_name = 'company'

    def get_form(self, form_class=None):
        form = super().get_form(form_class)

        user = self.request.user
        field_name = self.company_field_name

        if hasattr(user, 'company') and user.company:
            company = user.company

            field = form.fields[field_name]
            field.queryset = Company.objects.filter(pk=company.pk)
            field.initial = company

            # ✅ SHOW BUT DISABLE (NOT HIDE)
            field.disabled = True
            field.widget.attrs.pop('hidden', None)

        return form


class EFRISRequiredMixin:
    """
    Mixin to require EFRIS enabled for class-based views
    Usage:
        class MyView(EFRISRequiredMixin, TemplateView):
            ...
    """
    efris_required = True
    efris_active_required = False
    efris_redirect_url = 'dashboard'

    def dispatch(self, request, *args, **kwargs):
        if self.efris_required:
            if not hasattr(request, 'tenant') or not request.tenant.efris_enabled:
                messages.error(request, 'EFRIS integration must be enabled to access this feature.')
                return redirect(self.efris_redirect_url)

            if self.efris_active_required and not request.tenant.efris_is_active:
                messages.error(request, 'EFRIS integration must be active and configured.')
                return redirect(self.efris_redirect_url)

        return super().dispatch(request, *args, **kwargs)

