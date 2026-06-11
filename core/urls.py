from django.urls import path
from . import views
from . import duplicate_views

app_name = 'core'
urlpatterns = [
    path('users/',              views.user_list,       name='users'),
    path('users/new/',          views.user_create,     name='user_new'),
    path('users/<int:pk>/',     views.user_edit,       name='user_edit'),
    path('settings/',           views.user_settings,   name='settings'),
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
]
