from django.urls import path
from . import views

app_name = 'notifications'
urlpatterns = [
    path('',               views.notification_list,       name='list'),
    path('send-reminders/',views.send_reminders_now,      name='send_reminders'),
    path('manager-report/',views.send_manager_report_now, name='manager_report'),
    path('task-reminders/',views.send_task_reminders_now, name='task_reminders'),
]
