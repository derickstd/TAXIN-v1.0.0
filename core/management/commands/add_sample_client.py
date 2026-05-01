from django.core.management.base import BaseCommand
from clients.models import Client
from services.models import ServiceType, ClientServiceSubscription
from compliance.models import ComplianceObligation, ComplianceDeadline
from core.models import User
from django.utils import timezone
import calendar


class Command(BaseCommand):
    help = 'Add a sample client with VAT obligation and compliance deadline'

    def handle(self, *args, **options):
        user = User.objects.first()
        
        # Create client
        client = Client.objects.create(
            full_name='TEST CLIENT WITH VAT',
            phone_primary='+256700999999',
            phone_whatsapp='+256700999999',
            email='testclient@example.com',
            tin='1009999999',
            district='Kampala',
            client_type='company',
            assigned_officer=user,
            created_by=user
        )
        
        # Get VAT service
        vat_service = ServiceType.objects.filter(name__icontains='VAT').first()
        
        # Create service subscription
        ClientServiceSubscription.objects.create(
            client=client,
            service_type=vat_service,
            negotiated_price=150000,
            is_active=True
        )
        
        # Create obligation
        obligation = ComplianceObligation.objects.create(
            client=client,
            service_type=vat_service,
            frequency='monthly',
            is_active=True
        )
        
        # Create compliance deadline
        today = timezone.now().date()
        if today.day > 15:
            target_month = today.month + 1 if today.month < 12 else 1
            target_year = today.year if today.month < 12 else today.year + 1
        else:
            target_month = today.month
            target_year = today.year
        
        if target_month == 1:
            period_month = 12
            period_year = target_year - 1
        else:
            period_month = target_month - 1
            period_year = target_year
        
        period_label = f"{calendar.month_name[period_month]} {period_year}"
        due_date = today.replace(year=target_year, month=target_month, day=15)
        
        ComplianceDeadline.objects.create(
            obligation=obligation,
            period_label=period_label,
            due_date=due_date,
            status='upcoming'
        )
        
        self.stdout.write(self.style.SUCCESS(f'✅ Created client: {client.client_id} - {client.get_display_name()}'))
        self.stdout.write(f'   Service: {vat_service.name}')
        self.stdout.write(f'   Compliance deadline: {period_label} (due {due_date})')
