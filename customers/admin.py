from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from django.urls import reverse
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.db.models import Q
from .models import Customer, CustomerGroup, CustomerNote, CustomerCreditStatement, EFRISCustomerSync


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'customer_type_display',
        'phone',
        'tin',
        'credit_status_display',
        'efris_status_display',
        'is_active_display',
        'created_at'
    )

    list_filter = (
        'customer_type',
        'is_vat_registered',
        'is_active',
        'efris_status',
        'credit_status',
        'allow_credit',
        'store',
        'district',
        ('created_at', admin.DateFieldListFilter),
    )

    search_fields = (
        'name',
        'customer_id',
        'tin',
        'nin',
        'brn',
        'phone',
        'email',
        'passport_number',
        'driving_license',
        'efris_customer_id',
        'efris_reference_no',
    )

    list_select_related = ('store', 'created_by')

    ordering = ('-created_at', 'name')

    date_hierarchy = 'created_at'

    actions = [
        'activate_customers',
        'deactivate_customers',
        'enable_credit',
        'disable_credit',
        'sync_to_efris',
        'update_credit_balances',
        'export_selected',
    ]

    fieldsets = (
        ('Basic Information', {
            'fields': (
                'customer_type',
                'name',
                'store',
                'email',
                'phone',
                ('created_by', 'created_at'),
            )
        }),

        ('Tax Information', {
            'fields': (
                'tin',
                'nin',
                'brn',
                'is_vat_registered',
            ),
            'classes': ('collapse',),
        }),

        ('Additional Identification', {
            'fields': (
                'passport_number',
                'driving_license',
                'voter_id',
                'alien_id',
            ),
            'classes': ('collapse',),
        }),

        ('Address Information', {
            'fields': (
                'physical_address',
                'postal_address',
                'district',
                'country'
            ),
            'classes': ('collapse',),
        }),

        ('Credit Management', {
            'fields': (
                'allow_credit',
                'credit_limit',
                'credit_days',
                'credit_status',
                ('credit_balance', 'credit_available'),
                'last_credit_review',
            )
        }),

        ('eFRIS Integration', {
            'fields': (
                'efris_customer_type',
                'efris_status',
                'efris_customer_id',
                'efris_reference_no',
                'efris_registered_at',
                'efris_last_sync',
                'efris_sync_error',
            ),
            'classes': ('collapse',),
        }),

        ('Status & Meta', {
            'fields': (
                'is_active',
                ('updated_at',),
            )
        }),
    )

    readonly_fields = (
        'created_at',
        'updated_at',
        'created_by',
        'credit_balance',
        'credit_available',
        'efris_registered_at',
        'efris_last_sync',
    )

    autocomplete_fields = ['store', 'created_by']

    # Custom list display methods
    def customer_type_display(self, obj):
        colors = {
            'INDIVIDUAL': 'info',
            'BUSINESS': 'success',
            'GOVERNMENT': 'warning',
            'NGO': 'primary',
        }
        color = colors.get(obj.customer_type, 'secondary')
        return format_html(
            '<span class="badge bg-{}">{}</span>',
            color,
            obj.get_customer_type_display()
        )

    customer_type_display.short_description = 'Type'
    customer_type_display.admin_order_field = 'customer_type'

    def credit_status_display(self, obj):
        colors = {
            'GOOD': 'success',
            'WARNING': 'warning',
            'SUSPENDED': 'danger',
            'BLOCKED': 'dark',
        }
        color = colors.get(obj.credit_status, 'secondary')
        badge = format_html(
            '<span class="badge bg-{}">{}</span>',
            color,
            obj.get_credit_status_display()
        )

        if obj.allow_credit:
            limit_info = format_html(
                '<small class="text-muted d-block">{} / {}</small>',
                obj.credit_balance,
                obj.credit_limit
            )
            return format_html('{} {}', badge, limit_info)
        return badge

    credit_status_display.short_description = 'Credit Status'
    credit_status_display.admin_order_field = 'credit_status'

    def efris_status_display(self, obj):
        colors = {
            'REGISTERED': 'success',
            'PENDING': 'warning',
            'FAILED': 'danger',
            'NOT_REGISTERED': 'secondary',
            'UPDATED': 'info',
        }
        color = colors.get(obj.efris_status, 'secondary')
        badge = format_html(
            '<span class="badge bg-{}">{}</span>',
            color,
            obj.get_efris_status_display()
        )

        if obj.efris_customer_id:
            efris_id = format_html(
                '<small class="text-muted d-block">{}</small>',
                obj.efris_customer_id[:8] + '...' if len(obj.efris_customer_id) > 8 else obj.efris_customer_id
            )
            return format_html('{} {}', badge, efris_id)
        return badge

    efris_status_display.short_description = 'eFRIS Status'
    efris_status_display.admin_order_field = 'efris_status'

    def is_active_display(self, obj):
        if obj.is_active:
            return format_html(
                '<span class="badge bg-success">Active</span>'
            )
        return format_html(
            '<span class="badge bg-danger">Inactive</span>'
        )

    is_active_display.short_description = 'Status'
    is_active_display.admin_order_field = 'is_active'

    # Custom actions
    def activate_customers(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(
            request,
            f'Successfully activated {updated} customer(s).',
            messages.SUCCESS
        )

    activate_customers.short_description = "Activate selected customers"

    def deactivate_customers(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(
            request,
            f'Successfully deactivated {updated} customer(s).',
            messages.SUCCESS
        )

    deactivate_customers.short_description = "Deactivate selected customers"

    def enable_credit(self, request, queryset):
        updated = queryset.update(allow_credit=True)
        self.message_user(
            request,
            f'Enabled credit for {updated} customer(s).',
            messages.SUCCESS
        )

    enable_credit.short_description = "Enable credit for selected customers"

    def disable_credit(self, request, queryset):
        updated = queryset.update(allow_credit=False)
        self.message_user(
            request,
            f'Disabled credit for {updated} customer(s).',
            messages.SUCCESS
        )

    disable_credit.short_description = "Disable credit for selected customers"

    def sync_to_efris(self, request, queryset):
        # Filter customers that can be synced
        eligible_customers = queryset.filter(
            Q(efris_status__in=['NOT_REGISTERED', 'FAILED']) &
            Q(name__isnull=False) & ~Q(name='') &
            Q(phone__isnull=False) & ~Q(phone='')
        )

        if eligible_customers.count() == 0:
            self.message_user(
                request,
                'No eligible customers for eFRIS sync.',
                messages.WARNING
            )
            return

        # Redirect to custom sync view or perform sync
        customer_ids = ','.join(str(c.id) for c in eligible_customers)
        url = reverse('admin:customers_efrissync_changelist') + f'?customers={customer_ids}'
        return HttpResponseRedirect(url)

    sync_to_efris.short_description = "Sync to eFRIS"

    def update_credit_balances(self, request, queryset):
        updated = 0
        for customer in queryset:
            customer.update_credit_balance()
            updated += 1

        self.message_user(
            request,
            f'Updated credit balances for {updated} customer(s).',
            messages.SUCCESS
        )

    update_credit_balances.short_description = "Update credit balances"

    def export_selected(self, request, queryset):
        from django.http import HttpResponse
        import csv

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="customers_export_{request.user.username}.csv"'

        writer = csv.writer(response)
        writer.writerow([
            'Customer ID', 'Name', 'Type', 'Phone', 'Email',
            'TIN', 'NIN', 'BRN', 'VAT Registered',
            'Credit Limit', 'Credit Balance', 'Credit Available', 'Credit Status',
            'eFRIS Status', 'eFRIS ID', 'District', 'Country',
            'Created Date', 'Last Updated'
        ])

        for customer in queryset:
            writer.writerow([
                customer.customer_id,
                customer.name,
                customer.get_customer_type_display(),
                customer.phone,
                customer.email,
                customer.tin,
                customer.nin,
                customer.brn,
                'Yes' if customer.is_vat_registered else 'No',
                customer.credit_limit,
                customer.credit_balance,
                customer.credit_available,
                customer.get_credit_status_display(),
                customer.get_efris_status_display(),
                customer.efris_customer_id,
                customer.district,
                customer.country,
                customer.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                customer.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
            ])

        return response

    export_selected.short_description = "Export selected customers to CSV"

    # Custom methods
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related(
            'store', 'created_by'
        ).prefetch_related(
            'groups', 'notes', 'credit_statements', 'efris_syncs'
        )

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(self.readonly_fields)
        if obj and obj.is_efris_registered:
            readonly_fields.append('efris_customer_id')
        return readonly_fields

    def save_model(self, request, obj, form, change):
        if not change:  # New object
            obj.created_by = request.user

        # Auto-calculate credit available
        if 'credit_limit' in form.changed_data or 'credit_balance' in form.changed_data:
            obj.credit_available = max(0, obj.credit_limit - obj.credit_balance)

        # Auto-set eFRIS customer type based on customer type
        if 'customer_type' in form.changed_data and not obj.efris_customer_type:
            mapping = {
                'INDIVIDUAL': '1',
                'BUSINESS': '2',
                'GOVERNMENT': '3',
                'NGO': '4',
            }
            obj.efris_customer_type = mapping.get(obj.customer_type, '1')

        super().save_model(request, obj, form, change)

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}

        # Add statistics to context
        total_customers = Customer.objects.count()
        active_customers = Customer.objects.filter(is_active=True).count()
        vat_registered = Customer.objects.filter(is_vat_registered=True).count()
        credit_enabled = Customer.objects.filter(allow_credit=True).count()
        efris_registered = Customer.objects.filter(efris_status='REGISTERED').count()

        extra_context.update({
            'total_customers': total_customers,
            'active_customers': active_customers,
            'vat_registered': vat_registered,
            'credit_enabled': credit_enabled,
            'efris_registered': efris_registered,
        })

        return super().changelist_view(request, extra_context=extra_context)

    class Media:
        css = {
            'all': ('admin/css/custom.css',)
        }


@admin.register(CustomerGroup)
class CustomerGroupAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'discount_percentage_display',
        'customer_count',
        'efris_registered_count',
        'auto_sync_to_efris_display',
        'created_at'
    )

    list_filter = (
        'auto_sync_to_efris',
        ('created_at', admin.DateFieldListFilter),
    )

    search_fields = ('name', 'description')

    filter_horizontal = ('customers',)

    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'description', 'discount_percentage')
        }),
        ('Customers', {
            'fields': ('customers',)
        }),
        ('eFRIS Integration', {
            'fields': ('auto_sync_to_efris',)
        }),
        ('Statistics', {
            'fields': (('customer_count', 'efris_registered_count'),)
        }),
        ('Dates', {
            'fields': (('created_at', 'updated_at'),)
        }),
    )

    readonly_fields = (
        'created_at',
        'updated_at',
        'customer_count',
        'efris_registered_count',
    )

    actions = ['sync_groups_to_efris']

    # Custom list display methods
    def discount_percentage_display(self, obj):
        if obj.discount_percentage > 0:
            return format_html(
                '<span class="badge bg-success">{}% off</span>',
                obj.discount_percentage
            )
        return '-'

    discount_percentage_display.short_description = 'Discount'
    discount_percentage_display.admin_order_field = 'discount_percentage'

    def customer_count(self, obj):
        count = obj.customers.count()
        url = reverse('admin:customers_customer_changelist')
        url += f'?groups__id__exact={obj.id}'
        return format_html(
            '<a href="{}">{}</a>',
            url,
            count
        )

    customer_count.short_description = 'Customers'

    def efris_registered_count(self, obj):
        count = obj.customers.filter(efris_status='REGISTERED').count()
        if count > 0:
            url = reverse('admin:customers_customer_changelist')
            url += f'?groups__id__exact={obj.id}&efris_status__exact=REGISTERED'
            return format_html(
                '<a href="{}" class="text-success">{}</a>',
                url,
                count
            )
        return format_html('<span class="text-muted">{}</span>', count)

    efris_registered_count.short_description = 'eFRIS Registered'

    def auto_sync_to_efris_display(self, obj):
        if obj.auto_sync_to_efris:
            return format_html(
                '<span class="badge bg-info">Auto Sync</span>'
            )
        return format_html(
            '<span class="badge bg-secondary">Manual</span>'
        )

    auto_sync_to_efris_display.short_description = 'Sync Mode'
    auto_sync_to_efris_display.admin_order_field = 'auto_sync_to_efris'

    # Custom action
    def sync_groups_to_efris(self, request, queryset):
        groups_with_auto_sync = queryset.filter(auto_sync_to_efris=True)

        if groups_with_auto_sync.count() == 0:
            self.message_user(
                request,
                'No groups selected with auto-sync enabled.',
                messages.WARNING
            )
            return

        customer_ids = []
        for group in groups_with_auto_sync:
            eligible_customers = group.customers.filter(
                efris_status__in=['NOT_REGISTERED', 'FAILED'],
                name__isnull=False,
                phone__isnull=False
            )
            customer_ids.extend(eligible_customers.values_list('id', flat=True))

        if customer_ids:
            customer_ids_str = ','.join(str(id) for id in set(customer_ids))
            url = reverse('admin:customers_efrissync_changelist') + f'?customers={customer_ids_str}'
            return HttpResponseRedirect(url)

        self.message_user(
            request,
            'No eligible customers found in selected groups.',
            messages.INFO
        )

    sync_groups_to_efris.short_description = "Sync group customers to eFRIS"

    # Custom methods
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.prefetch_related('customers')


