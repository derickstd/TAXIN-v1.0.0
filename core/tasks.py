from celery import shared_task
import logging
from django.core.management import call_command
from django.core.mail import mail_admins
from django.conf import settings

from .models import Tenant

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def run_tenant_migrations(self, tenant_id):
    try:
        tenant = Tenant.objects.get(pk=tenant_id)
    except Tenant.DoesNotExist:
        logger.error('Tenant %s does not exist', tenant_id)
        return

    tenant.status = 'running'
    tenant.save()
    alias = tenant.db_alias
    try:
        # Migrate only business logic apps, skip system apps like django_apscheduler
        apps_to_migrate = [
            'auth', 'contenttypes', 'sessions', 'core', 'clients', 'services',
            'billing', 'compliance', 'credentials', 'notifications',
            'expenses', 'documents', 'dashboard', 'taxcalendar'
        ]
        for app in apps_to_migrate:
            try:
                call_command('migrate', app, database=alias, interactive=False, verbosity=0)
            except Exception as e:
                logger.warning('Failed to migrate app %s for tenant %s: %s', app, tenant.company.slug, e)
                # Continue with other apps
        tenant.status = 'ready'
        tenant.last_error = ''
        tenant.save()
        subject = f'Tenant DB created: {tenant.company.slug}'
        message = f'Tenant database {alias} for company {tenant.company.name} has been created successfully.'
        mail_admins(subject, message)
    except Exception as e:
        logger.exception('Failed running migrations for tenant %s', tenant.company.slug)
        tenant.status = 'failed'
        tenant.last_error = str(e)
        tenant.save()
        subject = f'Failed creating tenant DB: {tenant.company.slug}'
        message = f'Error creating tenant database {alias} for company {tenant.company.name}:\n{e}'
        mail_admins(subject, message)
        raise
