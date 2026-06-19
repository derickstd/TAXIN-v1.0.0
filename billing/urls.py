from django.urls import path
from . import views

app_name = 'billing'
urlpatterns = [
    path('',                    views.invoice_list,          name='list'),
    path('new/',                views.invoice_create,        name='create'),
    path('<int:pk>/',           views.invoice_detail,        name='detail'),
    path('<int:pk>/pay/',       views.record_payment,        name='pay'),
    path('client-pay/',         views.record_client_payment, name='client_pay'),
    path('<int:pk>/whatsapp/',  views.send_invoice_whatsapp, name='whatsapp'),
    path('<int:pk>/convert/',   views.convert_to_invoice,    name='convert'),
    path('aging/',              views.aging_report,          name='aging'),
    path('refresh-balances/',   views.refresh_outstanding_balances, name='refresh_balances'),
    path('refresh-balances-json/', views.refresh_outstanding_balances_json, name='refresh_balances_json'),
    # Other Income routes
    path('otherincome/',        views.other_income_list,     name='otherincome_list'),
    path('otherincome/new/',    views.other_income_create,   name='otherincome_create'),
    path('otherincome/<int:pk>/', views.other_income_detail, name='otherincome_detail'),
    path('otherincome/<int:pk>/delete/', views.other_income_delete, name='otherincome_delete'),
]
