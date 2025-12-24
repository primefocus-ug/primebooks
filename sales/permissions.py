from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from sales.models import SaleItem

# Create custom permission
content_type = ContentType.objects.get_for_model(SaleItem)
permission = Permission.objects.get_or_create(
    codename='can_override_price',
    name='Can override product/service price during sale',
    content_type=content_type,
)