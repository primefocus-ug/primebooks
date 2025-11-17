from django.urls import path
from public_accounts.admin_site import public_admin

app_name = 'public_admin'

urlpatterns = public_admin.urls[0]