from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, AuditLog, Company, Tenant
from .models import ModelVisibility, UserModelPermission


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'registration_number', 'tin', 'active', 'owner']
    search_fields = ['name', 'slug', 'tin', 'registration_number', 'email']
    list_filter = ['active']
    prepopulated_fields = {'slug': ('name',)}


class UserModelPermissionInline(admin.TabularInline):
    model = UserModelPermission
    extra = 0
    raw_id_fields = ['content_type']


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Taxman256', {'fields': ('company', 'role', 'phone_whatsapp', 'email_notify',
                                  'is_active_staff', 'date_joined_firm',
                                  'receive_debt_alerts', 'receive_task_reminders',
                                  'ui_theme')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'password1', 'password2',
                       'first_name', 'last_name', 'email', 'company',
                       'role', 'phone_whatsapp', 'is_active_staff'),
        }),
    )
    list_display = ['username', 'get_full_name', 'company', 'role', 'is_active', 'is_active_staff']
    list_filter = ['company', 'role', 'is_active', 'is_active_staff']
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

    inlines = [UserModelPermissionInline]

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


@admin.register(ModelVisibility)
class ModelVisibilityAdmin(admin.ModelAdmin):
    list_display = ['content_type', 'enabled', 'description']
    list_filter = ['enabled', 'content_type__app_label']
    search_fields = ['content_type__app_label', 'content_type__model', 'description']


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ['company', 'db_alias', 'status', 'created_at']
    list_filter = ['status']
    readonly_fields = ['db_alias', 'db_path', 'status', 'created_by', 'last_error', 'created_at', 'updated_at']
    search_fields = ['company__name', 'db_alias']
