from django.urls import path
from . import views

app_name = 'taxcalendar'
urlpatterns = [
    path('', views.calendar_view, name='list'),
    path('new/', views.event_create, name='create'),
    path('<int:pk>/status/', views.event_update_status, name='update_status'),
    path('<int:pk>/delete/', views.event_delete, name='delete'),
]
