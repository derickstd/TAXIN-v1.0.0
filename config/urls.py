from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static
from django.shortcuts import redirect

urlpatterns = [
    path('', lambda r: redirect('dashboard:index'), name='home'),
    path('admin/', admin.site.urls),
    path('login/',  auth_views.LoginView.as_view(template_name='core/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(template_name='core/logout.html'), name='logout'),
    path('dashboard/',     include('dashboard.urls')),
    path('clients/',       include('clients.urls')),
    path('jobs/',          include('services.urls')),
    path('billing/',       include('billing.urls')),
    path('compliance/',    include('compliance.urls')),
    path('credentials/',   include('credentials.urls')),
    path('notifications/', include('notifications.urls')),
    path('expenses/',      include('expenses.urls')),
    path('documents/',     include('documents.urls')),
    path('staff/',         include('core.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
