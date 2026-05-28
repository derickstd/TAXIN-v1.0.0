from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        import os
        # Prevent double-start in Django's auto-reloader (dev) and in manage.py commands
        if os.environ.get('RUN_MAIN') == 'true' or not os.environ.get('DJANGO_SETTINGS_MODULE'):
            return
        # In production (gunicorn/waitress) RUN_MAIN is not set — start normally
        # In dev runserver the reloader sets RUN_MAIN='true' on the child process — skip parent
        if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
            return

        try:
            self._start_scheduler()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Scheduler not started: {e}")

    def _start_scheduler(self):
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        from django_apscheduler.jobstores import DjangoJobStore
        from core import jobs
        import logging
        log = logging.getLogger(__name__)

        scheduler = BackgroundScheduler(timezone='Africa/Kampala')
        scheduler.add_jobstore(DjangoJobStore(), 'default')

        # Daily 6AM — mark overdue invoices + update client statuses
        scheduler.add_job(
            jobs.update_client_statuses,
            CronTrigger(hour=6, minute=0),
            id='update_statuses', replace_existing=True, jobstore='default',
            misfire_grace_time=3600,
        )

        # Friday 8AM — debt reminders to clients
        scheduler.add_job(
            jobs.send_friday_client_reminders,
            CronTrigger(day_of_week='fri', hour=8, minute=0),
            id='friday_reminders', replace_existing=True, jobstore='default',
            misfire_grace_time=3600,
        )

        # Saturday & Monday 8AM — manager debt report
        scheduler.add_job(
            jobs.send_manager_debt_report,
            CronTrigger(day_of_week='sat,mon', hour=8, minute=0),
            id='manager_report', replace_existing=True, jobstore='default',
            misfire_grace_time=3600,
        )

        # Monday & Thursday 9AM — task reminders to staff
        scheduler.add_job(
            jobs.send_task_reminders,
            CronTrigger(day_of_week='mon,thu', hour=9, minute=0),
            id='task_reminders', replace_existing=True, jobstore='default',
            misfire_grace_time=3600,
        )

        # 1st of month 7AM — auto-generate monthly job cards
        scheduler.add_job(
            jobs.generate_monthly_jobcards,
            CronTrigger(day=1, hour=7, minute=0),
            id='monthly_jobs', replace_existing=True, jobstore='default',
            misfire_grace_time=3600,
        )

        # 1st of month 7:30AM — generate compliance deadlines
        scheduler.add_job(
            jobs.generate_compliance_deadlines,
            CronTrigger(day=1, hour=7, minute=30),
            id='compliance_deadlines', replace_existing=True, jobstore='default',
            misfire_grace_time=3600,
        )

        # Daily 6:30AM — mark overdue invoices
        scheduler.add_job(
            _mark_overdue_invoices,
            CronTrigger(hour=6, minute=30),
            id='mark_overdue', replace_existing=True, jobstore='default',
            misfire_grace_time=3600,
        )

        scheduler.start()
        log.info("✅ Taxman256 scheduler started — 7 jobs registered")


def _mark_overdue_invoices():
    """Mark sent/partially_paid invoices as overdue when due date passes."""
    from billing.models import Invoice
    from django.utils import timezone
    updated = Invoice.objects.filter(
        status__in=['sent', 'partially_paid'],
        due_date__lt=timezone.now().date()
    ).update(status='overdue')
    if updated:
        import logging
        logging.getLogger(__name__).info(f"Marked {updated} invoices as overdue")
