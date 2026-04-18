from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()

SERVICE_TYPES = [
    {'name':'Income Tax Return','category':'ura_filing','default_price':300000,'deadline_type':'annual_dec31','is_recurring':True},
    {'name':'PAYE Return','category':'ura_filing','default_price':30000,'deadline_type':'monthly_15','is_recurring':True},
    {'name':'VAT Return','category':'ura_filing','default_price':30000,'deadline_type':'monthly_15','is_recurring':True},
    {'name':'Excise Duty Return','category':'ura_filing','default_price':30000,'deadline_type':'monthly_15','is_recurring':True},
    {'name':'Withholding Tax Return','category':'ura_filing','default_price':30000,'deadline_type':'monthly_15','is_recurring':True},
    {'name':'NSSF Monthly Filing','category':'nssf','default_price':20000,'deadline_type':'monthly_15','is_recurring':True},
    {'name':'URSB Company Registration','category':'ursb','default_price':500000,'deadline_type':'none','is_recurring':False},
    {'name':'URSB Business Registration','category':'ursb','default_price':150000,'deadline_type':'none','is_recurring':False},
    {'name':'URSB Annual Return','category':'ursb','default_price':100000,'deadline_type':'annual_ursb','is_recurring':True},
    {'name':'URA Assessment Generation','category':'ura_advisory','default_price':10000,'deadline_type':'none','is_recurring':False},
    {'name':'Passport Application','category':'immigration','default_price':50000,'deadline_type':'none','is_recurring':False},
    {'name':'Single Window Application (Customs Licence)','category':'customs','default_price':150000,'deadline_type':'none','is_recurring':False},
    {'name':'ASYCUDA Data Capture','category':'customs','default_price':20000,'deadline_type':'none','is_recurring':False},
    {'name':'Tax Advisory (Per Hour)','category':'advisory','default_price':50000,'deadline_type':'none','is_recurring':False},
    {'name':'Tax Investigation Support','category':'ura_advisory','default_price':500000,'deadline_type':'none','is_recurring':False},
    {'name':'Other (Custom)','category':'miscellaneous','default_price':0,'deadline_type':'none','is_recurring':False},
]

EXPENSE_CATEGORIES = [
    'Office Rent','Utilities (Electricity/Water)','Internet & Data',
    'Staff Salaries','Staff Transport/Fuel','URA Facilitation',
    'Client Transport','Professional Subscriptions','Printing & Stationery',
    'Bank Charges','Mobile Money Charges','Equipment & Software',
    'Marketing & Advertising','Staff Training & CPD',
    'Meals & Entertainment (Client)','Airtime & Communication','Miscellaneous / Other',
]

