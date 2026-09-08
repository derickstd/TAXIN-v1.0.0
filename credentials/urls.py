from django.urls import path
from . import views

app_name = 'credentials'
urlpatterns = [
    path('',              views.credential_list,   name='list'),
    path('google-sync/',  views.google_sheet_sync, name='google_sync'),
    path('<int:pk>/edit/', views.credential_edit,  name='edit'),
    path('<int:pk>/reveal/', views.reveal_password, name='reveal'),
]
