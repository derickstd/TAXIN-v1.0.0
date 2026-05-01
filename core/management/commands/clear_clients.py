from django.core.management.base import BaseCommand
from clients.models import Client
from services.models import ClientServiceSubscription
from compliance.models import ComplianceObligation, ComplianceDeadline
from credentials.models import ClientCredential
from billing.models import Invoice, Payment
from services.models import JobCard


class Command(BaseCommand):
    help = 'Clear all clients and related data to start fresh'

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Confirm deletion of all clients',
        )

    def handle(self, *args, **options):
        if not options['confirm']:
            self.stdout.write(self.style.WARNING('⚠️  This will DELETE ALL clients and related data!'))
            self.stdout.write('Run with --confirm flag to proceed:')
            self.stdout.write('  python manage.py clear_clients --confirm')
            return
        
        # Count before deletion
        client_count = Client.objects.count()
        jobcard_count = JobCard.objects.count()
        invoice_count = Invoice.objects.count()
        payment_count = Payment.objects.count()
        obligation_count = ComplianceObligation.objects.count()
        deadline_count = ComplianceDeadline.objects.count()
        credential_count = ClientCredential.objects.count()
        subscription_count = ClientServiceSubscription.objects.count()
        
        self.stdout.write(f'\nDeleting:')
        self.stdout.write(f'  - {client_count} clients')
        self.stdout.write(f'  - {jobcard_count} job cards')
        self.stdout.write(f'  - {invoice_count} invoices')
        self.stdout.write(f'  - {payment_count} payments')
        self.stdout.write(f'  - {obligation_count} compliance obligations')
        self.stdout.write(f'  - {deadline_count} compliance deadlines')
        self.stdout.write(f'  - {credential_count} credentials')
        self.stdout.write(f'  - {subscription_count} service subscriptions')
        
        # Delete in correct order (related data first)
        Payment.objects.all().delete()
        Invoice.objects.all().delete()
        JobCard.objects.all().delete()
        ComplianceDeadline.objects.all().delete()
        ComplianceObligation.objects.all().delete()
        ClientCredential.objects.all().delete()
        ClientServiceSubscription.objects.all().delete()
        Client.objects.all().delete()
        
        self.stdout.write(self.style.SUCCESS('\n✅ All clients and related data cleared!'))
        self.stdout.write('You can now start fresh with new client registrations.')
