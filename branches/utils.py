from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import json
import logging

logger = logging.getLogger(__name__)


class WebSocketNotifier:
    """Utility class for sending WebSocket notifications."""

    def __init__(self):
        self.channel_layer = get_channel_layer()

    def send_store_update(self, store_id, data, update_type='store_update'):
        """Send update to store analytics group."""
        if not self.channel_layer:
            logger.warning('Channel layer not available')
            return False

        try:
            async_to_sync(self.channel_layer.group_send)(
                f'store_analytics_{store_id}',
                {
                    'type': update_type.replace('_', '.'),  # Convert to method name format
                    'data': data
                }
            )
            return True
        except Exception as e:
            logger.error(f'Store WebSocket notification failed for store {store_id}: {e}')
            return False

    def send_company_update(self, company_id, data, update_type='company_update'):
        """Send update to company-wide analytics group."""
        if not self.channel_layer:
            logger.warning('Channel layer not available')
            return False

        try:
            async_to_sync(self.channel_layer.group_send)(
                f'company_stores_{company_id}',
                {
                    'type': update_type.replace('_', '.'),
                    'data': data
                }
            )
            return True
        except Exception as e:
            logger.error(f'Company WebSocket notification failed for company {company_id}: {e}')
            return False

    def send_performance_alert(self, store_id, alert_data, severity='info'):
        """Send performance alert to store."""
        if not self.channel_layer:
            logger.warning('Channel layer not available')
            return False

        try:
            async_to_sync(self.channel_layer.group_send)(
                f'store_analytics_{store_id}',
                {
                    'type': 'performance.alert',
                    'data': alert_data,
                    'severity': severity
                }
            )
            return True
        except Exception as e:
            logger.error(f'Performance alert WebSocket failed for store {store_id}: {e}')
            return False

    def send_company_alert(self, company_id, alert_data, severity='info'):
        """Send alert to entire company."""
        if not self.channel_layer:
            logger.warning('Channel layer not available')
            return False

        try:
            async_to_sync(self.channel_layer.group_send)(
                f'company_stores_{company_id}',
                {
                    'type': 'company.alert',
                    'data': alert_data,
                    'severity': severity
                }
            )
            return True
        except Exception as e:
            logger.error(f'Company alert WebSocket failed for company {company_id}: {e}')
            return False

    def send_inventory_alert(self, store_id, inventory_data):
        """Send inventory update to store."""
        if not self.channel_layer:
            logger.warning('Channel layer not available')
            return False

        try:
            async_to_sync(self.channel_layer.group_send)(
                f'store_analytics_{store_id}',
                {
                    'type': 'inventory.update',
                    'data': inventory_data
                }
            )
            return True
        except Exception as e:
            logger.error(f'Inventory alert WebSocket failed for store {store_id}: {e}')
            return False

    # Backward compatibility methods (branch -> store)
    def send_branch_update(self, branch_id, data, update_type='branch_update'):
        """
        Backward compatibility: redirect to send_store_update.
        @deprecated: Use send_store_update instead.
        """
        logger.warning('send_branch_update is deprecated. Use send_store_update instead.')
        return self.send_store_update(branch_id, data, update_type)


# Singleton instance
websocket_notifier = WebSocketNotifier()




# ============================================================================
# FILE 8: admin.py - Updated Admin Actions for Stores
# ============================================================================
from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from stores.models import Store, StoreDevice, StoreOperatingHours
from .utils import websocket_notifier


@admin.action(description=_('Send analytics update to selected stores'))
def send_analytics_update(modeladmin, request, queryset):
    """Send real-time analytics update for selected stores."""
    from django.utils import timezone

    for store in queryset:
        try:
            update_data = {
                'store_id': store.id,
                'store_name': store.name,
                'is_active': store.is_active,
                'updated_at': timezone.now().isoformat()
            }

            websocket_notifier.send_store_update(
                store.id,
                update_data,
                'admin_update'
            )

        except Exception as e:
            modeladmin.message_user(
                request,
                f'Failed to send update for {store.name}: {str(e)}',
                level='error'
            )

    modeladmin.message_user(
        request,
        f'Analytics update sent to {queryset.count()} store(s)',
        level='success'
    )


@admin.action(description=_('Activate selected stores'))
def activate_stores(modeladmin, request, queryset):
    """Activate selected stores and notify via WebSocket."""
    updated = queryset.update(is_active=True)

    for store in queryset:
        websocket_notifier.send_store_update(
            store.id,
            {'store_id': store.id, 'is_active': True, 'action': 'activated'},
            'store_update'
        )

    modeladmin.message_user(
        request,
        f'{updated} store(s) activated successfully',
        level='success'
    )


@admin.action(description=_('Deactivate selected stores'))
def deactivate_stores(modeladmin, request, queryset):
    """Deactivate selected stores and notify via WebSocket."""
    updated = queryset.update(is_active=False)

    for store in queryset:
        websocket_notifier.send_store_update(
            store.id,
            {'store_id': store.id, 'is_active': False, 'action': 'deactivated'},
            'store_update'
        )

    modeladmin.message_user(
        request,
        f'{updated} store(s) deactivated successfully',
        level='success'
    )


