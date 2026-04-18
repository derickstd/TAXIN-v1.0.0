from django.urls import path
from . import views

app_name = 'compliance'
urlpatterns = [
    path('', views.deadline_list, name='list'),
    path('<int:pk>/update/<str:action>/', views.update_status, name='update_status'),
]