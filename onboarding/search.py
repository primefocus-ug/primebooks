"""
search/views.py
─────────────────────────────────────────────────────────────────────
Global command palette search API.

Endpoint:  GET /search/palette/?q=<query>
Returns:   { "results": [ { title, subtitle, url, icon, type } ] }

Searches across:
  • Invoices    (sales.Invoice)
  • Products    (inventory.Product)
  • Customers   (sales.Customer / accounts.Customer)
  • Users       (AUTH_USER_MODEL)
  • Reports     (reports.Report — the support ticket system)

Add to main urls.py:
    path('search/', include('search.urls')),

Add 'search' to INSTALLED_APPS (or place views.py directly in an
existing app and adjust the URL include accordingly).

Performance notes:
  • Each model query uses icontains on 1-2 fields only.
  • Results are capped at MAX_RESULTS_PER_MODEL (default 4).
  • The whole view is guarded by @login_required.
  • Queries only run when q >= MIN_QUERY_LENGTH chars (default 2).
"""

from django.http                    import JsonResponse
from django.contrib.auth.decorators import login_required
from django.db.models               import Q
from django.apps                    import apps
from django.urls                    import reverse, NoReverseMatch

MAX_RESULTS_PER_MODEL = 4
MIN_QUERY_LENGTH      = 2


@login_required
def palette_search(request):
    q = request.GET.get('q', '').strip()

    if len(q) < MIN_QUERY_LENGTH:
        return JsonResponse({'results': []})

    results = []

    # ── Invoices ────────────────────────────────────────────────
    try:
        Invoice = apps.get_model('sales', 'Invoice')
        invoices = Invoice.objects.filter(
            Q(invoice_number__icontains=q) |
            Q(customer__name__icontains=q)
        ).select_related('customer')[:MAX_RESULTS_PER_MODEL]

        for inv in invoices:
            customer_name = getattr(getattr(inv, 'customer', None), 'name', '')
            try:
                url = reverse('invoice_detail', kwargs={'pk': inv.pk})
            except NoReverseMatch:
                url = f'/invoices/{inv.pk}/'
            results.append({
                'title':    str(getattr(inv, 'invoice_number', inv.pk)),
                'subtitle': f'Invoice · {customer_name}' if customer_name else 'Invoice',
                'url':      url,
                'icon':     'bi-receipt',
                'type':     'invoice',
            })
    except LookupError:
        pass

    # ── Products ────────────────────────────────────────────────
    try:
        Product = apps.get_model('inventory', 'Product')
        products = Product.objects.filter(
            Q(name__icontains=q) |
            Q(sku__icontains=q)
        )[:MAX_RESULTS_PER_MODEL]

        for prod in products:
            sku = getattr(prod, 'sku', '')
            try:
                url = reverse('product_detail', kwargs={'pk': prod.pk})
            except NoReverseMatch:
                url = f'/products/{prod.pk}/'
            results.append({
                'title':    prod.name,
                'subtitle': f'Product · SKU: {sku}' if sku else 'Product',
                'url':      url,
                'icon':     'bi-box-seam',
                'type':     'product',
            })
    except LookupError:
        pass

    # ── Customers ───────────────────────────────────────────────
    try:
        # Try sales.Customer first, then accounts.Customer
        Customer = None
        for app_label in ('sales', 'accounts', 'customers'):
            try:
                Customer = apps.get_model(app_label, 'Customer')
                break
            except LookupError:
                continue

        if Customer:
            customers = Customer.objects.filter(
                Q(name__icontains=q) |
                Q(email__icontains=q)
            )[:MAX_RESULTS_PER_MODEL]

            for cust in customers:
                email = getattr(cust, 'email', '')
                try:
                    url = reverse('customer_detail', kwargs={'pk': cust.pk})
                except NoReverseMatch:
                    url = f'/customers/{cust.pk}/'
                results.append({
                    'title':    cust.name,
                    'subtitle': f'Customer · {email}' if email else 'Customer',
                    'url':      url,
                    'icon':     'bi-person-badge',
                    'type':     'customer',
                })
    except Exception:
        pass

    # ── Users ───────────────────────────────────────────────────
    if request.user.has_perm('accounts.view_customuser'):
        try:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            users = User.objects.filter(
                Q(username__icontains=q)  |
                Q(first_name__icontains=q)|
                Q(last_name__icontains=q) |
                Q(email__icontains=q)
            ).exclude(pk=request.user.pk)[:MAX_RESULTS_PER_MODEL]

            for user in users:
                full_name = user.get_full_name() or user.username
                try:
                    url = reverse('user_detail', kwargs={'user_id': user.pk})
                except NoReverseMatch:
                    try:
                        url = reverse('user_detail', kwargs={'pk': user.pk})
                    except NoReverseMatch:
                        url = f'/users/{user.pk}/'
                results.append({
                    'title':    full_name,
                    'subtitle': f'User · {user.email}' if user.email else 'User',
                    'url':      url,
                    'icon':     'bi-person-circle',
                    'type':     'user',
                })
        except Exception:
            pass

    # ── Support Reports (tickets) ────────────────────────────────
    try:
        Suggestion = apps.get_model('suggestions', 'Suggestion')
        ticket_reports = Suggestion.objects.filter(
            submitted_by=request.user,
        ).filter(
            Q(ticket_number__icontains=q) |
            Q(title__icontains=q)
        )[:MAX_RESULTS_PER_MODEL]

        for rep in ticket_reports:
            try:
                url = reverse('suggestions:report_detail', kwargs={'ticket_number': rep.ticket_number})
            except NoReverseMatch:
                url = f'/suggestions/{rep.ticket_number}/'
            results.append({
                'title':    rep.title,
                'subtitle': f'Ticket · {rep.ticket_number}',
                'url':      url,
                'icon':     'bi-ticket-detailed',
                'type':     'ticket',
            })
    except LookupError:
        pass

    return JsonResponse({'results': results})