from django.core.management.base import BaseCommand
from django.db.models import Sum
from clients.models import Client
from billing.models import Invoice
from decimal import Decimal


class Command(BaseCommand):
    help = 'Update outstanding balance for all clients'

    def handle(self, *args, **options):
        clients = Client.objects.all()
        updated = 0
        
        for client in clients:
            # Calculate outstanding from unpaid invoices
            out = Invoice.objects.filter(client=client).exclude(
                status__in=['paid', 'written_off']
            ).aggregate(s=Sum('grand_total'))['s'] or Decimal('0')
            
            # Calculate total paid
            paid_sum = Invoice.objects.filter(client=client).aggregate(
                s=Sum('amount_paid')
            )['s'] or Decimal('0')
            
            # Calculate balance
            balance = max(Decimal('0'), out - paid_sum)
            
            # Update if changed
            if client.total_outstanding != balance:
                client.total_outstanding = balance
                client.save(update_fields=['total_outstanding'])
                updated += 1
                self.stdout.write(f'  Updated {client.client_id}: UGX {balance:,.0f}')
        
        self.stdout.write(self.style.SUCCESS(f'\n✅ Updated {updated} client(s) outstanding balance'))
