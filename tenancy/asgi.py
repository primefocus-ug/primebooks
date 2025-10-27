import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from channels.security.websocket import AllowedHostsOriginValidator
from pathlib import Path
from dotenv import load_dotenv
env_path = Path(__file__).resolve().parent.parent / '.env'
load_dotenv(dotenv_path=env_path)
# Relative import of project-level websocket_urlpatterns
from . import routing

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tenancy.settings')

# HTTP + WebSocket ASGI application
application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": AllowedHostsOriginValidator(
        AuthMiddlewareStack(
            URLRouter(routing.websocket_urlpatterns)
        )
    ),
})






# import os
# import django
# from django.core.asgi import get_asgi_application
# from channels.routing import ProtocolTypeRouter, URLRouter
# from channels.auth import AuthMiddlewareStack
# from channels.security.websocket import AllowedHostsOriginValidator
#
# os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tenancy.settings')
#
# django.setup()
#
# from .routing import websocket_urlpatterns
#
#
# # -------------------------------
# # Base ASGI application (for dev)
# # -------------------------------
# application = ProtocolTypeRouter({
#     "http": get_asgi_application(),
#     "websocket": AllowedHostsOriginValidator(
#         AuthMiddlewareStack(
#             URLRouter(websocket_urlpatterns)
#         )
#     ),
# })
#
#
# # -------------------------------
# # Debug wrapper (enabled if DEBUG=True)
# # -------------------------------
# class DebugASGIApplication:
#     """
#     ASGI application wrapper that adds debugging capabilities
#     """
#
#     def __init__(self, application):
#         self.application = application
#
#     async def __call__(self, scope, receive, send):
#         # Log WebSocket connections in development
#         if scope["type"] == "websocket" and os.environ.get("DEBUG", "False").lower() == "true":
#             print(f"WebSocket connection: {scope['path']} from {scope.get('client', ['unknown'])[0]}")
#
#         return await self.application(scope, receive, send)
#
#
# if os.environ.get("DEBUG", "False").lower() == "true":
#     application = DebugASGIApplication(application)
#
#
# # -------------------------------
# # Production wrapper (DISABLED in dev)
# # -------------------------------
# # class ProductionASGIApplication:
# #     """
# #     Production ASGI application with additional security and monitoring
# #     """
# #     def __init__(self, application):
# #         self.application = application
# #         self.active_connections = {}
# #
# #     async def __call__(self, scope, receive, send):
# #         # Add connection tracking for monitoring
# #         if scope["type"] == "websocket":
# #             client_ip = self.get_client_ip(scope)
# #             path = scope.get("path", "")
# #
# #             # Track connection
# #             connection_id = f"{client_ip}:{path}"
# #             self.active_connections[connection_id] = {
# #                 'connected_at': self.get_current_time(),
# #                 'path': path,
# #                 'client_ip': client_ip
# #             }
# #
# #             # Wrapper to track disconnections
# #             original_receive = receive
# #
# #             async def tracking_receive():
# #                 message = await original_receive()
# #                 if message.get("type") == "websocket.disconnect":
# #                     self.active_connections.pop(connection_id, None)
# #                 return message
# #
# #             return await self.application(scope, tracking_receive, send)
# #
# #         return await self.application(scope, receive, send)
# #
# #     def get_client_ip(self, scope):
# #         ...
# #
# #     def get_current_time(self):
# #         ...
# #
# #     def get_active_connections(self):
# #         return self.active_connections.copy()
# #
# # if os.environ.get("DEBUG", "False").lower() == "false":
# #     application = ProductionASGIApplication(application)
#
#
# # -------------------------------
# # Custom WebSocket Auth Middleware (DISABLED in dev)
# # -------------------------------
# # class WebSocketAuthMiddleware:
# #     ...
# #
# # def create_websocket_application():
# #     """Create WebSocket application with custom authentication"""
# #     return AllowedHostsOriginValidator(
# #         WebSocketAuthMiddleware(
# #             AuthMiddlewareStack(
# #                 URLRouter(websocket_urlpatterns)
# #             )
# #         )
# #     )
# #
# # # Optional: Use enhanced WebSocket application
# # # application = ProtocolTypeRouter({
# # #     "http": get_asgi_application(),
# # #     "websocket": create_websocket_application(),
# # # })
#
#
# # -------------------------------
# # Health check ASGI (DISABLED in dev)
# # -------------------------------
# # class HealthCheckASGI:
# #     ...
# #
# # # Uncomment to add health check
# # # application = HealthCheckASGI()
#
#
# # -------------------------------
# # Config validation (keep in dev)
# # -------------------------------
# def validate_asgi_config():
#     """Validate ASGI configuration"""
#     required_settings = [
#         'CHANNEL_LAYERS',
#         'ASGI_APPLICATION'
#     ]
#
#     from django.conf import settings
#
#     missing = []
#     for setting in required_settings:
#         if not hasattr(settings, setting):
#             missing.append(setting)
#
#     if missing:
#         raise RuntimeError(f"Missing required settings for WebSocket support: {missing}")
#
#     # Check Redis connection
#     try:
#         from channels.layers import get_channel_layer
#         channel_layer = get_channel_layer()
#         if not channel_layer:
#             raise RuntimeError("Channel layer not configured properly")
#     except Exception as e:
#         raise RuntimeError(f"Channel layer configuration error: {e}")
#
#
# if os.environ.get("DEBUG", "False").lower() == "true":
#     try:
#         validate_asgi_config()
#         print("ASGI WebSocket configuration validated successfully")
#     except Exception as e:
#         print(f"ASGI configuration warning: {e}")
#
# # Export
# __all__ = ['application', 'validate_asgi_config']
