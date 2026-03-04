from django_tenants.utils import schema_context
from django.core.mail import send_mail

schema = 'rem'  # e.g. 'acme_ltd'

with schema_context(schema):
    from sales.models import Sale
    from django.db.models import Sum
    from django.utils import timezone
    from datetime import timedelta

    rev = Sale.objects.filter(is_voided=False,status__in=['COMPLETED', 'PAID'],created_at__date__gte=timezone.now().date() - timedelta(days=30),).aggregate(t=Sum('total_amount'))['t'] or 0

    print(f'Revenue in {schema}: {float(rev):,.0f}')

# Now send — outside context is fine since no more DB calls
send_mail(subject=f'Revenue test — {schema}',message=f'30d revenue: {float(rev):,.0f}',from_email='noreply@yourapp.com',recipient_list=['nashvybzes2@gmail.com'],fail_silently=False,)
print('Email sent (or printed to console if using console backend)')