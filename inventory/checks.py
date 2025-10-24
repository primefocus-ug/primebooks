from django.core.checks import Error, Warning, Info
from django.conf import settings


def check_websocket_configuration(app_configs, **kwargs):
    """Check WebSocket configuration for inventory app"""
    errors = []
    
    # Check if Channels is installed
    try:
        import channels
    except ImportError:
        errors.append(
            Error(
                'Django Channels is not installed',
                hint='Install Django Channels: pip install channels',
                id='inventory.E001',
            )
        )
        return errors
    
    # Check if ASGI is configured
    if not hasattr(settings, 'ASGI_APPLICATION'):
        errors.append(
            Warning(
                'ASGI_APPLICATION not configured',
                hint='Add ASGI_APPLICATION setting to enable WebSocket support',
                id='inventory.W001',
            )
        )
    
    # Check if channel layers are configured
    if not hasattr(settings, 'CHANNEL_LAYERS'):
        errors.append(
            Warning(
                'CHANNEL_LAYERS not configured',
                hint='Configure CHANNEL_LAYERS for WebSocket broadcasting',
                id='inventory.W002',
            )
        )
    else:
        # Check channel layer backend
        default_layer = settings.CHANNEL_LAYERS.get('default', {})
        backend = default_layer.get('BACKEND', '')
        
        if 'InMemoryChannelLayer' in backend:
            errors.append(
                Info(
                    'Using InMemoryChannelLayer',
                    hint='Consider using Redis channel layer for production',
                    id='inventory.I001',
            )
        )
    
    # Check if Redis is available for production
    if hasattr(settings, 'CHANNEL_LAYERS'):
        default_layer = settings.CHANNEL_LAYERS.get('default', {})
        backend = default_layer.get('BACKEND', '')
        
        if 'RedisChannelLayer' in backend:
            try:
                import redis
                # Try to connect to Redis
                config = default_layer.get('CONFIG', {})
                hosts = config.get('hosts', [('127.0.0.1', 6379)])
                
                if hosts:
                    host, port = hosts[0] if isinstance(hosts[0], tuple) else (hosts[0], 6379)
                    try:
                        r = redis.Redis(host=host, port=port, socket_connect_timeout=1)
                        r.ping()
                    except redis.ConnectionError:
                        errors.append(
                            Warning(
                                'Cannot connect to Redis server',
                                hint=f'Ensure Redis is running on {host}:{port}',
                                id='inventory.W003',
                            )
                        )
            except ImportError:
                errors.append(
                    Error(
                        'Redis package not installed',
                        hint='Install redis package: pip install redis',
                        id='inventory.E002',
                    )
                )
    
    # Check if WebSocket URLs are included in routing
    try:
        from nash.routing import websocket_urlpatterns
        from inventory.routing import websocket_urlpatterns as inventory_patterns
        
        # Check if inventory patterns are included
        inventory_included = any(
            str(pattern).find('inventory') != -1 
            for pattern in websocket_urlpatterns
        )
        
        if not inventory_included:
            errors.append(
                Warning(
                    'Inventory WebSocket URLs not included in main routing',
                    hint='Include inventory.routing.websocket_urlpatterns in nash.routing',
                    id='inventory.W004',
                )
            )
    except ImportError:
        errors.append(
            Warning(
                'WebSocket routing not properly configured',
                hint='Ensure nash.routing.websocket_urlpatterns is properly configured',
                id='inventory.W005',
            )
        )
    
    # Check JavaScript dependencies
    static_files_configured = (
        hasattr(settings, 'STATIC_URL') and 
        hasattr(settings, 'STATICFILES_DIRS')
    )
    
    if not static_files_configured:
        errors.append(
            Warning(
                'Static files not properly configured',
                hint='Configure STATIC_URL and STATICFILES_DIRS for WebSocket JavaScript',
                id='inventory.W006',
            )
        )
    
    return errors


def check_inventory_models(app_configs, **kwargs):
    """Check inventory models for WebSocket compatibility"""
    errors = []
    
    # Check if required fields exist for WebSocket broadcasting
    from .models import Stock, StockMovement, ImportSession
    
    # Check Stock model
    try:
        Stock._meta.get_field('last_updated')
    except:
        errors.append(
            Warning(
                'Stock model missing last_updated field',
                hint='Add last_updated field for better WebSocket performance',
                id='inventory.W007',
            )
        )
    
    # Check StockMovement model
    try:
        StockMovement._meta.get_field('created_at')
        StockMovement._meta.get_field('created_by')
    except:
        errors.append(
            Error(
                'StockMovement model missing required fields',
                hint='Ensure created_at and created_by fields exist',
                id='inventory.E003',
            )
        )
    
    # Check ImportSession model
    try:
        ImportSession._meta.get_field('status')
        ImportSession._meta.get_field('user')
    except:
        errors.append(
            Error(
                'ImportSession model missing required fields',
                hint='Ensure status and user fields exist',
                id='inventory.E004',
            )
        )
    
    return errors