from django.urls import path
from . import views

app_name = 'documents'
urlpatterns = [
    path('', views.documents_home, name='home'),
    path('files/', views.doc_list, name='doc_list'),
    path('files/upload/', views.doc_upload, name='doc_upload'),
    path('files/<int:pk>/delete/', views.doc_delete, name='doc_delete'),
    path('price-list/', views.price_list, name='price_list'),
    path('statement/<int:pk>/', views.client_statement, name='statement'),
    path('monthly-report/', views.monthly_report, name='monthly_report'),
    path('reports/financial/', views.financial_reports, name='financial_reports'),
    path('reports/balance-sheet/', views.balance_sheet_report, name='balance_sheet_report'),
    path('reports/account-statement/', views.branch_account_statement, name='branch_account_statement'),
    path('account-transfer/bank-deposit/', views.branch_account_transfer, name='branch_account_transfer'),
    path('reports/branch-daily-ledger/', views.branch_daily_ledger, name='branch_daily_ledger'),
    path('reports/branch-daily-ledger/expense/', views.branch_daily_expense, name='branch_daily_expense'),
    path('reports/branch-daily-summaries/', views.branch_daily_summaries, name='branch_daily_summaries'),
    path('reports/branch-daily-summaries/<int:pk>/review/', views.review_branch_daily_summary, name='review_branch_daily_summary'),
    path('audit-books/', views.audit_books, name='audit_books'),
]
