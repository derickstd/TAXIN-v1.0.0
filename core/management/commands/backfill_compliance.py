"""
Management command to backfill compliance obligations for all existing clients
Run this once to create obligations for all clients in the system
"""
from django.core.management.base import BaseCommand
from django.db.models import Q
from clients.models import Client
from services.models import ServiceType
from compliance.models import ComplianceObligation, ComplianceDeadline
from django.utils import timezone
import calendar


class Command(BaseCommand):
    help = 'Backfill compliance obligations and deadlines for all existing clients'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be created without actually creating',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))
        
        self.stdout.write('Starting compliance backfill for all clients...')
        
        # Get all clients except blacklisted
        all_clients = Client.objects.all().exclude(status='blacklisted')
        total_clients = all_clients.count()
        
        self.stdout.write(f'Found {total_clients} clients to process')
        
        # Get monthly tax services
        monthly_services = ServiceType.objects.filter(
            Q(name__icontains='PAYE') | 
            Q(name__icontains='VAT') |
            Q(name__icontains='Excise') |
            Q(name__icontains='NSSF') |
            Q(name__icontains='Withholding'),
            is_active=True
        )
        
        self.stdout.write(f'Found {monthly_services.count()} monthly services')
        
        # Get annual services
        annual_services = ServiceType.objects.filter(
            Q(name__icontains='Income Tax') | Q(name__icontains='Annual Return'),
            is_active=True
        )
        
        self.stdout.write(f'Found {annual_services.count()} annual services')
        
        obligations_created = 0
        deadlines_created = 0
        
        today = timezone.now().date()
        current_month = today.month
        current_year = today.year
        
        # Calculate current period
        if current_month == 1:
            prev_month = 12
            prev_year = current_year - 1
        else:
            prev_month = current_month - 1
            prev_year = current_year
        
        period_label = f"{calendar.month_name[prev_month]} {prev_year}"
        due_date = today.replace(day=15) if today.day < 15 else today.replace(month=current_month+1 if current_month < 12 else 1, day=15, year=current_year if current_month < 12 else current_year+1)
        
        self.stdout.write(f'Creating obligations and deadlines for period: {period_label} (due {due_date})')
        
        # Process each client
        for idx, client in enumerate(all_clients, 1):
            if idx % 10 == 0:
                self.stdout.write(f'  Processing client {idx}/{total_clients}...')
            
            # Create monthly obligations
            for service in monthly_services:
                if not dry_run:
                    obligation, created = ComplianceObligation.objects.get_or_create(
                        client=client,
                        service_type=service,
                        defaults={
                            'frequency': 'monthly',
                            'is_active': True
                        }
                    )
                    
                    if created:
                        obligations_created += 1
                    
                    # Create deadline for current period
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
                        deadlines_created += 1
                else:
                    # Dry run - just count
                    exists = ComplianceObligation.objects.filter(
                        client=client,
                        service_type=service
                    ).exists()
                    if not exists:
                        obligations_created += 1
                        deadlines_created += 1
            
            # Create annual obligations
            for service in annual_services:
                annual_period = f"FY {current_year}"
                annual_due = timezone.datetime(current_year, 12, 31).date()
                
                if not dry_run:
                    obligation, created = ComplianceObligation.objects.get_or_create(
                        client=client,
                        service_type=service,
                        defaults={
                            'frequency': 'annual',
                            'is_active': True
                        }
                    )
                    
                    if created:
                        obligations_created += 1
                    
                    # Create deadline for current year
                    deadline_exists = ComplianceDeadline.objects.filter(
                        obligation=obligation,
                        period_label=annual_period
                    ).exists()
                    
                    if not deadline_exists:
                        ComplianceDeadline.objects.create(
                            obligation=obligation,
                            period_label=annual_period,
                            due_date=annual_due,
                            status='upcoming'
                        )
                        deadlines_created += 1
                else:
                    # Dry run - just count
                    exists = ComplianceObligation.objects.filter(
                        client=client,
                        service_type=service
                    ).exists()
                    if not exists:
                        obligations_created += 1
                        deadlines_created += 1
        
        # Summary
        self.stdout.write(self.style.SUCCESS('✓ Backfill complete!'))
        self.stdout.write(f'  → {obligations_created} compliance obligations {"would be" if dry_run else ""} created')
        self.stdout.write(f'  → {deadlines_created} compliance deadlines {"would be" if dry_run else ""} created')
        self.stdout.write(f'  → {total_clients} clients processed')
        
        if dry_run:
            self.stdout.write(self.style.WARNING('This was a DRY RUN - run without --dry-run to apply changes'))
        else:
            self.stdout.write(self.style.SUCCESS('All clients now have compliance obligations and deadlines!'))
