from django.contrib import admin
from .models import NotificationLog, MessageThread, Message

admin.site.register(NotificationLog)
admin.site.register(MessageThread)
admin.site.register(Message)
