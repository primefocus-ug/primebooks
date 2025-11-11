from django.contrib import admin
from django.urls import path
from django.db import models
from django.http import HttpResponse
from django.utils.html import format_html
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.contrib.admin import SimpleListFilter
from django.template.response import TemplateResponse
import csv
from django.utils import timezone
from datetime import datetime
from .models import Store, StoreOperatingHours, StoreDevice, DeviceOperatorLog,SecurityAlert, DeviceFingerprint,UserDeviceSession

class StoreOperatingHoursInline(admin.TabularInline):
    model = StoreOperatingHours
    extra = 0
    fields = ['day', 'opening_time', 'closing_time', 'is_closed']
    ordering = ['day']

    def get_readonly_fields(self, request, obj=None):
        if not request.user.has_perm('stores.change_storeoperatinghours'):
            return ['day', 'opening_time', 'closing_time', 'is_closed']
        return []

class StoreDeviceInline(admin.TabularInline):
    """Inline for displaying devices in the Store admin"""
    model = StoreDevice
    extra = 0
    fields = [
        'name', 'device_type', 'device_number', 'serial_number',
        'is_active', 'is_efris_linked', 'registered_at'
    ]
    readonly_fields = ['registered_at']
    ordering = ['-registered_at']

    def get_readonly_fields(self, request, obj=None):
        readonly = ['registered_at']
        if not request.user.has_perm('stores.change_storedevice'):
            readonly.extend([
                'name', 'device_type', 'device_number',
                'serial_number', 'is_active', 'is_efris_linked'
            ])
        return readonly


class BranchFilter(SimpleListFilter):
    title = _('Branch')
    parameter_name = 'branch'

    def lookups(self, request, model_admin):
        try:
            from branches.models import CompanyBranch
            branches = CompanyBranch.objects.filter(is_active=True)
            return [(branch.id, branch.name) for branch in branches]
        except ImportError:
            return []

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(branch_id=self.value())
        return queryset

class RegionFilter(SimpleListFilter):
    title = _('Region')
    parameter_name = 'region'

    def lookups(self, request, model_admin):
        regions = Store.objects.exclude(
            region__isnull=True
        ).exclude(
            region__exact=''
        ).values_list('region', flat=True).distinct().order_by('region')
        return [(region, region) for region in regions]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(region=self.value())
        return queryset

class EFRISStatusFilter(SimpleListFilter):
    title = _('EFRIS Status')
    parameter_name = 'efris_status'

    def lookups(self, request, model_admin):
        return [
            ('active', _('Active')),
            ('disabled', _('Disabled')),
            ('no_device', _('No Device')),
            ('unregistered', _('Unregistered')),
            ('inactive', _('Inactive')),
        ]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(efris_status=self.value())
        return queryset