class StoreAdmin(admin.ModelAdmin):
    """Enhanced Store admin with WebSocket support."""

    list_display = [
        'name', 'code', 'company', 'store_type', 'is_main_branch',
        'is_active', 'efris_enabled', 'location'
    ]
    list_filter = [
        'is_active', 'store_type', 'is_main_branch', 'efris_enabled',
        'company'
    ]
    search_fields = ['name', 'code', 'location', 'tin', 'phone', 'email']
    actions = [send_analytics_update, activate_stores, deactivate_stores]

    fieldsets = (
        (_('Basic Information'), {
            'fields': ('company', 'name', 'code', 'store_type', 'description')
        }),
        (_('Location'), {
            'fields': (
                'location', 'physical_address', 'region',
                'latitude', 'longitude', 'location_gps'
            )
        }),
        (_('Contact Information'), {
            'fields': ('phone', 'secondary_phone', 'email', 'logo')
        }),
        (_('Tax Information'), {
            'fields': ('tin', 'nin')
        }),
        (_('Management'), {
            'fields': ('manager_name', 'manager_phone', 'staff')
        }),
        (_('EFRIS Configuration'), {
            'fields': (
                'efris_enabled', 'efris_device_number', 'device_serial_number',
                'is_registered_with_efris', 'efris_registration_date',
                'auto_fiscalize_sales', 'allow_manual_fiscalization',
                'report_stock_movements'
            )
        }),
        (_('Settings'), {
            'fields': (
                'is_main_branch', 'is_active', 'allows_sales',
                'allows_inventory', 'timezone', 'operating_hours'
            )
        }),
        (_('Additional'), {
            'fields': ('sort_order', 'notes'),
            'classes': ('collapse',)
        }),
    )

    def save_model(self, request, obj, form, change):
        """Override to send WebSocket update on save."""
        super().save_model(request, obj, form, change)

        # Send WebSocket notification
        update_data = {
            'store_id': obj.id,
            'store_name': obj.name,
            'is_active': obj.is_active,
            'action': 'updated' if change else 'created'
        }

        websocket_notifier.send_store_update(
            obj.id,
            update_data,
            'admin_update'
        )


# Register the admin
admin.site.register(Store, StoreAdmin)

# ============================================================================
# MIGRATION HELPER: For transitioning from CompanyBranch to Store
# ============================================================================
"""
# Create a data migration file to help transition existing code

from django.db import migrations

def migrate_branch_references_to_store(apps, schema_editor):
    '''
    Data migration to help transition from CompanyBranch to Store.
    This is a template - adjust based on your specific needs.
    '''
    Store = apps.get_model('stores', 'Store')

    # Example: Update any model that had a foreign key to CompanyBranch
    # Sale = apps.get_model('sales', 'Sale')
    # for sale in Sale.objects.all():
    #     if hasattr(sale, 'branch'):
    #         sale.store = sale.branch
    #         sale.save(update_fields=['store'])

    print("Migration complete: CompanyBranch -> Store")

class Migration(migrations.Migration):
    dependencies = [
        ('stores', '0001_initial'),  # Adjust to your actual migration
    ]

    operations = [
        migrations.RunPython(
            migrate_branch_references_to_store,
            reverse_code=migrations.RunPython.noop
        ),
    ]
"""

# ============================================================================
# USAGE EXAMPLES
# ============================================================================
"""
# Example 1: Sending store update from a view
from .utils import websocket_notifier

def update_store_status(request, store_id):
    store = Store.objects.get(id=store_id)
    store.is_active = not store.is_active
    store.save()

    # Send real-time update
    websocket_notifier.send_store_update(
        store.id,
        {
            'store_id': store.id,
            'is_active': store.is_active,
            'updated_by': request.user.username
        },
        'status_change'
    )

    return JsonResponse({'success': True})


# Example 2: Connecting to WebSocket from JavaScript
const storeId = 123;
const ws = new WebSocket(`ws://localhost:8000/ws/store/${storeId}/analytics/`);

ws.onopen = function() {
    console.log('Connected to store analytics');

    // Request initial data
    ws.send(JSON.stringify({
        type: 'request_update'
    }));
};

ws.onmessage = function(event) {
    const data = JSON.parse(event.data);

    switch(data.type) {
        case 'initial_data':
            console.log('Initial data:', data.data);
            updateDashboard(data.data);
            break;

        case 'sale_created':
            console.log('New sale:', data.data);
            showNotification('New Sale!', data.data);
            break;

        case 'inventory_update':
            console.log('Inventory updated:', data.data);
            updateInventoryDisplay(data.data);
            break;

        case 'performance_alert':
            console.log('Alert:', data.data);
            showAlert(data.data, data.severity);
            break;
    }
};

ws.onerror = function(error) {
    console.error('WebSocket error:', error);
};

ws.onclose = function() {
    console.log('Disconnected from store analytics');
    // Implement reconnection logic here
};


# Example 3: Using in Django templates
{% load static %}

<div id="store-dashboard" data-store-id="{{ store.id }}">
    <h2>{{ store.name }} Analytics</h2>

    <div class="metrics">
        <div class="metric" id="today-sales">
            <h3>Today's Sales</h3>
            <p class="value">0</p>
        </div>

        <div class="metric" id="today-revenue">
            <h3>Today's Revenue</h3>
            <p class="value">UGX 0</p>
        </div>
    </div>
</div>

<script>
document.addEventListener('DOMContentLoaded', function() {
    const storeId = document.getElementById('store-dashboard').dataset.storeId;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/store/${storeId}/analytics/`);

    ws.onmessage = function(event) {
        const data = JSON.parse(event.data);

        if (data.type === 'initial_data' || data.type === 'analytics_update') {
            const metrics = data.data.today;
            document.querySelector('#today-sales .value').textContent = metrics.sales;
            document.querySelector('#today-revenue .value').textContent = 
                `UGX ${metrics.revenue.toLocaleString()}`;
        }
    };
});
</script>
"""