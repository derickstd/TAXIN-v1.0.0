from django.core.management.base import BaseCommand
from django.utils import timezone
from clients.models import Client
from compliance.models import ComplianceObligation, ComplianceDeadline
import calendar


class Command(BaseCommand):
    help = 'Generate missing compliance deadlines for all clients with obligations'

    def handle(self, *args, **options):
        today = timezone.now().date()
        
        # If today is past the 15th, generate for next month; otherwise current month
        if today.day > 15:
            if today.month == 12:
                target_month = 1
                target_year = today.year + 1
            else:
                target_month = today.month + 1
                target_year = today.year
        else:
            target_month = today.month
            target_year = today.year
        
        # Period label is for the previous month
        if target_month == 1:
            period_month = 12
            period_year = target_year - 1
        else:
            period_month = target_month - 1
            period_year = target_year
        
        period_label = f"{calendar.month_name[period_month]} {period_year}"
        
        try:
            due_date = today.replace(year=target_year, month=target_month, day=15)
        except ValueError:
            import datetime
            due_date = datetime.date(target_year, target_month, 15)
        
        self.stdout.write(f"Generating deadlines for period: {period_label}")
        self.stdout.write(f"Due date: {due_date}")
        
        # Get all active obligations
        obligations = ComplianceObligation.objects.filter(is_active=True).select_related('client', 'service_type')
        
        created_count = 0
        skipped_count = 0
        
        for obligation in obligations:
            # Check if deadline already exists
            if ComplianceDeadline.objects.filter(obligation=obligation, period_label=period_label).exists():
                skipped_count += 1
                continue
            
            ComplianceDeadline.objects.create(
                obligation=obligation,
                period_label=period_label,
                due_date=due_date,
                status='upcoming'
            )
            created_count += 1
            self.stdout.write(f"  ✓ Created: {obligation.client.get_display_name()} - {obligation.service_type.name}")
        
        self.stdout.write(self.style.SUCCESS(f"\n✅ Created {created_count} compliance deadlines"))
        self.stdout.write(f"⏭️  Skipped {skipped_count} (already exist)")
