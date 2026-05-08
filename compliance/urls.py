from django.urls import path
from . import views

app_name = 'compliance'
urlpatterns = [
    path('', views.deadline_list, name='list'),
    path('<int:pk>/update/<str:action>/', views.update_status, name='update_status'),
    path('credential/<int:pk>/mark-handled/', views.mark_credential_handled, name='mark_credential_handled'),
]