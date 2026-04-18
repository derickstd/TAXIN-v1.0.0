"""
Taxman256 Production Server — Waitress (Windows compatible)
Run: python serve.py
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.core.management import call_command
print("Applying migrations...")
call_command('migrate', '--run-syncdb', verbosity=0)
print("Migrations complete.")

print("\n" + "="*55)
print("  TAXMAN256 Practice Management System")
print("  Server: http://0.0.0.0:8080")
print("  Login: admin / admin123")
print("="*55 + "\n")

from waitress import serve
from config.wsgi import application
serve(application, host='0.0.0.0', port=8080, threads=8)
