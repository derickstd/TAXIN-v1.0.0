from django.core.management.base import BaseCommand
from clients.models import Client
from services.models import ServiceType, ClientServiceSubscription
from compliance.models import ComplianceObligation, ComplianceDeadline
from core.models import User


class Command(BaseCommand):
    help = 'Test client registration with services and compliance'

    def handle(self, *args, **options):
        user = User.objects.first()
        
        # Create test client
        client = Client.objects.create(
            full_name='TEST CLIENT FOR VERIFICATION',
            phone_primary='+256700999888',
            client_type='company',
            created_by=user
        )
        self.stdout.write(f'✓ Client created: {client.client_id}')
        
        # Get VAT service
        vat_service = ServiceType.objects.filter(name__icontains='VAT').first()
        if not vat_service:
            self.stdout.write(self.style.ERROR('✗ No VAT service found'))
            return
        
        # Create subscription
        subscription = ClientServiceSubscription.objects.create(
            client=client,
            service_type=vat_service,
            negotiated_price=150000,
            is_active=True
        )
        self.stdout.write(f'✓ Subscription created: {subscription.id}')
        
        # Create obligation
        obligation = ComplianceObligation.objects.create(
            client=client,
            service_type=vat_service,
            frequency='monthly',
            is_active=True
        )
        self.stdout.write(f'✓ Obligation created: {obligation.id}')
        
        # Generate compliance deadline
        from clients.views import _generate_client_compliance_deadlines
        count = _generate_client_compliance_deadlines(client)
        self.stdout.write(f'✓ Compliance deadlines generated: {count}')
        
        # Verify
        subs = ClientServiceSubscription.objects.filter(client=client).count()
        obls = ComplianceObligation.objects.filter(client=client).count()
        deadlines = ComplianceDeadline.objects.filter(obligation__client=client).count()
        
        self.stdout.write(self.style.SUCCESS(f'\n=== VERIFICATION ==='))
        self.stdout.write(f'Subscriptions: {subs}')
        self.stdout.write(f'Obligations: {obls}')
        self.stdout.write(f'Deadlines: {deadlines}')
        
        if subs > 0 and obls > 0 and deadlines > 0:
            self.stdout.write(self.style.SUCCESS('\n✅ ALL SYSTEMS WORKING!'))
        else:
            self.stdout.write(self.style.ERROR('\n✗ SOMETHING FAILED'))
