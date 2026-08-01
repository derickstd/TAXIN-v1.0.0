from django.urls import path
from . import views

app_name = 'services'
urlpatterns = [
    path('',               views.jobcard_list,         name='list'),
    path('new/',           views.jobcard_create,       name='create'),
    path('create/quick/',  views.jobcard_quick_create, name='quick_create'),
    path('catalogue/',     views.service_list,         name='catalogue'),
    path('catalogue/new/', views.service_create,       name='service_new'),
    path('catalogue/<int:pk>/toggle/', views.service_toggle, name='service_toggle'),
    path('<int:pk>/edit/',  views.jobcard_edit,         name='edit'),
    path('<int:pk>/delete/', views.jobcard_delete,      name='delete'),
    path('<int:pk>/',      views.jobcard_detail,       name='detail'),
    path('<int:pk>/status/', views.update_jobcard_status, name='update_status'),
    path('line/<int:pk>/status/', views.update_line_status, name='line_status'),
    path('ajax/check-duplicate/', views.ajax_check_duplicate, name='ajax_check_duplicate'),
]
