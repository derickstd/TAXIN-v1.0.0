from django.urls import path
from . import views

app_name = 'billing'
urlpatterns = [
    path('',                    views.invoice_list,          name='list'),
    path('new/',                views.invoice_create,        name='create'),
    path('new/manual/',         views.invoice_create,        name='manual'),
    path('<int:pk>/',           views.invoice_detail,        name='detail'),
    path('<int:pk>/pay/',       views.record_payment,        name='pay'),
    path('<int:pk>/whatsapp/',  views.send_invoice_whatsapp, name='whatsapp'),
    path('<int:pk>/convert/',   views.convert_to_invoice,    name='convert'),
    path('aging/',              views.aging_report,          name='aging'),
]
