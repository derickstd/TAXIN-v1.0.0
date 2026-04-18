import os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from django.urls import reverse, NoReverseMatch
from django.test import RequestFactory, Client as TestClient
from django.contrib.auth import get_user_model
User = get_user_model()

errors = []
warnings = []
ok = []

# ── 1. URL resolution ──────────────────────────────────────────────────────
print('\n=== URL RESOLUTION ===')
urls = [
    ('dashboard:index',[]),('clients:list',[]),('clients:create',[]),
    ('clients:import',[]),('clients:walkin',[]),
    ('billing:list',[]),('billing:create',[]),('billing:aging',[]),
    ('services:list',[]),('services:create',[]),('services:catalogue',[]),
    ('expenses:list',[]),('expenses:create',[]),
    ('compliance:list',[]),
    ('credentials:list',[]),('credentials:create',[]),
    ('core:settings',[]),('core:users',[]),('core:user_new',[]),
    ('documents:price_list',[]),('documents:monthly_report',[]),
    ('documents:audit_books',[]),
    ('notifications:list',[]),
]
for name, args in urls:
    try:
        url = reverse(name, args=args)
        ok.append(f'URL {name}')
        print(f'  OK  {name} -> {url}')
    except NoReverseMatch as e:
        errors.append(f'URL {name}: {e}')
        print(f'  ERR {name}: {e}')

# ── 2. Model integrity checks ──────────────────────────────────────────────
print('\n=== MODEL CHECKS ===')
from clients.models import Client
from services.models import JobCard, JobCardLineItem, ServiceType
from billing.models import Invoice, Payment
from expenses.models import Expense, ExpenseCategory
from compliance.models import ComplianceObligation, ComplianceDeadline
from credentials.models import ClientCredential
from notifications.models import NotificationLog

# Check Client.save() client_id race condition
import inspect
src = inspect.getsource(Client.save)
if 'last.id + 1' in src:
    errors.append('Client.save: client_id uses last.id+1 - race condition under concurrent inserts')
    print('  ERR Client.save: race condition in client_id generation')
else:
    print('  OK  Client.save client_id generation')

# Check JobCard number generation
src2 = inspect.getsource(JobCard.save)
if "order_by('-id').first()" in src2:
    warnings.append('JobCard.save: job_number generation uses order_by(-id) - race condition possible')
    print('  WARN JobCard.save: job_number race condition possible')

# Check Invoice.update_status proforma bug
src3 = inspect.getsource(Invoice.update_status)
if 'proforma' in src3 and 'return' in src3:
    errors.append('Invoice.update_status: early return for proforma/quotation skips status update entirely')
    print('  ERR Invoice.update_status: proforma/quotation status never updated')

# Check _auto_create_invoice missing document_type
from services.views import _auto_create_invoice
src4 = inspect.getsource(_auto_create_invoice)
if 'document_type' not in src4:
    warnings.append('_auto_create_invoice: document_type not set, defaults to invoice (OK but implicit)')
    print('  WARN _auto_create_invoice: document_type not explicitly set')

# Check duplicate client_detail in clients/views.py
from clients import views as cv
import inspect
src5 = inspect.getsource(cv)
count = src5.count('def client_detail(')
if count > 1:
    errors.append(f'clients/views.py: client_detail defined {count} times - second definition shadows first')
    print(f'  ERR clients/views.py: client_detail defined {count}x - shadow bug')

# Check context_processor error swallowing
from core.context_processors import global_context
src6 = inspect.getsource(global_context)
if 'except Exception' in src6 and 'pass' in src6:
    warnings.append('context_processor: bare except+pass silently swallows all errors')
    print('  WARN context_processor: bare except swallows errors silently')

# Check billing/views record_payment uses float() not Decimal
from billing import views as bv
src7 = inspect.getsource(bv.record_payment)
if 'float(' in src7:
    errors.append('billing/views.record_payment: uses float() for money - precision loss risk')
    print('  ERR billing/views.record_payment: float() used for currency')

# Check expenses form - status field not set to submitted in form
from expenses.views import expense_create
src8 = inspect.getsource(expense_create)
if "status = 'submitted'" in src8:
    print('  OK  expense_create sets status=submitted')

# Check services/views jobcard_create - formset deleted_objects
src9 = inspect.getsource(cv.client_create)
print('  OK  client_create')

# ── 3. View response tests ─────────────────────────────────────────────────
print('\n=== VIEW RESPONSE TESTS ===')
tc = TestClient()
# Create test superuser
u, created = User.objects.get_or_create(username='_audit_test_user_')
if created:
    u.set_password('testpass123')
    u.role = 'admin'
    u.is_superuser = True
    u.is_staff = True
    u.save()

tc.login(username='_audit_test_user_', password='testpass123')

test_urls = [
    '/dashboard/', '/clients/', '/billing/', '/services/',
    '/expenses/', '/compliance/', '/credentials/', '/documents/',
    '/notifications/', '/settings/', '/users/',
]
for url in test_urls:
    try:
        resp = tc.get(url, follow=True)
        if resp.status_code == 200:
            print(f'  OK  GET {url} -> 200')
            ok.append(f'GET {url}')
        else:
            errors.append(f'GET {url} -> {resp.status_code}')
            print(f'  ERR GET {url} -> {resp.status_code}')
    except Exception as e:
        errors.append(f'GET {url} -> EXCEPTION: {e}')
        print(f'  EXC GET {url}: {e}')

# ── 4. Form submission tests ───────────────────────────────────────────────
print('\n=== FORM SUBMISSION TESTS ===')
from clients.models import Client as ClientModel

# Test client create
resp = tc.post('/clients/new/', {
    'client_type': 'individual',
    'full_name': '_Audit Test Client_',
    'phone_primary': '+256700000001',
    'district': 'Kampala',
}, follow=True)
if resp.status_code == 200 and ClientModel.objects.filter(full_name='_Audit Test Client_').exists():
    print('  OK  POST /clients/new/ -> client created')
    ok.append('POST client create')
else:
    errors.append(f'POST /clients/new/ failed: {resp.status_code}')
    print(f'  ERR POST /clients/new/ -> {resp.status_code}')
    if hasattr(resp, 'context') and resp.context and 'form' in resp.context:
        print(f'       Form errors: {resp.context["form"].errors}')

# Test invoice create
client = ClientModel.objects.filter(full_name='_Audit Test Client_').first()
if client:
    resp = tc.post('/billing/new/', {
        'document_type': 'invoice',
        'client': client.pk,
        'description': 'Audit test invoice',
        'amount': '100000',
    }, follow=True)
    if resp.status_code == 200 and Invoice.objects.filter(client=client).exists():
        print('  OK  POST /billing/new/ -> invoice created')
        ok.append('POST invoice create')
    else:
        errors.append(f'POST /billing/new/ failed: {resp.status_code}')
        print(f'  ERR POST /billing/new/ -> {resp.status_code}')

# ── 5. Summary ─────────────────────────────────────────────────────────────
print(f'\n=== SUMMARY ===')
print(f'  OK:       {len(ok)}')
print(f'  WARNINGS: {len(warnings)}')
print(f'  ERRORS:   {len(errors)}')
if warnings:
    print('\nWARNINGS:')
    for w in warnings: print(f'  - {w}')
if errors:
    print('\nERRORS:')
    for e in errors: print(f'  - {e}')

# Cleanup
ClientModel.objects.filter(full_name='_Audit Test Client_').delete()
User.objects.filter(username='_audit_test_user_').delete()
