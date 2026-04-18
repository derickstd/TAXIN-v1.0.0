from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, AuditLog


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Taxman256', {'fields': ('role', 'phone_whatsapp', 'email_notify',
                                  'is_active_staff', 'date_joined_firm',
                                  'receive_debt_alerts', 'receive_task_reminders',
                                  'ui_theme')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'password1', 'password2',
                       'first_name', 'last_name', 'email',
                       'role', 'phone_whatsapp', 'is_active_staff'),
        }),
    )
    list_display = ['username', 'get_full_name', 'role', 'is_active', 'is_active_staff']
    list_filter = ['role', 'is_active', 'is_active_staff']

    def save_model(self, request, obj, form, change):
        # Ensure every user saved via admin has a usable password
        if not obj.has_usable_password():
            obj.set_password('taxman2025!')
        # Ensure is_active is always True unless explicitly unchecked
        if not change:
            obj.is_active = True
            obj.is_active_staff = True
        super().save_model(request, obj, form, change)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['model_name', 'action', 'changed_by', 'changed_at']
    list_filter = ['action', 'model_name']
    readonly_fields = ['model_name', 'object_id', 'action', 'changed_fields',
                       'changed_by', 'changed_at', 'ip_address']
