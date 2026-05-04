from django.apps import AppConfig

class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        import os
        if os.environ.get('RUN_MAIN') != 'true':
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

        scheduler = BackgroundScheduler(timezone='Africa/Kampala')
        scheduler.add_jobstore(DjangoJobStore(), 'default')

        # Daily 6AM: update client statuses
        scheduler.add_job(jobs.update_client_statuses, CronTrigger(hour=6, minute=0),
            id='update_statuses', replace_existing=True, jobstore='default')

        # Friday 8AM: debt reminders to clients
        scheduler.add_job(jobs.send_friday_client_reminders, CronTrigger(day_of_week='fri', hour=8, minute=0),
            id='friday_reminders', replace_existing=True, jobstore='default')

        # Saturday & Monday 8AM: manager debt report
        scheduler.add_job(jobs.send_manager_debt_report, CronTrigger(day_of_week='sat,mon', hour=8, minute=0),
            id='manager_report', replace_existing=True, jobstore='default')

        # Monday & Thursday 9AM: task reminders to staff
        scheduler.add_job(jobs.send_task_reminders, CronTrigger(day_of_week='mon,thu', hour=9, minute=0),
            id='task_reminders', replace_existing=True, jobstore='default')

        # 1st of month 7AM: auto-generate monthly job cards
        scheduler.add_job(jobs.generate_monthly_jobcards, CronTrigger(day=1, hour=7, minute=0),
            id='monthly_jobs', replace_existing=True, jobstore='default')

        # 1st of month 7:30AM: generate compliance deadlines
        scheduler.add_job(jobs.generate_compliance_deadlines, CronTrigger(day=1, hour=7, minute=30),
            id='compliance_deadlines', replace_existing=True, jobstore='default')

        scheduler.start()
        import logging
        logging.getLogger(__name__).info("✅ Taxman256 scheduler started — 6 jobs registered")
