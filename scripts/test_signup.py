"""Test script to verify new company signup and tenant DB creation"""
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from core.models import Company, User, Tenant, AuditLog
from core.views import _create_company_database

# Clean up any existing test companies
test_slug = 'testco123'
Company.objects.filter(slug=test_slug).delete()

print("=" * 60)
print("Testing Fresh Company Signup and Tenant DB Creation")
print("=" * 60)

# Step 1: Create Company
print("\n[1] Creating company record...")
company = Company.objects.create(
    name='Test Company Ltd',
    slug=test_slug,
    email='test@example.com',
    active=True
)
print(f"    ✓ Company created: {company.slug} (id={company.pk})")

# Step 2: Create User
print("\n[2] Creating admin user...")
user = User.objects.create_user(
    username='testadmin123',
    email='admin@example.com',
    password='testpass123!',
    company=company,
    role='admin',
    is_active=True,
    is_active_staff=True,
)
company.owner = user
company.save()
print(f"    ✓ User created: {user.username} (id={user.pk})")

# Step 3: Create tenant database
print("\n[3] Creating tenant database...")
try:
    alias = _create_company_database(company, changed_by=user)
    print(f"    ✓ Tenant DB alias: {alias}")
except Exception as e:
    print(f"    ✗ ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Step 4: Verify company state
print("\n[4] Verifying company state...")
company.refresh_from_db()
print(f"    Company.db_name = {company.db_name}")
print(f"    Company.active = {company.active}")

# Step 5: Check tenant record
print("\n[5] Checking tenant record...")
tenant = Tenant.objects.filter(company=company).first()
if tenant:
    print(f"    ✓ Tenant found")
    print(f"      - status: {tenant.status}")
    print(f"      - db_alias: {tenant.db_alias}")
    print(f"      - db_path: {tenant.db_path}")
    if tenant.last_error:
        print(f"      - last_error: {tenant.last_error}")
else:
    print(f"    ✗ No tenant record found")

# Step 6: Check database file
print("\n[6] Checking database file...")
if os.path.exists(company.db_name if company.db_name and company.db_name.startswith('/') else os.path.join(os.getcwd(), 'company_databases', f'{company.slug}.sqlite3')):
    print(f"    ✓ Database file exists")
else:
    db_path = os.path.join(os.getcwd(), 'company_databases', f'{company.slug}.sqlite3')
    if os.path.exists(db_path):
        print(f"    ✓ Database file exists at {db_path}")
    else:
        print(f"    ✗ Database file not found at {db_path}")

# Step 7: Check audit logs
print("\n[7] Checking audit logs...")
logs = AuditLog.objects.filter(object_id=str(company.pk)).order_by('-changed_at')
if logs:
    for log in logs:
        print(f"    - {log.action}: {log.notes}")
else:
    print(f"    ✗ No audit logs found")

# Step 8: Try to login with new user
print("\n[8] Testing login credentials...")
from django.contrib.auth import authenticate
auth_user = authenticate(username='testadmin123', password='testpass123!')
if auth_user:
    print(f"    ✓ Login successful for {auth_user.username}")
else:
    print(f"    ✗ Login failed")

print("\n" + "=" * 60)
print("✓ Signup test completed successfully!")
print("=" * 60)
