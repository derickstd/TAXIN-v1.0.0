from django.urls import path
from . import views

app_name = 'expenses'
urlpatterns = [
    path('', views.expense_list, name='list'),
    path('new/', views.expense_create, name='create'),
    path('<int:pk>/approve/', views.approve_expense, name='approve'),
]
