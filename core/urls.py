from django.urls import path
from . import views
from . import duplicate_views
from . import admin_views

app_name = 'core'
urlpatterns = [
    # Admin Dashboard
    path('admin/dashboard/', admin_views.admin_dashboard, name='admin_dashboard'),
    path('admin/control-center/', admin_views.admin_control_center, name='admin_control_center'),
    path('admin/users/', admin_views.admin_users, name='admin_users'),
    path('admin/users/<int:user_id>/send-password-reset/', admin_views.admin_send_password_reset, name='admin_send_password_reset'),
    path('admin/users/<int:user_id>/deactivate/', admin_views.admin_user_deactivate, name='admin_user_deactivate'),
    path('admin/users/<int:user_id>/reactivate/', admin_views.admin_user_reactivate, name='admin_user_reactivate'),
    path('admin/users/<int:user_id>/delete/', admin_views.admin_user_delete, name='admin_user_delete'),
    path('admin/users/bulk-reset/', admin_views.admin_bulk_password_reset, name='admin_bulk_password_reset'),
    path('admin/clients/<int:client_id>/suspend/', admin_views.admin_client_suspend, name='admin_client_suspend'),
    path('admin/clients/<int:client_id>/reactivate/', admin_views.admin_client_reactivate, name='admin_client_reactivate'),
    path('admin/companies/', admin_views.admin_companies, name='admin_companies'),
    path('admin/companies/<int:company_id>/branches/', admin_views.admin_company_branches, name='admin_company_branches'),
    path('admin/companies/<int:company_id>/suspend/', admin_views.admin_company_suspend, name='admin_company_suspend'),
    path('admin/companies/<int:company_id>/reactivate/', admin_views.admin_company_reactivate, name='admin_company_reactivate'),
    path('admin/tenants/', admin_views.admin_tenants, name='admin_tenants'),
    path('admin/tenants/<int:tenant_id>/approve/', admin_views.admin_tenant_approve, name='admin_tenant_approve'),
    path('admin/tenants/<int:tenant_id>/suspend/', admin_views.admin_tenant_suspend, name='admin_tenant_suspend'),
    path('admin/tenants/<int:tenant_id>/reactivate/', admin_views.admin_tenant_reactivate, name='admin_tenant_reactivate'),
    path('admin/audit-logs/', admin_views.admin_audit_logs, name='admin_audit_logs'),
    path('admin/audit-logs/export/', admin_views.admin_export_audit_logs, name='admin_export_audit_logs'),
    path('admin/analytics/', admin_views.admin_system_analytics, name='admin_analytics'),
    path('admin/health/', admin_views.admin_system_health, name='admin_health'),
    
    # User Management
    path('users/',              views.user_list,       name='users'),
    path('users/new/',          views.user_create,     name='user_new'),
    path('users/<int:pk>/',     views.user_edit,       name='user_edit'),
    path('settings/',           views.user_settings,   name='settings'),
    path('settings/theme/',     views.save_ui_theme,   name='save_theme'),
    path('change-password/',    views.change_password, name='change_password'),
    path('offline/',            views.offline,         name='offline'),
    path('automation/trigger/', views.trigger_automation, name='trigger_automation'),
    path('automation/run-daily/', views.run_daily_now,     name='run_daily'),
    path('duplicates/clients/', duplicate_views.duplicate_clients_list, name='duplicate_clients_list'),
    path('duplicates/clients/<int:pk>/', duplicate_views.duplicate_client_detail, name='duplicate_client_detail'),
    path('duplicates/transactions/', duplicate_views.duplicate_transactions_alerts, name='duplicate_transactions'),
    path('transactions/edits/', duplicate_views.transaction_edit_log, name='transaction_edits'),
    path('transactions/edit/<str:transaction_type>/<int:transaction_id>/', duplicate_views.edit_transaction, name='edit_transaction'),
    path('reporting/settings/', duplicate_views.reporting_settings, name='reporting_settings'),
    path('reporting/settings/<int:pk>/', duplicate_views.reporting_settings_edit, name='reporting_settings_edit'),
    path('reporting/generate/<str:report_type>/', duplicate_views.generate_report, name='generate_report'),
    
    # Export endpoints
    path('export/users/excel/', views.export_users_excel, name='export_users_excel'),
    path('export/users/pdf/', views.export_users_pdf, name='export_users_pdf'),
    path('export/clients/excel/', views.export_clients_excel, name='export_clients_excel'),
    path('export/clients/pdf/', views.export_clients_pdf, name='export_clients_pdf'),
    path('export/invoices/excel/', views.export_invoices_excel, name='export_invoices_excel'),
    path('export/invoices/pdf/', views.export_invoices_pdf, name='export_invoices_pdf'),
    path('export/jobcards/excel/', views.export_jobcards_excel, name='export_jobcards_excel'),
    path('export/jobcards/pdf/', views.export_jobcards_pdf, name='export_jobcards_pdf'),
    path('export/credentials/excel/', views.export_credentials_excel, name='export_credentials_excel'),
    path('export/credentials/pdf/', views.export_credentials_pdf, name='export_credentials_pdf'),
    path('export/deadlines/excel/', views.export_deadlines_excel, name='export_deadlines_excel'),
    path('export/deadlines/pdf/', views.export_deadlines_pdf, name='export_deadlines_pdf'),

    path('tenants/<int:pk>/progress/', views.tenant_progress, name='tenant_progress'),
    path('api/tenants/<int:pk>/status/', views.tenant_status, name='tenant_status'),
]
