from django.core.exceptions import PermissionDenied


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