@admin.register(CustomerNote)
class CustomerNoteAdmin(admin.ModelAdmin):
    list_display = (
        'customer_link',
        'note_preview',
        'category_display',
        'is_important_display',
        'author_link',
        'created_at'
    )

    list_filter = (
        'category',
        'is_important',
        ('created_at', admin.DateFieldListFilter),
        ('customer__customer_type', admin.RelatedOnlyFieldListFilter),
    )

    search_fields = (
        'customer__name',
        'customer__customer_id',
        'note',
        'author__username',
        'author__email'
    )

    list_select_related = ('customer', 'author')

    ordering = ('-created_at',)

    date_hierarchy = 'created_at'

    fieldsets = (
        ('Note Details', {
            'fields': ('customer', 'note', 'category', 'is_important')
        }),
        ('Author Information', {
            'fields': ('author',)
        }),
        ('Dates', {
            'fields': (('created_at', 'updated_at'),)
        }),
    )

    readonly_fields = ('created_at', 'updated_at', 'author')

    autocomplete_fields = ['customer', 'author']

    # Custom list display methods
    def customer_link(self, obj):
        url = reverse('admin:customers_customer_change', args=[obj.customer.id])
        return format_html(
            '<a href="{}">{}</a>',
            url,
            obj.customer.name
        )

    customer_link.short_description = 'Customer'
    customer_link.admin_order_field = 'customer__name'

    def note_preview(self, obj):
        preview = obj.note[:100]
        if len(obj.note) > 100:
            preview += '...'
        return format_html('<span title="{}">{}</span>', obj.note, preview)

    note_preview.short_description = 'Note'

    def category_display(self, obj):
        colors = {
            'GENERAL': 'secondary',
            'EFRIS': 'info',
            'TAX': 'warning',
            'PAYMENT': 'success',
            'SUPPORT': 'danger',
        }
        color = colors.get(obj.category, 'secondary')
        return format_html(
            '<span class="badge bg-{}">{}</span>',
            color,
            obj.get_category_display()
        )

    category_display.short_description = 'Category'
    category_display.admin_order_field = 'category'

    def is_important_display(self, obj):
        if obj.is_important:
            return format_html(
                '<span class="badge bg-danger">Important</span>'
            )
        return '-'

    is_important_display.short_description = 'Important'
    is_important_display.admin_order_field = 'is_important'

    def author_link(self, obj):
        if obj.author:
            url = reverse('admin:accounts_customuser_change', args=[obj.author.id])
            return format_html(
                '<a href="{}">{}</a>',
                url,
                obj.author.get_full_name() or obj.author.username
            )
        return '-'

    author_link.short_description = 'Author'
    author_link.admin_order_field = 'author__username'

    # Custom methods
    def save_model(self, request, obj, form, change):
        if not change:  # New object
            obj.author = request.user
        super().save_model(request, obj, form, change)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related('customer', 'author')