class Command(BaseCommand):
    help = 'Set up Taxman256 system with initial data'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Setting up Taxman256...'))
        self._setup_services()
        self._setup_expense_categories()
        self._setup_admin()
        self._setup_sample_data()
        self.stdout.write(self.style.SUCCESS('\n✅ Taxman256 setup complete! Login: admin / admin123'))

    def _setup_services(self):
        from services.models import ServiceType
        for st in SERVICE_TYPES:
            ServiceType.objects.update_or_create(name=st['name'], defaults=st)
        self.stdout.write(f'  ✓ {len(SERVICE_TYPES)} service types loaded')

    def _setup_expense_categories(self):
        from expenses.models import ExpenseCategory
        for name in EXPENSE_CATEGORIES:
            ExpenseCategory.objects.get_or_create(name=name)
        self.stdout.write(f'  ✓ {len(EXPENSE_CATEGORIES)} expense categories loaded')

    def _setup_admin(self):
        if not User.objects.filter(username='admin').exists():
            User.objects.create_superuser(
                username='admin', email='admin@taxman256.ug', password='admin123',
                first_name='System', last_name='Admin', role='admin',
                is_active_staff=True,
            )
            self.stdout.write('  ✓ Admin user created (admin / admin123)')
        # Create sample staff
        if not User.objects.filter(username='officer1').exists():
            User.objects.create_user(
                username='officer1', password='pass1234',
                first_name='Grace', last_name='Nakato', role='tax_officer',
                email='grace@taxman256.ug', is_active_staff=True,
            )
        if not User.objects.filter(username='manager1').exists():
            User.objects.create_user(
                username='manager1', password='pass1234',
                first_name='Samuel', last_name='Ssemakula', role='manager',
                email='samuel@taxman256.ug', is_active_staff=True,
                phone_whatsapp='+256785230670',
            )

    def _setup_sample_data(self):
        from clients.models import Client
        from services.models import ServiceType, JobCard, JobCardLineItem
        from billing.models import Invoice
        from expenses.models import Expense, ExpenseCategory
        import datetime

        officer = User.objects.filter(role='tax_officer').first()
        admin = User.objects.filter(role='admin').first()

        sample_clients = [
            {'full_name':'Kampala Traders Ltd','trading_name':'KT Ltd','client_type':'company','tin':'1001234567','phone_primary':'+256700100001','phone_whatsapp':'+256700100001','district':'Kampala'},
            {'full_name':'Sarah Namukasa','client_type':'individual','tin':'1009876543','phone_primary':'+256700200002','phone_whatsapp':'+256700200002','district':'Wakiso'},
            {'full_name':'Green Horizons NGO','client_type':'ngo','phone_primary':'+256700300003','district':'Kampala'},
            {'full_name':'Mega Imports Uganda','client_type':'company','tin':'1005555555','phone_primary':'+256700400004','phone_whatsapp':'+256700400004','district':'Jinja'},
            {'full_name':'Peter Okello','client_type':'individual','phone_primary':'+256700500005','district':'Gulu'},
        ]

        created_clients = []
        for c in sample_clients:
            obj, _ = Client.objects.get_or_create(
                phone_primary=c['phone_primary'],
                defaults={**c, 'assigned_officer': officer, 'created_by': admin, 'status':'active'}
            )
            created_clients.append(obj)

        today = datetime.date.today()
        vat = ServiceType.objects.get(name='VAT Return')
        paye = ServiceType.objects.get(name='PAYE Return')
        income_tax = ServiceType.objects.get(name='Income Tax Return')

        # Create a sample job card with multiple services
        if not JobCard.objects.filter(client=created_clients[0]).exists():
            job = JobCard.objects.create(
                client=created_clients[0], period_month=today.month-1 or 12,
                period_year=today.year, assigned_to=officer,
                status='pending_payment', created_by=admin, is_periodic=True,
                due_date=today + datetime.timedelta(days=7),
            )
            items = [
                JobCardLineItem(job_card=job, service_type=vat, default_price=30000, negotiated_price=30000, status='handled_not_paid', period_label='March 2025'),
                JobCardLineItem(job_card=job, service_type=paye, default_price=30000, negotiated_price=25000, status='handled_not_paid', period_label='March 2025'),
            ]
            JobCardLineItem.objects.bulk_create(items)
            job.update_total()
            Invoice.objects.create(
                client=created_clients[0], job_card=job,
                due_date=today + datetime.timedelta(days=14),
                subtotal=55000, vat_total=0, grand_total=55000,
                status='sent', created_by=admin,
            )

        # A paid job card
        if JobCard.objects.filter(client=created_clients[1]).count() == 0:
            job2 = JobCard.objects.create(
                client=created_clients[1], period_month=today.month, period_year=today.year,
                assigned_to=officer, status='completed', created_by=admin,
                due_date=today - datetime.timedelta(days=5),
                completed_at=timezone.now() - datetime.timedelta(days=2),
            )
            JobCardLineItem.objects.create(
                job_card=job2, service_type=income_tax, default_price=300000,
                negotiated_price=250000, status='handled_paid', period_label='FY2024'
            )
            job2.update_total()
            Invoice.objects.create(
                client=created_clients[1], job_card=job2,
                due_date=today - datetime.timedelta(days=5),
                subtotal=250000, vat_total=0, grand_total=250000,
                amount_paid=250000, status='paid', created_by=admin,
            )

        # Sample expense
        cat = ExpenseCategory.objects.first()
        if cat and not Expense.objects.filter(paid_by=officer).exists():
            Expense.objects.create(
                expense_date=today, category=cat,
                description='Internet bill for the month',
                amount=150000, paid_by=officer, payment_method='mobile_money',
                status='approved', created_by=officer, approved_by=admin,
            )

        self.stdout.write(f'  ✓ Sample data created ({len(created_clients)} clients, job cards, invoices, expenses)')
