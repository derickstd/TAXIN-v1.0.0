from django.contrib import admin
from .models import ClientCredential, CredentialAccessLog
admin.site.register(ClientCredential)
admin.site.register(CredentialAccessLog)
