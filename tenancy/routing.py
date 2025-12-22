from inventory.routing import websocket_urlpatterns as inventory_patterns
from company.routing import websocket_urlpatterns as company_patterns
from stores.routing import websocket_urlpatterns as stores_patterns
from sales.routing import websocket_urlpatterns as sales_patterns
from reports.routing import websocket_urlpatterns as reports_patterns
from messaging.routing import websocket_urlpatterns as messaging_patterns
from branches.routing import websocket_urlpatterns as branches_patterns
from notifications.routing import websocket_urlpatterns as notifications_patterns
from expenses.routing import websocket_urlpatterns as expenses_patterns

# Combine all app websocket patterns
websocket_urlpatterns = [
    *inventory_patterns,
    *branches_patterns,
    *company_patterns,
    *stores_patterns,
    *sales_patterns,
    *reports_patterns,
    *messaging_patterns,
    *notifications_patterns,
    *expenses_patterns,
]
