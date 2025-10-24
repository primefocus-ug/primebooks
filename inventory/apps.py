from django.apps import AppConfig


class InventoryConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'inventory'
    verbose_name = 'Inventory Management'
    
    def ready(self):
        """Import signals when the app is ready"""
        try:
            # Import signals to ensure they are connected
            from . import signals
            
            # Import websocket_utils to initialize broadcaster
            from . import websocket_utils
            
        except ImportError as e:
            # Handle import errors gracefully
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Could not import inventory signals or websocket_utils: {e}")
        
        # Register any custom checks
        from django.core.checks import register
        from .checks import check_websocket_configuration
        
        register(check_websocket_configuration, deploy=True)