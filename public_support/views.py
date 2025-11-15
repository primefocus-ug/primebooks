from django.views.generic import CreateView, ListView, DetailView, TemplateView
from django.contrib import messages
from django.shortcuts import redirect, get_object_or_404
from django.urls import reverse_lazy
from .models import SupportTicket, FAQ, ContactRequest
from .forms import SupportTicketForm, ContactRequestForm


class CreateSupportTicketView(CreateView):
    """Create support ticket"""
    model = SupportTicket
    form_class = SupportTicketForm
    template_name = 'public_support/create_ticket.html'
    success_url = reverse_lazy('public_support:ticket_success')

    def form_valid(self, form):
        ticket = form.save(commit=False)
        ticket.ip_address = self.get_client_ip()
        ticket.user_agent = self.request.META.get('HTTP_USER_AGENT', '')
        ticket.referrer = self.request.META.get('HTTP_REFERER', '')
        ticket.save()

        # Send notification email
        # send_ticket_notification.delay(ticket.ticket_id)

        # Store ticket number in session
        self.request.session['last_ticket_number'] = ticket.ticket_number

        messages.success(
            self.request,
            f'Your support ticket {ticket.ticket_number} has been created. '
            f'We\'ll get back to you shortly!'
        )

        return super().form_valid(form)

    def get_client_ip(self):
        x_forwarded_for = self.request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = self.request.META.get('REMOTE_ADDR')
        return ip


class TicketSuccessView(TemplateView):
    """Ticket creation success page"""
    template_name = 'public_support/ticket_success.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['ticket_number'] = self.request.session.get('last_ticket_number')
        return context


class FAQListView(ListView):
    """List all FAQs"""
    model = FAQ
    template_name = 'public_support/faq_list.html'
    context_object_name = 'faqs'

    def get_queryset(self):
        queryset = FAQ.objects.filter(is_active=True)
        category = self.request.GET.get('category')
        if category:
            queryset = queryset.filter(category=category)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['categories'] = FAQ.CATEGORY_CHOICES
        context['selected_category'] = self.request.GET.get('category')
        return context


class FAQDetailView(DetailView):
    """Individual FAQ"""
    model = FAQ
    template_name = 'public_support/faq_detail.html'
    context_object_name = 'faq'

    def get_object(self):
        faq = super().get_object()
        faq.increment_views()
        return faq


class ContactRequestView(CreateView):
    """Contact form"""
    model = ContactRequest
    form_class = ContactRequestForm
    template_name = 'public_support/contact.html'
    success_url = reverse_lazy('public_support:contact_success')

    def form_valid(self, form):
        contact = form.save(commit=False)
        contact.ip_address = self.get_client_ip()
        contact.save()

        # Send notification
        # send_contact_notification.delay(contact.id)

        messages.success(
            self.request,
            'Thank you for contacting us! We\'ll get back to you soon.'
        )

        return super().form_valid(form)

    def get_client_ip(self):
        x_forwarded_for = self.request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = self.request.META.get('REMOTE_ADDR')
        return ip