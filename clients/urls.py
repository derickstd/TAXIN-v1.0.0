from django.urls import path
from . import views

app_name = 'clients'
urlpatterns = [
    path('',            views.client_list,        name='list'),
    path('new/',        views.client_create,      name='create'),
    path('import/',     views.client_import,      name='import'),
    path('search/',     views.client_search_api,  name='search'),
    path('walkin/',     views.walkin_create,       name='walkin'),
    path('<int:pk>/',   views.client_detail,      name='detail'),
    path('<int:pk>/edit/', views.client_edit,     name='edit'),
]
