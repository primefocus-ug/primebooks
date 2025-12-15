from django.contrib import messages
from django.shortcuts import redirect
from company.models import Company


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

