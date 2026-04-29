from django.apps import AppConfig

class Config(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'services'
    
    def ready(self):
        import services.signals
