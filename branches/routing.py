from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # Store analytics (primary)
    re_path(r'ws/store/(?P<store_id>\d+)/analytics/', consumers.StoreAnalyticsConsumer.as_asgi()),

    # Company-wide store analytics
    re_path(r'ws/company/(?P<company_id>\d+)/stores/', consumers.CompanyStoresConsumer.as_asgi()),

    # Backward compatibility routes (branch -> store)
    re_path(r'ws/branch/(?P<branch_id>\d+)/analytics/', consumers.StoreAnalyticsConsumer.as_asgi()),
]