from django.core.management.base import BaseCommand
from clients.models import Client
from services.models import ClientServiceSubscription
from compliance.models import ComplianceObligation, ComplianceDeadline


class Command(BaseCommand):
    help = 'Check latest clients and their services/compliance status'

    def handle(self, *args, **options):
        clients = Client.objects.all().order_by('-id')[:5]
        
        self.stdout.write(self.style.SUCCESS('=== LATEST CLIENTS CHECK ===\n'))
        
        for c in clients:
            subs = ClientServiceSubscription.objects.filter(client=c).count()
            obls = ComplianceObligation.objects.filter(client=c).count()
            deadlines = ComplianceDeadline.objects.filter(obligation__client=c).count()
            
            status = '✅' if (subs > 0 and obls > 0 and deadlines > 0) else '❌'
            
            self.stdout.write(f'\n{status} {c.client_id} - {c.full_name}')
            self.stdout.write(f'   Subscriptions: {subs}')
            self.stdout.write(f'   Obligations: {obls}')
            self.stdout.write(f'   Deadlines: {deadlines}')
        
        # Summary
        total = Client.objects.count()
        with_services = Client.objects.filter(subscriptions__isnull=False).distinct().count()
        with_compliance = Client.objects.filter(obligations__isnull=False).distinct().count()
        
        self.stdout.write(self.style.SUCCESS(f'\n=== SUMMARY ==='))
        self.stdout.write(f'Total Clients: {total}')
        self.stdout.write(f'With Services: {with_services}')
        self.stdout.write(f'With Compliance: {with_compliance}')
