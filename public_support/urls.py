from django.urls import path
from django.views.generic import TemplateView
from .views import (
    CreateSupportTicketView, TicketSuccessView,
    FAQListView, FAQDetailView, ContactRequestView
)

app_name = 'public_support'

urlpatterns = [
    # Support tickets
    path('tickets/new/', CreateSupportTicketView.as_view(), name='create_ticket'),
    path('tickets/success/', TicketSuccessView.as_view(), name='ticket_success'),

    # FAQs
    path('faq/', FAQListView.as_view(), name='faq_list'),
    path('faq/<slug:slug>/', FAQDetailView.as_view(), name='faq_detail'),

    # Contact
    path('contact/', ContactRequestView.as_view(), name='contact'),
    path('contact/success/', TemplateView.as_view(
        template_name='public_support/contact_success.html'
    ), name='contact_success'),
]