@admin.register(CustomerCreditStatement)
class CustomerCreditStatementAdmin(admin.ModelAdmin):
    list_display = (
        'customer_link',
        'transaction_type_display',
        'amount_display',
        'balance_before',
        'balance_after',
        'reference_number',
        'created_by_link',
        'created_at'
    )

    list_filter = (
        'transaction_type',
        ('created_at', admin.DateFieldListFilter),
        ('customer__customer_type', admin.RelatedOnlyFieldListFilter),
        ('customer__credit_status', admin.RelatedOnlyFieldListFilter),
    )

    search_fields = (
        'customer__name',
        'customer__customer_id',
        'description',
        'reference_number',
        'created_by__username'
    )

    list_select_related = ('customer', 'created_by', 'sale', 'payment')

    ordering = ('-created_at',)

    date_hierarchy = 'created_at'

    readonly_fields = (
        'created_at',
        'created_by',
        'balance_before',
        'balance_after',
    )

    fieldsets = (
        ('Transaction Details', {
            'fields': (
                'customer',
                'transaction_type',
                ('sale', 'payment'),
                'amount',
                ('balance_before', 'balance_after'),
            )
        }),
        ('Description', {
            'fields': ('description', 'reference_number')
        }),
        ('Author', {
            'fields': ('created_by',)
        }),
        ('Date', {
            'fields': ('created_at',)
        }),
    )

    autocomplete_fields = ['customer', 'created_by', 'sale', 'payment']

    # Custom list display methods
    def customer_link(self, obj):
        url = reverse('admin:customers_customer_change', args=[obj.customer.id])
        return format_html(
            '<a href="{}">{}</a>',
            url,
            obj.customer.name
        )

    customer_link.short_description = 'Customer'
    customer_link.admin_order_field = 'customer__name'

    def transaction_type_display(self, obj):
        colors = {
            'INVOICE': 'warning',
            'PAYMENT': 'success',
            'CREDIT_NOTE': 'info',
            'ADJUSTMENT': 'secondary',
        }
        color = colors.get(obj.transaction_type, 'secondary')
        return format_html(
            '<span class="badge bg-{}">{}</span>',
            color,
            obj.get_transaction_type_display()
        )

    transaction_type_display.short_description = 'Type'
    transaction_type_display.admin_order_field = 'transaction_type'

    def amount_display(self, obj):
        color = 'success' if obj.transaction_type == 'PAYMENT' else 'danger'
        icon = '↓' if obj.transaction_type == 'PAYMENT' else '↑'
        return format_html(
            '<span class="text-{}">{} {}</span>',
            color,
            icon,
            obj.amount
        )

    amount_display.short_description = 'Amount'
    amount_display.admin_order_field = 'amount'

    def created_by_link(self, obj):
        if obj.created_by:
            url = reverse('admin:accounts_customuser_change', args=[obj.created_by.id])
            return format_html(
                '<a href="{}">{}</a>',
                url,
                obj.created_by.get_full_name() or obj.created_by.username
            )
        return '-'

    created_by_link.short_description = 'Created By'
    created_by_link.admin_order_field = 'created_by__username'

    # Custom methods
    def save_model(self, request, obj, form, change):
        if not change:  # New object
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related('customer', 'created_by', 'sale', 'payment')


