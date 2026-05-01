"""
Generate monthly compliance deadlines for all active clients
Can be run manually or scheduled for 1st of each month
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Q
from clients.models import Client
from compliance.models import ComplianceObligation, ComplianceDeadline
from services.models import ServiceType
import calendar


class Command(BaseCommand):
    help = 'Generate monthly compliance deadlines for all active clients'

    def add_arguments(self, parser):
        parser.add_argument(
            '--month',
            type=int,
            help='Month number (1-12). Defaults to previous month.',
        )
        parser.add_argument(
            '--year',
            type=int,
            help='Year (e.g., 2026). Defaults to current year.',
        )

    def handle(self, *args, **options):
        today = timezone.now().date()
        
        # Determine which month to generate deadlines for
        if options['month'] and options['year']:
            target_month = options['month']
            target_year = options['year']
        else:
            # Default: previous month
            if today.month == 1:
                target_month = 12
                target_year = today.year - 1
            else:
                target_month = today.month - 1
                target_year = today.year
        
        # Period label (e.g., "January 2026")
        period_label = f"{calendar.month_name[target_month]} {target_year}"
        
        # Due date is 15th of the month following the target month
        if target_month == 12:
            due_month = 1
            due_year = target_year + 1
        else:
            due_month = target_month + 1
            due_year = target_year
        
        due_date = timezone.datetime(due_year, due_month, 15).date()
        
        self.stdout.write(f'Generating compliance deadlines for {period_label}...')
        self.stdout.write(f'Due date: {due_date}')
        
        # Get monthly tax services (PAYE, VAT, Excise Duty, NSSF)
        # Try exact matches first, then partial matches
        monthly_services = ServiceType.objects.filter(
            Q(name__iexact='PAYE') | 
            Q(name__iexact='VAT Return') | Q(name__iexact='VAT') |
            Q(name__iexact='Excise Duty') | Q(name__iexact='Excise') |
            Q(name__iexact='NSSF'),
            is_active=True
        )
        
        if not monthly_services.exists():
            self.stdout.write(self.style.WARNING('No monthly tax services found. Please create service types for: PAYE, VAT Return, Excise Duty, NSSF'))
            return
        
        created_count = 0
        skipped_count = 0
        
        # Get all active clients
        active_clients = Client.objects.filter(status='active')
        
        self.stdout.write(f'Processing {active_clients.count()} active clients...')
        
        for client in active_clients:
            for service in monthly_services:
                # Get or create obligation for this client-service combination
                obligation, created = ComplianceObligation.objects.get_or_create(
                    client=client,
                    service_type=service,
                    defaults={
                        'frequency': 'monthly',
                        'is_active': True
                    }
                )
                
                # Check if deadline already exists for this period
                deadline_exists = ComplianceDeadline.objects.filter(
                    obligation=obligation,
                    period_label=period_label
                ).exists()
                
                if not deadline_exists:
                    ComplianceDeadline.objects.create(
                        obligation=obligation,
                        period_label=period_label,
                        due_date=due_date,
                        status='upcoming'
                    )
                    created_count += 1
                else:
                    skipped_count += 1
        
        self.stdout.write(self.style.SUCCESS(
            f'✓ Generated {created_count} compliance deadlines'
        ))
        
        if skipped_count > 0:
            self.stdout.write(f'  → {skipped_count} deadlines already existed (skipped)')
        
        # Show breakdown by service
        self.stdout.write('\nBreakdown by service:')
        for service in monthly_services:
            count = ComplianceDeadline.objects.filter(
                obligation__service_type=service,
                period_label=period_label
            ).count()
            self.stdout.write(f'  • {service.name}: {count} deadlines')
