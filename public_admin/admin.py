from django.contrib import admin
from .models import PublicStaffUser


@admin.register(PublicStaffUser)
class PublicStaffUserAdmin(admin.ModelAdmin):
    list_display = ['username', 'email', 'first_name', 'last_name', 'is_active', 'last_login']
    list_filter = ['is_active', 'created_at']
    search_fields = ['username', 'email', 'first_name', 'last_name']
    readonly_fields = ['created_at', 'last_login']

    fieldsets = (
        ('User Info', {
            'fields': ('username', 'email', 'first_name', 'last_name')
        }),
        ('Status', {
            'fields': ('is_active', 'is_staff')
        }),
        ('Security', {
            'fields': ('password',),
            'description': 'Password is hashed and cannot be viewed.'
        }),
        ('Timestamps', {
            'fields': ('created_at', 'last_login'),
            'classes': ('collapse',)
        }),
    )

    def save_model(self, request, obj, form, change):
        if 'password' in form.changed_data:
            # If password was changed, hash it
            obj.set_password(form.cleaned_data['password'])
        super().save_model(request, obj, form, change)