@admin.register(EFRISCustomerSync)
class EFRISCustomerSyncAdmin(admin.ModelAdmin):
    list_display = (
        'customer_link',
        'sync_type_display',
        'status_display',
        'efris_reference',
        'retry_count_display',
        'created_at',
        'processed_at'
    )

    list_filter = (
        'sync_type',
        'status',
        ('created_at', admin.DateFieldListFilter),
        ('processed_at', admin.DateFieldListFilter),
    )

    search_fields = (
        'customer__name',
        'customer__customer_id',
        'efris_reference',
        'error_message',
        'customer__efris_customer_id'
    )

    list_select_related = ('customer',)

    ordering = ('-created_at',)

    date_hierarchy = 'created_at'

    readonly_fields = (
        'created_at',
        'updated_at',
        'processed_at',
        'retry_count',
    )

    fieldsets = (
        ('Sync Information', {
            'fields': (
                'customer',
                ('sync_type', 'status'),
                ('retry_count', 'max_retries'),
            )
        }),
        ('Response Data', {
            'fields': (
                'efris_reference',
                'request_payload',
                'response_data',
                'error_message',
            ),
            'classes': ('collapse',),
        }),
        ('Dates', {
            'fields': (
                ('created_at', 'updated_at'),
                'processed_at',
            )
        }),
    )

    actions = ['retry_failed_syncs', 'mark_for_retry']

    # Custom list display methods
    def customer_link(self, obj):
        url = reverse('admin:customers_customer_change', args=[obj.customer.id])
        return format_html(
            '<a href="{}">{}</a>',
            url,
            obj.customer.name
        )

    customer_link.short_description = 'Customer'
    customer_link.admin_order_field = 'customer__name'

    def sync_type_display(self, obj):
        colors = {
            'REGISTER': 'primary',
            'UPDATE': 'info',
            'QUERY': 'secondary',
        }
        color = colors.get(obj.sync_type, 'secondary')
        return format_html(
            '<span class="badge bg-{}">{}</span>',
            color,
            obj.get_sync_type_display()
        )

    sync_type_display.short_description = 'Sync Type'
    sync_type_display.admin_order_field = 'sync_type'

    def status_display(self, obj):
        colors = {
            'SUCCESS': 'success',
            'FAILED': 'danger',
            'PENDING': 'warning',
            'RETRY': 'info',
        }
        color = colors.get(obj.status, 'secondary')
        return format_html(
            '<span class="badge bg-{}">{}</span>',
            color,
            obj.get_status_display()
        )

    status_display.short_description = 'Status'
    status_display.admin_order_field = 'status'

    def retry_count_display(self, obj):
        if obj.retry_count > 0:
            color = 'warning' if obj.retry_count < obj.max_retries else 'danger'
            return format_html(
                '<span class="badge bg-{}">{}/{}</span>',
                color,
                obj.retry_count,
                obj.max_retries
            )
        return '-'

    retry_count_display.short_description = 'Retries'

    # Custom actions
    def retry_failed_syncs(self, request, queryset):
        eligible_syncs = queryset.filter(
            status__in=['FAILED', 'RETRY'],
            retry_count__lt=models.F('max_retries')
        )

        if eligible_syncs.count() == 0:
            self.message_user(
                request,
                'No eligible syncs for retry.',
                messages.WARNING
            )
            return

        from .efris_service import EFRISCustomerService
        service = EFRISCustomerService()

        success_count = 0
        failed_count = 0

        for sync in eligible_syncs:
            try:
                if sync.sync_type == 'REGISTER':
                    result = service.register_customer(sync.customer)
                elif sync.sync_type == 'UPDATE':
                    result = service.update_customer(sync.customer)
                else:
                    continue

                if result['success']:
                    sync.mark_success(
                        response_data=result.get('response_data'),
                        efris_reference=result.get('reference')
                    )
                    success_count += 1
                else:
                    sync.mark_failed(
                        error_message=result.get('error', 'Unknown error'),
                        should_retry=True
                    )
                    failed_count += 1

            except Exception as e:
                sync.mark_failed(str(e), should_retry=True)
                failed_count += 1

        self.message_user(
            request,
            f'Retried {eligible_syncs.count()} syncs: {success_count} succeeded, {failed_count} failed.',
            messages.SUCCESS if success_count > 0 else messages.WARNING
        )

    retry_failed_syncs.short_description = "Retry selected syncs"

    def mark_for_retry(self, request, queryset):
        updated = queryset.filter(
            status='FAILED',
            retry_count__lt=models.F('max_retries')
        ).update(status='RETRY')

        self.message_user(
            request,
            f'Marked {updated} failed syncs for retry.',
            messages.SUCCESS
        )

    mark_for_retry.short_description = "Mark for retry"

    # Custom methods
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related('customer')

    def has_add_permission(self, request):
        return False  # Syncs should only be created via API/views

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        extra_context = extra_context or {}
        extra_context['show_save_and_continue'] = False
        extra_context['show_save_and_add_another'] = False
        return super().changeform_view(request, object_id, form_url, extra_context)


