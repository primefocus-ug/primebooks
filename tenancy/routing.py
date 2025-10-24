from inventory.routing import websocket_urlpatterns as inventory_patterns
from company.routing import websocket_urlpatterns as company_patterns
from stores.routing import websocket_urlpatterns as stores_patterns
from sales.routing import websocket_urlpatterns as sales_patterns
from reports.routing import websocket_urlpatterns as reports_patterns

# Combine all app websocket patterns
websocket_urlpatterns = [
    *inventory_patterns,
    *company_patterns,
    *stores_patterns,
    *sales_patterns,
    *reports_patterns,
]