@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'code', 'company_link', 'store_type', 'region',
        'status_display', 'efris_status_display', 'staff_count',
        'device_count', 'inventory_status', 'created_at'
    ]
    list_filter = [
        'is_active', 'company', 'store_type', 'efris_enabled',
        'is_main_branch', 'region', EFRISStatusFilter, 'created_at'
    ]
    search_fields = ['name', 'code', 'physical_address', 'region', 'tin', 'nin', 'manager_name']
    list_per_page = 25
    ordering = ['-is_main_branch', 'sort_order', 'name']
    date_hierarchy = 'created_at'

    fieldsets = (
        (_('Basic Information'), {
            'fields': ('company',  ('name', 'code'), 'store_type', 'is_main_branch')
        }),
        (_('Location'), {
            'fields': ('physical_address', 'location', 'region', 'location_gps', ('latitude', 'longitude')),
            'classes': ('collapse',)
        }),
        (_('Contact Information'), {
            'fields': (('phone', 'secondary_phone'), 'email', 'manager_name', 'manager_phone')
        }),
        (_('Tax Information'), {
            'fields': ('nin', 'tin'),
            'classes': ('collapse',)
        }),
        (_('Operating Hours'), {
            'fields': ('operating_hours', 'timezone'),
            'classes': ('collapse',)
        }),
        (_('EFRIS Configuration'), {
            'fields': (
                'efris_device_number', 'device_serial_number', 'efris_enabled',
                'is_registered_with_efris', 'efris_registration_date', 'efris_last_sync',
                'auto_fiscalize_sales', 'allow_manual_fiscalization', 'report_stock_movements'
            ),
            'classes': ('collapse',)
        }),
        (_('Settings'), {
            'fields': ('allows_sales', 'allows_inventory', 'logo', 'is_active', 'staff', 'notes', 'sort_order')
        }),
        (_('Timestamps'), {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    readonly_fields = ['created_at', 'updated_at', 'code']
    filter_horizontal = ['staff']
    inlines = [StoreOperatingHoursInline, StoreDeviceInline]
    actions = [
        'make_active', 'make_inactive', 'enable_efris',
        'disable_efris', 'export_selected_stores'
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'company'
        ).prefetch_related(
            'staff', 'devices', 'inventory_items'
        )

    def company_link(self, obj):
        if obj.company:
            try:
                url = reverse('admin:company_company_change', args=[obj.company.company_id])
                return format_html('<a href="{}">{}</a>', url, obj.company.display_name)
            except:
                return obj.company.display_name
        return '-'
    company_link.short_description = _('Company')
    company_link.admin_order_field = 'company__display_name'

    def status_display(self, obj):
        if obj.is_active:
            return format_html(
                '<span class="badge bg-success"><i class="bi bi-check-circle"></i> Active</span>'
            )
        return format_html(
            '<span class="badge bg-secondary"><i class="bi bi-x-circle"></i> Inactive</span>'
        )
    status_display.short_description = _('Status')
    status_display.admin_order_field = 'is_active'

    def efris_status_display(self, obj):
        status = obj.efris_status
        status_map = {
            'active': ('bg-primary', 'shield-check', 'Active'),
            'disabled': ('bg-warning', 'shield-x', 'Disabled'),
            'no_device': ('bg-danger', 'shield-x', 'No Device'),
            'unregistered': ('bg-warning', 'shield-x', 'Unregistered'),
            'inactive': ('bg-secondary', 'shield-x', 'Inactive'),
        }
        bg_class, icon, label = status_map.get(status, ('bg-secondary', 'shield-x', 'Inactive'))
        return format_html(
            f'<span class="badge {bg_class}"><i class="bi bi-{icon}"></i> {label}</span>'
        )
    efris_status_display.short_description = _('EFRIS')
    efris_status_display.admin_order_field = 'efris_status'

    def staff_count(self, obj):
        count = obj.staff.count()
        if count > 0:
            return format_html(
                '<span class="badge bg-info">{} staff</span>', count
            )
        return format_html('<span class="text-muted">No staff</span>')
    staff_count.short_description = _('Staff')

    def device_count(self, obj):
        total = obj.devices.count()
        active = obj.devices.filter(is_active=True).count()
        if total > 0:
            return format_html(
                '<span class="badge bg-primary">{}/{} devices</span>', active, total
            )
        return format_html('<span class="text-muted">No devices</span>')
    device_count.short_description = _('Devices')

    def inventory_status(self, obj):
        total_items = obj.inventory_items.count()
        low_stock = obj.inventory_items.filter(
            quantity__lte=models.F('low_stock_threshold')
        ).count()
        if total_items == 0:
            return format_html('<span class="text-muted">No inventory</span>')
        if low_stock > 0:
            return format_html(
                '<span class="badge bg-warning">{} items ({} low)</span>',
                total_items, low_stock
            )
        return format_html(
            '<span class="badge bg-success">{} items</span>', total_items
        )
    inventory_status.short_description = _('Inventory')

    def make_active(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} stores activated successfully.')
    make_active.short_description = _('Activate selected stores')

    def make_inactive(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} stores deactivated successfully.')
    make_inactive.short_description = _('Deactivate selected stores')

    def enable_efris(self, request, queryset):
        updated = queryset.update(efris_enabled=True)
        self.message_user(request, f'EFRIS enabled for {updated} stores.')
    enable_efris.short_description = _('Enable EFRIS for selected stores')

    def disable_efris(self, request, queryset):
        updated = queryset.update(efris_enabled=False)
        self.message_user(request, f'EFRIS disabled for {updated} stores.')
    disable_efris.short_description = _('Disable EFRIS for selected stores')

    def export_selected_stores(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="stores_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'
        writer = csv.writer(response)
        writer.writerow([
            'Name', 'Code', 'Company', 'Store Type', 'Address', 'Region',
            'Phone', 'Email', 'TIN', 'NIN', 'EFRIS Enabled', 'Status',
            'Created At', 'Manager Name', 'Is Main Branch'
        ])
        for store in queryset:
            writer.writerow([
                store.name,
                store.code,
                store.company.display_name if store.company else '',
                store.get_store_type_display(),
                store.physical_address,
                store.region or '',
                store.phone or '',
                store.email or '',
                store.tin or '',
                store.nin or '',
                'Yes' if store.efris_enabled else 'No',
                'Active' if store.is_active else 'Inactive',
                store.created_at.strftime('%Y-%m-%d %H:%M'),
                store.manager_name or '',
                'Yes' if store.is_main_branch else 'No'
            ])
        return response
    export_selected_stores.short_description = _('Export selected stores')

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('analytics/', self.admin_site.admin_view(self.analytics_view), name='store_analytics'),
            path('map/', self.admin_site.admin_view(self.map_view), name='store_map'),
        ]
        return custom_urls + urls

    def analytics_view(self, request):
        from django.db.models import Count
        stores = Store.objects.all()
        analytics_data = {
            'total_stores': stores.count(),
            'active_stores': stores.filter(is_active=True).count(),
            'main_branches': stores.filter(is_main_branch=True).count(),
            'stores_by_type': stores.values('store_type').annotate(count=Count('id')).order_by(),
            'stores_by_region': stores.values('region').annotate(count=Count('id')).order_by(),
            'efris_adoption': {
                'enabled': stores.filter(efris_enabled=True).count(),
                'total': stores.count()
            }
        }
        context = {
            'title': 'Store Analytics',
            'analytics_data': analytics_data,
            'opts': self.model._meta,
        }
        return TemplateResponse(request, 'admin/stores/analytics.html', context)

    def map_view(self, request):
        stores_with_coords = Store.objects.filter(
            latitude__isnull=False,
            longitude__isnull=False
        ).values('id', 'name', 'latitude', 'longitude', 'physical_address', 'store_type')
        context = {
            'title': 'Store Locations Map',
            'stores_data': list(stores_with_coords),
            'opts': self.model._meta,
        }
        return TemplateResponse(request, 'admin/stores/map.html', context)

@admin.register(StoreOperatingHours)
class StoreOperatingHoursAdmin(admin.ModelAdmin):
    list_display = ['store_name', 'day_display', 'time_display', 'status_display']
    list_filter = ['day', 'is_closed', 'store__is_active']
    search_fields = ['store__name', 'store__code']
    list_per_page = 50
    ordering = ['store__name', 'day']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('store')

    def store_name(self, obj):
        url = reverse('admin:stores_store_change', args=[obj.store.pk])
        return format_html('<a href="{}">{}</a>', url, obj.store.name)
    store_name.short_description = _('Store')
    store_name.admin_order_field = 'store__name'

    def day_display(self, obj):
        return obj.get_day_display()
    day_display.short_description = _('Day')
    day_display.admin_order_field = 'day'

    def time_display(self, obj):
        if obj.is_closed:
            return format_html('<span class="text-muted">Closed</span>')
        return f'{obj.opening_time} - {obj.closing_time}'
    time_display.short_description = _('Hours')

    def status_display(self, obj):
        if obj.is_closed:
            return format_html('<span class="badge bg-secondary">Closed</span>')
        return format_html('<span class="badge bg-success">Open</span>')
    status_display.short_description = _('Status')

@admin.register(StoreDevice)
class StoreDeviceAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'device_number', 'device_type', 'store_link',
        'active_sessions_badge', 'capacity_status',
        'is_active', 'is_efris_linked', 'last_seen_badge', 'registered_at'
    ]
    list_filter = [
        'device_type', 'is_active', 'is_efris_linked', 'require_approval',
        'store', 'registered_at'
    ]
    search_fields = [
        'name', 'device_number', 'serial_number', 'mac_address',
        'hardware_id', 'store__name'
    ]
    ordering = ['-registered_at']
    readonly_fields = ['registered_at', 'last_seen_at', 'active_sessions_count_display']

    fieldsets = (
        (_('Device Information'), {
            'fields': (
                'store', 'name', 'device_number', 'device_type', 'serial_number',
                'mac_address', 'hardware_id', 'notes'
            )
        }),
        (_('Status and Capacity'), {
            'fields': (
                'is_active', 'is_efris_linked', 'require_approval',
                'max_concurrent_users', 'active_sessions_count_display',
                'last_seen_at', 'registered_at'
            )
        }),
    )

    # ============================
    #  Custom Display Fields
    # ============================

    def store_link(self, obj):
        """Clickable store link"""
        try:
            url = reverse('admin:stores_store_change', args=[obj.store.pk])
            return format_html('<a href="{}">{}</a>', url, obj.store.name)
        except Exception:
            return obj.store.name
    store_link.short_description = _('Store')
    store_link.admin_order_field = 'store__name'

    def active_sessions_badge(self, obj):
        """Show active sessions count with color"""
        count = obj.active_sessions_count
        color = 'green' if count > 0 else 'gray'
        return format_html(
            '<span style="color:{}; font-weight:bold;">{}</span>',
            color, count
        )
    active_sessions_badge.short_description = _('Active Sessions')

    def capacity_status(self, obj):
        """Show if device is at capacity"""
        if obj.is_at_capacity:
            return format_html('<span style="color:red;">⚠ At Capacity</span>')
        return format_html('<span style="color:green;">✓ OK</span>')
    capacity_status.short_description = _('Capacity')

    def last_seen_badge(self, obj):
        """Show colored 'Last Seen' badge"""
        if obj.last_seen_at:
            return format_html(
                '<span style="color:gray;">{}</span>', obj.last_seen_at.strftime('%Y-%m-%d %H:%M')
            )
        return format_html('<span style="color:lightgray;">Never</span>')
    last_seen_badge.short_description = _('Last Seen')

    def active_sessions_count_display(self, obj):
        """Show active session count in detail view"""
        return obj.active_sessions_count
    active_sessions_count_display.short_description = _('Active Sessions')

    # ============================
    #  Permissions
    # ============================

    def has_add_permission(self, request):
        # Allow adding devices only if user has store permission
        return request.user.has_perm('stores.add_storedevice')

    def has_delete_permission(self, request, obj=None):
        # Only allow deletion for superusers
        return request.user.is_superuser

@admin.register(SecurityAlert)
class SecurityAlertAdmin(admin.ModelAdmin):
    list_display = [
        'created_at', 'user', 'alert_type_badge', 'severity_badge',
        'status_badge', 'store', 'notified', 'resolved_at'
    ]
    list_filter = [
        'alert_type', 'severity', 'status', 'notified',
        'store', 'created_at'
    ]
    search_fields = [
        'user__email', 'user__first_name', 'user__last_name',
        'title', 'description', 'ip_address'
    ]
    readonly_fields = [
        'created_at', 'user', 'store', 'session', 'device',
        'alert_type', 'title', 'description', 'ip_address',
        'alert_data', 'notified_at'
    ]
    date_hierarchy = 'created_at'

    fieldsets = (
        (_('Alert Information'), {
            'fields': ('user', 'store', 'session', 'device', 'created_at')
        }),
        (_('Alert Details'), {
            'fields': ('alert_type', 'severity', 'status', 'title', 'description', 'ip_address')
        }),
        (_('Alert Data'), {
            'fields': ('alert_data',),
            'classes': ('collapse',)
        }),
        (_('Notification'), {
            'fields': ('notified', 'notified_at')
        }),
        (_('Resolution'), {
            'fields': ('resolved_at', 'resolved_by', 'resolution_notes')
        }),
    )

    actions = ['mark_resolved', 'mark_false_positive', 'mark_investigating']

    def alert_type_badge(self, obj):
        return format_html(
            '<span style="font-weight: bold;">{}</span>',
            obj.get_alert_type_display()
        )

    alert_type_badge.short_description = _('Alert Type')

    def severity_badge(self, obj):
        colors = {
            'LOW': '#28a745',
            'MEDIUM': '#ffc107',
            'HIGH': '#fd7e14',
            'CRITICAL': '#dc3545',
        }
        color = colors.get(obj.severity, 'gray')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 3px; font-weight: bold;">{}</span>',
            color, obj.get_severity_display()
        )

    severity_badge.short_description = _('Severity')

    def status_badge(self, obj):
        colors = {
            'OPEN': 'red',
            'INVESTIGATING': 'orange',
            'RESOLVED': 'green',
            'FALSE_POSITIVE': 'blue',
            'IGNORED': 'gray',
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color, obj.get_status_display()
        )

    status_badge.short_description = _('Status')

    def mark_resolved(self, request, queryset):
        count = queryset.filter(status='OPEN').count()
        for alert in queryset.filter(status='OPEN'):
            alert.resolve(
                resolved_by=request.user,
                notes='Resolved via admin action'
            )
        self.message_user(request, f'{count} alert(s) marked as resolved.')

    mark_resolved.short_description = _('Mark as resolved')

    def mark_false_positive(self, request, queryset):
        count = queryset.filter(status='OPEN').count()
        for alert in queryset.filter(status='OPEN'):
            alert.mark_false_positive(
                resolved_by=request.user,
                notes='Marked as false positive via admin action'
            )
        self.message_user(request, f'{count} alert(s) marked as false positive.')

    mark_false_positive.short_description = _('Mark as false positive')

    def mark_investigating(self, request, queryset):
        count = queryset.update(status='INVESTIGATING')
        self.message_user(request, f'{count} alert(s) marked as investigating.')

    mark_investigating.short_description = _('Mark as investigating')

    def has_add_permission(self, request):
        return False  # Alerts should only be created programmatically

@admin.register(DeviceFingerprint)
class DeviceFingerprintAdmin(admin.ModelAdmin):
    list_display = [
        'device_name', 'user', 'browser_name', 'os_name',
        'trust_badge', 'login_count', 'last_seen_at', 'is_active'
    ]
    list_filter = [
        'is_trusted', 'is_active', 'browser_name',
        'os_name', 'first_seen_at'
    ]
    search_fields = [
        'user__email', 'user__first_name', 'user__last_name',
        'device_name', 'fingerprint_hash', 'last_ip_address'
    ]
    readonly_fields = [
        'fingerprint_hash', 'first_seen_at', 'last_seen_at',
        'login_count', 'trust_score'
    ]
    date_hierarchy = 'last_seen_at'

    fieldsets = (
        (_('Device Information'), {
            'fields': ('user', 'device_name', 'fingerprint_hash')
        }),
        (_('Device Details'), {
            'fields': ('browser_name', 'os_name')
        }),
        (_('Trust & Security'), {
            'fields': ('is_trusted', 'trust_score', 'is_active')
        }),
        (_('Usage Statistics'), {
            'fields': ('first_seen_at', 'last_seen_at', 'login_count')
        }),
        (_('Location'), {
            'fields': ('last_ip_address', 'last_location')
        }),
        (_('Notes'), {
            'fields': ('notes',),
            'classes': ('collapse',)
        }),
    )

    actions = ['mark_as_trusted', 'mark_as_untrusted', 'deactivate_devices']

    # --------------------------
    # Custom Display Methods
    # --------------------------
    def trust_badge(self, obj):
        """Colored badge for trust level"""
        if obj.is_trusted:
            color, icon, text = 'green', '✓', 'Trusted'
        else:
            color, icon, text = 'orange', '⚠', 'Unverified'

        return format_html(
            '<span style="color: {}; font-weight: bold;">{} {} ({})</span>',
            color, icon, text, obj.trust_score
        )
    trust_badge.short_description = _('Trust Level')

    # --------------------------
    # Admin Actions
    # --------------------------
    def mark_as_trusted(self, request, queryset):
        count = queryset.update(is_trusted=True, trust_score=100)
        self.message_user(request, f'{count} device(s) marked as trusted.')
    mark_as_trusted.short_description = _('Mark as trusted')

    def mark_as_untrusted(self, request, queryset):
        count = queryset.update(is_trusted=False, trust_score=0)
        self.message_user(request, f'{count} device(s) marked as untrusted.')
    mark_as_untrusted.short_description = _('Mark as untrusted')

    def deactivate_devices(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f'{count} device(s) deactivated.')
    deactivate_devices.short_description = _('Deactivate selected devices')


@admin.register(UserDeviceSession)
class UserDeviceSessionAdmin(admin.ModelAdmin):
    list_display = [
        'user', 'store', 'store_device', 'browser_info',
        'ip_address', 'status_badge', 'is_new_device',
        'is_suspicious', 'created_at', 'session_duration_display'
    ]
    list_filter = [
        'status', 'is_active', 'is_new_device', 'is_suspicious',
        'browser_name', 'os_name', 'store', 'created_at'
    ]
    search_fields = [
        'user__email', 'user__first_name', 'user__last_name',
        'ip_address', 'device_fingerprint', 'session_key'
    ]
    readonly_fields = [
        'session_key', 'device_fingerprint', 'created_at',
        'last_activity_at', 'logged_out_at', 'session_duration_display',
        'location_map_link'
    ]
    date_hierarchy = 'created_at'

    fieldsets = (
        (_('Session Information'), {
            'fields': ('user', 'store', 'store_device', 'session_key', 'status', 'is_active')
        }),
        (_('Device Fingerprint'), {
            'fields': ('device_fingerprint', 'browser_name', 'browser_version', 'os_name', 'os_version')
        }),
        (_('Network Information'), {
            'fields': ('ip_address', 'user_agent')
        }),
        (_('Display Information'), {
            'fields': ('screen_resolution',)  # only keep actual fields
        }),
        (_('Location'), {
            'fields': ('latitude', 'longitude', 'location_accuracy', 'location_map_link'),
            'classes': ('collapse',)
        }),
        (_('Security'), {
            'fields': ('is_new_device', 'is_suspicious', 'suspicious_reason', 'security_alerts_count')
        }),
        (_('Timing'), {
            'fields': ('created_at', 'last_activity_at', 'expires_at', 'logged_out_at', 'session_duration_display')
        }),
        (_('Metadata'), {
            'fields': ('metadata',),
            'classes': ('collapse',)
        }),
    )

    actions = ['terminate_sessions', 'extend_sessions', 'mark_as_trusted']

    def browser_info(self, obj):
        return f"{obj.browser_name} {obj.browser_version} on {obj.os_name}"

    browser_info.short_description = _('Browser/OS')

    def status_badge(self, obj):
        colors = {
            'ACTIVE': 'green',
            'EXPIRED': 'orange',
            'LOGGED_OUT': 'blue',
            'FORCE_CLOSED': 'red',
            'SUSPICIOUS': 'darkred',
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px;">{}</span>',
            color, obj.get_status_display()
        )

    status_badge.short_description = _('Status')

    def session_duration_display(self, obj):
        duration = obj.session_duration
        hours = duration.total_seconds() // 3600
        minutes = (duration.total_seconds() % 3600) // 60
        return f"{int(hours)}h {int(minutes)}m"

    session_duration_display.short_description = _('Duration')

    def location_map_link(self, obj):
        if obj.latitude and obj.longitude:
            url = f"https://www.google.com/maps?q={obj.latitude},{obj.longitude}"
            return format_html(
                '<a href="{}" target="_blank">View on Map</a>',
                url
            )
        return "No location data"

    location_map_link.short_description = _('Map')

    def terminate_sessions(self, request, queryset):
        count = 0
        for session in queryset.filter(is_active=True):
            session.terminate(reason='FORCE_CLOSED')
            count += 1
        self.message_user(request, f'{count} session(s) terminated successfully.')

    terminate_sessions.short_description = _('Terminate selected sessions')

    def extend_sessions(self, request, queryset):
        count = 0
        for session in queryset.filter(is_active=True):
            session.extend_session(hours=24)
            count += 1
        self.message_user(request, f'{count} session(s) extended by 24 hours.')

    extend_sessions.short_description = _('Extend selected sessions by 24 hours')

    def mark_as_trusted(self, request, queryset):
        for session in queryset:
            # Mark the device fingerprint as trusted
            DeviceFingerprint.objects.filter(
                user=session.user,
                fingerprint_hash=session.device_fingerprint
            ).update(is_trusted=True, trust_score=100)
        self.message_user(request, f'Marked devices as trusted.')

    mark_as_trusted.short_description = _('Mark devices as trusted')

@admin.register(DeviceOperatorLog)
class DeviceOperatorLogAdmin(admin.ModelAdmin):
    list_display = [
        'timestamp', 'user_link', 'action', 'device_link', 'store_link',
        'session_link', 'success_status', 'is_efris_related', 'ip_address_short'
    ]
    list_filter = [
        'action', 'success', 'is_efris_related', 'timestamp', 'store'
    ]
    search_fields = [
        'user__username', 'user__email', 'device__name', 'store__name',
        'ip_address', 'error_message'
    ]
    list_per_page = 100
    ordering = ['-timestamp']
    date_hierarchy = 'timestamp'
    readonly_fields = [
        'timestamp', 'user', 'action', 'device', 'store', 'session',
        'ip_address', 'details', 'is_efris_related', 'success', 'error_message'
    ]

    # ============================
    #  Query Optimization
    # ============================
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'user', 'device', 'store', 'session'
        )

    # ============================
    #  Custom display fields
    # ============================

    def user_link(self, obj):
        """Clickable link to the user"""
        if obj.user:
            try:
                url = reverse('admin:auth_user_change', args=[obj.user.pk])
                return format_html('<a href="{}">{}</a>', url, obj.user.username)
            except Exception:
                return obj.user.username
        return '-'
    user_link.short_description = _('User')
    user_link.admin_order_field = 'user__username'

    def device_link(self, obj):
        """Clickable link to the device"""
        if obj.device:
            try:
                url = reverse('admin:stores_storedevice_change', args=[obj.device.pk])
                return format_html('<a href="{}">{}</a>', url, obj.device.name)
            except Exception:
                return obj.device.name
        return '-'
    device_link.short_description = _('Device')
    device_link.admin_order_field = 'device__name'

    def store_link(self, obj):
        """Clickable link to the store"""
        if obj.store:
            try:
                url = reverse('admin:stores_store_change', args=[obj.store.pk])
                return format_html('<a href="{}">{}</a>', url, obj.store.name)
            except Exception:
                return obj.store.name
        return '-'
    store_link.short_description = _('Store')
    store_link.admin_order_field = 'store__name'

    def session_link(self, obj):
        """Clickable link to the related user-device session"""
        if obj.session:
            try:
                url = reverse('admin:stores_userdevicesession_change', args=[obj.session.pk])
                return format_html('<a href="{}">{}</a>', url, obj.session)
            except Exception:
                return str(obj.session)
        return '-'
    session_link.short_description = _('Session')
    session_link.admin_order_field = 'session'

    def success_status(self, obj):
        """Show colored badge for success/failure"""
        color = 'green' if obj.success else 'red'
        label = _('Success') if obj.success else _('Failed')
        return format_html('<span style="color:{}; font-weight:bold;">{}</span>', color, label)
    success_status.short_description = _('Status')
    success_status.admin_order_field = 'success'

    def ip_address_short(self, obj):
        """Show IP address shortened or dash"""
        return obj.ip_address or '-'
    ip_address_short.short_description = _('IP Address')

    # ============================
    #  Permissions
    # ============================

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    # ============================
    #  Display Configuration
    # ============================

    fieldsets = (
        (_('Log Details'), {
            'fields': ('timestamp', 'user', 'action', 'device', 'store', 'session')
        }),
        (_('Technical Info'), {
            'fields': ('ip_address', 'is_efris_related', 'success', 'error_message')
        }),
        (_('Additional Details'), {
            'fields': ('details',),
            'classes': ('collapse',),
        }),
    )