# Inline admin for related models
class CustomerNoteInline(admin.TabularInline):
    model = CustomerNote
    extra = 1
    readonly_fields = ('created_at', 'updated_at', 'author')
    fields = ('note', 'category', 'is_important', 'author', 'created_at')

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "author":
            kwargs["initial"] = request.user.id
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.author = request.user
        super().save_model(request, obj, form, change)


class CustomerCreditStatementInline(admin.TabularInline):
    model = CustomerCreditStatement
    extra = 0
    readonly_fields = ('created_at', 'created_by', 'balance_before', 'balance_after')
    fields = ('transaction_type', 'amount', 'description', 'reference_number', 'created_by', 'created_at')
    can_delete = False
    max_num = 10

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "created_by":
            kwargs["initial"] = request.user.id
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def has_add_permission(self, request, obj):
        return True


class EFRISCustomerSyncInline(admin.TabularInline):
    model = EFRISCustomerSync
    extra = 0
    readonly_fields = ('created_at', 'updated_at', 'processed_at')
    fields = ('sync_type', 'status', 'efris_reference', 'created_at')
    can_delete = False
    max_num = 5

    def has_add_permission(self, request, obj):
        return False


# Add inlines to CustomerAdmin
CustomerAdmin.inlines = [
    CustomerNoteInline,
    CustomerCreditStatementInline,
    EFRISCustomerSyncInline,
]




# Optional: Custom CSS for admin
class CustomAdminSite(admin.AdminSite):
    class Media:
        css = {
            'all': ('admin/css/custom.css',)
        }