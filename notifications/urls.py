from django.urls import path
from . import views

app_name = 'notifications'
urlpatterns = [
    path('',               views.notification_list,       name='list'),
    path('messages/',       views.message_threads,        name='message_threads'),
    path('messages/new/',   views.message_new,            name='message_new'),
    path('messages/<int:thread_id>/', views.message_thread_detail, name='message_thread'),
    path('messages/<int:thread_id>/reply/', views.message_reply, name='message_reply'),
    path('send-reminders/',views.send_reminders_now,      name='send_reminders'),
    path('manager-report/',views.send_manager_report_now, name='manager_report'),
    path('task-reminders/',views.send_task_reminders_now, name='task_reminders'),
]
