from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)


class EfrisConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'efris'
    verbose_name = 'EFRIS Integration'
    module_key = 'efris'

    def ready(self):
        """Initialize EFRIS app"""
        try:
            # Import signal handlers
            from . import signals
            logger.info("EFRIS signal handlers loaded")

            # Initialize WebSocket manager
            from .websocket_manager import websocket_manager
            logger.info("EFRIS WebSocket manager initialized")

        except Exception as e:
            logger.error(f"Error initializing EFRIS app: {e}")

