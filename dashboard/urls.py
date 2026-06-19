from django.urls import path
from . import views

app_name = 'dashboard'
urlpatterns = [
    path('', views.index, name='index'),
    path('day-transactions/', views.day_transactions, name='day_transactions'),
]
