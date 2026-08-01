from django.contrib import admin
from django.urls import path, include, re_path, reverse_lazy
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static
from django.shortcuts import redirect
from core import views as core_views
from core.views import service_worker, signup

urlpatterns = [
    path('', lambda r: redirect('dashboard:index'), name='home'),
    path('admin/', admin.site.urls),
    path('login/',  core_views.custom_login, name='login'),
    path('password-reset/', auth_views.PasswordResetView.as_view(
        template_name='core/password_reset_form.html',
        email_template_name='core/password_reset_email.html',
        subject_template_name='core/password_reset_subject.txt',
        success_url=reverse_lazy('password_reset_done')
    ), name='password_reset'),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='core/password_reset_done.html'
    ), name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='core/password_reset_confirm.html',
        success_url=reverse_lazy('password_reset_complete')
    ), name='password_reset_confirm'),
    path('password-reset-complete/', auth_views.PasswordResetCompleteView.as_view(
        template_name='core/password_reset_complete.html'
    ), name='password_reset_complete'),
    path('logout/', auth_views.LogoutView.as_view(template_name='core/logout.html'), name='logout'),
    path('signup/', signup, name='signup'),
    path('sw.js',   service_worker, name='sw'),
    path('dashboard/',     include('dashboard.urls')),
    path('clients/',       include('clients.urls')),
    path('jobs/',          include('services.urls')),
    # Redirect /services/ to /jobs/ for backwards compatibility
    re_path(r'^services(?P<path>/?.*)$', lambda request, path: redirect(f'/jobs{path}')),
    path('billing/',       include('billing.urls')),
    path('compliance/',    include('compliance.urls')),
    path('credentials/',   include('credentials.urls')),
    path('notifications/', include('notifications.urls')),
    path('expenses/',      include('expenses.urls')),
    path('documents/',     include('documents.urls')),
    path('staff/',         include('core.urls')),
    path('calendar/',      include('taxcalendar.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
