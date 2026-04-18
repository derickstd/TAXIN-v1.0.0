from django.db import models
from django.conf import settings
from cryptography.fernet import Fernet
from clients.models import Client
from core.models import User

def get_fernet():
    return Fernet(settings.CREDENTIAL_FERNET_KEY.encode())

def encrypt_value(val):
    if not val: return ''
    return get_fernet().encrypt(val.encode()).decode()

def decrypt_value(val):
    if not val: return ''
    try: return get_fernet().decrypt(val.encode()).decode()
    except Exception: return '[Decryption Error]'

class ClientCredential(models.Model):
    CRED_TYPE = [
        ('ura_etax','URA e-Tax'),('nssf','NSSF Portal'),('ursb','URSB Portal'),
        ('bank','Bank'),('mobile_money','Mobile Money'),('customs','Customs/ASYCUDA'),('custom','Custom'),
    ]
    STATUS = [('pending','Pending Setup'),('active','Active'),('needs_reset','Needs Reset'),('archived','Archived')]

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='credentials')
    credential_type = models.CharField(max_length=20, choices=CRED_TYPE)
    label = models.CharField(max_length=200)
    username_encrypted = models.TextField(blank=True)
    password_encrypted = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default='pending')
    expiry_date = models.DateField(null=True, blank=True)
    notes_encrypted = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_credentials')
    last_accessed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='accessed_credentials')
    last_accessed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def set_username(self, val): self.username_encrypted = encrypt_value(val)
    def set_password(self, val): self.password_encrypted = encrypt_value(val)
    def set_notes(self, val): self.notes_encrypted = encrypt_value(val)
    def get_username(self): return decrypt_value(self.username_encrypted)
    def get_password(self): return decrypt_value(self.password_encrypted)
    def get_notes(self): return decrypt_value(self.notes_encrypted)

    def __str__(self):
        return f"{self.client} — {self.label}"

class CredentialAccessLog(models.Model):
    credential = models.ForeignKey(ClientCredential, on_delete=models.CASCADE, related_name='access_logs')
    accessed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    accessed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-accessed_at']
