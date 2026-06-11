from django.apps import AppConfig


class Config(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'expenses'
    
    def ready(self):
        """Register signals when app is ready."""
        import expenses.signals  # noqa

