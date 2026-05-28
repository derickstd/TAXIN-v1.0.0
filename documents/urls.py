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
    path('audit-books/', views.audit_books, name='audit_books'),
]
