from django.urls import path
from . import views

app_name = 'dashboard'
urlpatterns = [
    path('', views.index, name='index'),
    path('switch-branch/', views.switch_branch, name='switch_branch'),
    path('day-transactions/', views.day_transactions, name='day_transactions'),
]
