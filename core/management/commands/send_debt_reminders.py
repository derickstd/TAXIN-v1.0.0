"""
Send debt reminders to clients with outstanding invoices
Can be run manually or scheduled
"""
from django.core.management.base import BaseCommand
from core.email_utils import send_bulk_debt_reminders
from notifications.services import send_whatsapp_message
from clients.models import Client
from billing.models import Invoice


class Command(BaseCommand):
    help = 'Send debt reminders to clients with outstanding invoices'

    def handle(self, *args, **options):
        self.stdout.write('Sending debt reminders...')
        
        # Send email reminders
        email_count = send_bulk_debt_reminders()
        
        # Send WhatsApp reminders
        whatsapp_count = 0
        clients_with_debt = Client.objects.filter(total_outstanding__gt=0, status='active')
        
        for client in clients_with_debt:
            wa = client.get_whatsapp_number()
            if not wa:
                continue
            
            outstanding_invoices = Invoice.objects.filter(
                client=client
            ).exclude(status__in=['paid', 'written_off']).order_by('due_date')
            
            if not outstanding_invoices.exists():
                continue
            
            msg = f"Dear {client.get_display_name()},\n\n"
            msg += f"You have outstanding invoices totaling UGX {client.total_outstanding:,.0f}.\n\n"
            
            for inv in outstanding_invoices[:3]:  # Show first 3
                msg += f"• {inv.invoice_number}: UGX {inv.balance:,.0f} (Due: {inv.due_date})\n"
            
            if outstanding_invoices.count() > 3:
                msg += f"\n...and {outstanding_invoices.count() - 3} more.\n"
            
            msg += "\nPlease settle your account. Contact us for payment details.\n\nTaxman256"
            
            if send_whatsapp_message(wa, msg, client=client, msg_type='debt_reminder'):
                whatsapp_count += 1
        
        self.stdout.write(self.style.SUCCESS(
            f'✓ Sent {email_count} emails and {whatsapp_count} WhatsApp messages'
        ))
