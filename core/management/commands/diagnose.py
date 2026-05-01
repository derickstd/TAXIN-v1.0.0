from django.core.management.base import BaseCommand
from clients.models import Client
from services.models import ServiceType, ClientServiceSubscription
from compliance.models import ComplianceObligation, ComplianceDeadline
from credentials.models import ClientCredential
import os


class Command(BaseCommand):
    help = 'Run comprehensive system diagnostics'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('TAXMAN256 SYSTEM DIAGNOSTICS'))
        self.stdout.write(self.style.SUCCESS('=' * 60))
        
        # Database counts
        self.stdout.write('\n📊 DATABASE STATUS:')
        self.stdout.write(f'  Clients: {Client.objects.count()}')
        self.stdout.write(f'  Service Types: {ServiceType.objects.count()}')
        self.stdout.write(f'  Service Subscriptions: {ClientServiceSubscription.objects.count()}')
        self.stdout.write(f'  Compliance Obligations: {ComplianceObligation.objects.count()}')
        self.stdout.write(f'  Compliance Deadlines: {ComplianceDeadline.objects.count()}')
        self.stdout.write(f'  Credentials: {ClientCredential.objects.count()}')
        
        # Recent clients
        self.stdout.write('\n👥 RECENT CLIENTS (Last 3):')
        clients = Client.objects.all().order_by('-id')[:3]
        for c in clients:
            subs = ClientServiceSubscription.objects.filter(client=c).count()
            obls = ComplianceObligation.objects.filter(client=c).count()
            deadlines = ComplianceDeadline.objects.filter(obligation__client=c).count()
            
            status = '✅' if (subs > 0 and obls > 0 and deadlines > 0) else '❌'
            self.stdout.write(f'\n  {status} {c.client_id} - {c.full_name}')
            self.stdout.write(f'     Subs: {subs} | Obls: {obls} | Deadlines: {deadlines}')
        
        # Template check
        self.stdout.write('\n📄 TEMPLATE CHECK:')
        template_path = 'templates/clients/client_onboarding.html'
        if os.path.exists(template_path):
            with open(template_path, 'r', encoding='utf-8') as f:
                content = f.read()
                if 'servicesContainer' in content:
                    self.stdout.write('  ✅ servicesContainer found in template')
                    if '<form method="post"' in content:
                        form_pos = content.find('<form method="post"')
                        services_pos = content.find('servicesContainer')
                        form_close = content.find('</form>', form_pos)
                        
                        if form_pos < services_pos < form_close:
                            self.stdout.write('  ✅ servicesContainer is INSIDE form tag')
                        else:
                            self.stdout.write('  ❌ servicesContainer is OUTSIDE form tag')
                else:
                    self.stdout.write('  ❌ servicesContainer NOT found')
        else:
            self.stdout.write('  ❌ Template file not found')
        
        # Backend test
        self.stdout.write('\n🔧 BACKEND TEST:')
        self.stdout.write('  Running test registration...')
        
        from core.models import User
        user = User.objects.first()
        
        try:
            test_client = Client.objects.create(
                full_name='DIAGNOSTIC TEST CLIENT',
                phone_primary='+256700999000',
                client_type='company',
                created_by=user
            )
            
            vat = ServiceType.objects.filter(name__icontains='VAT').first()
            if vat:
                sub = ClientServiceSubscription.objects.create(
                    client=test_client,
                    service_type=vat,
                    negotiated_price=100000,
                    is_active=True
                )
                
                obl = ComplianceObligation.objects.create(
                    client=test_client,
                    service_type=vat,
                    frequency='monthly',
                    is_active=True
                )
                
                self.stdout.write('  ✅ Backend is WORKING')
                
                # Cleanup
                test_client.delete()
            else:
                self.stdout.write('  ⚠️  No VAT service found')
        except Exception as e:
            self.stdout.write(f'  ❌ Backend error: {e}')
        
        # Summary
        total_clients = Client.objects.count()
        working_clients = Client.objects.filter(subscriptions__isnull=False).distinct().count()
        
        self.stdout.write('\n' + '=' * 60)
        self.stdout.write('📋 SUMMARY:')
        self.stdout.write(f'  Total Clients: {total_clients}')
        self.stdout.write(f'  Clients with Services: {working_clients}')
        self.stdout.write(f'  Success Rate: {(working_clients/total_clients*100) if total_clients > 0 else 0:.1f}%')
        
        if working_clients == 0 and total_clients > 0:
            self.stdout.write(self.style.ERROR('\n⚠️  NO CLIENTS HAVE SERVICES!'))
            self.stdout.write(self.style.WARNING('\n🔧 ACTION REQUIRED:'))
            self.stdout.write('  1. RESTART Django server (Ctrl+C, then runserver)')
            self.stdout.write('  2. CLEAR browser cache or use Incognito mode')
            self.stdout.write('  3. Register a NEW test client with services')
            self.stdout.write('  4. Check terminal for debug output')
        elif working_clients > 0:
            self.stdout.write(self.style.SUCCESS('\n✅ SYSTEM IS WORKING!'))
        
        self.stdout.write('=' * 60)
