from django.contrib import messages
from django.shortcuts import redirect


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

