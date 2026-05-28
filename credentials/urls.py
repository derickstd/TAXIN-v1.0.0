from django.urls import path
from . import views

app_name = 'credentials'
urlpatterns = [
    path('',              views.credential_list,   name='list'),
    path('<int:pk>/edit/', views.credential_edit,  name='edit'),
    path('<int:pk>/reveal/', views.reveal_password, name='reveal'),
]
