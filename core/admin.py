from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, AuditLog

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (('Taxman256', {'fields': ('role','phone_whatsapp','is_active_staff','date_joined_firm')}),)

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['model_name','action','changed_by','changed_at']
    list_filter = ['action','model_name']
    readonly_fields = ['model_name','object_id','action','changed_fields','changed_by','changed_at','ip_address']
