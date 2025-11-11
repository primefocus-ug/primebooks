from django.views.generic import TemplateView
from django.conf import settings
from datetime import date


class LegalMixin:
    """Mixin to provide comprehensive legal context"""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'company_name': getattr(settings, 'COMPANY_NAME', 'Your Company Name'),
            'company_legal_name': getattr(settings, 'COMPANY_LEGAL_NAME', 'Your Company Legal Name, Inc.'),
            'contact_email': getattr(settings, 'LEGAL_CONTACT_EMAIL', 'legal@yourcompany.com'),
            'support_email': getattr(settings, 'SUPPORT_EMAIL', 'support@yourcompany.com'),
            'company_address': getattr(settings, 'COMPANY_ADDRESS',
                                       '123 Business St, Suite 100, City, State 12345, Country'),
            'effective_date': getattr(settings, 'LEGAL_EFFECTIVE_DATE', 'January 1, 2024'),
            'current_year': date.today().year,
            'dpo_email': getattr(settings, 'DPO_EMAIL', 'privacy@yourcompany.com'),
            'company_website': getattr(settings, 'COMPANY_WEBSITE', 'https://yourcompany.com'),
        })
        return context


class TermsOfServiceView(LegalMixin, TemplateView):
    """
    Comprehensive Terms of Service page
    Displays the legal terms governing the use of the service
    """
    template_name = 'legal/terms_of_service.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Terms of Service'
        context['page_description'] = 'Terms and conditions governing the use of our services'
        return context


class PrivacyPolicyView(LegalMixin, TemplateView):
    """
    Comprehensive Privacy Policy page
    Displays information about data collection, usage, and protection
    """
    template_name = 'legal/privacy_policy.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Privacy Policy'
        context['page_description'] = 'How we collect, use, and protect your personal information'
        return context


class AcceptableUseView(LegalMixin, TemplateView):
    """
    Acceptable Use Policy page
    Details prohibited activities and usage guidelines
    """
    template_name = 'legal/acceptable_use.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Acceptable Use Policy'
        context['page_description'] = 'Guidelines for acceptable use of our services'
        return context


class CookiePolicyView(LegalMixin, TemplateView):
    """
    Cookie Policy page
    Explains cookie usage and management
    """
    template_name = 'legal/cookie_policy.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Cookie Policy'
        context['page_description'] = 'How we use cookies and similar technologies'
        return context