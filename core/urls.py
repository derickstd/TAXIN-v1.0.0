from django.urls import path
from . import views

app_name = 'core'
urlpatterns = [
    path('users/',              views.user_list,       name='users'),
    path('users/new/',          views.user_create,     name='user_new'),
    path('users/<int:pk>/',     views.user_edit,       name='user_edit'),
    path('settings/',           views.user_settings,   name='settings'),
    path('change-password/',    views.change_password, name='change_password'),
    path('offline/',            views.offline,         name='offline'),
    path('automation/trigger/', views.trigger_automation, name='trigger_automation'),
]
