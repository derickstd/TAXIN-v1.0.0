from django.contrib import admin
from .models import Invoice, Payment, OtherIncome

admin.site.register(Invoice)
admin.site.register(Payment)

@admin.register(OtherIncome)
class OtherIncomeAdmin(admin.ModelAdmin):
    list_display = ('source_name', 'category', 'amount', 'income_date', 'collection_method')
    list_filter = ('category', 'collection_method', 'income_date')
    search_fields = ('source_name', 'reference', 'description')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Income Details', {'fields': ('source_name', 'category', 'amount', 'income_date')}),
        ('Collection', {'fields': ('collection_method', 'reference')}),
        ('Notes', {'fields': ('description',)}),
        ('Tracking', {'fields': ('recorded_by', 'created_at', 'updated_at')}),
    )
