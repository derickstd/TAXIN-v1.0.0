"""
Automated scheduled tasks for system maintenance and notifications
Run these tasks daily via cron job or task scheduler
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Sum, Q
from decimal import Decimal
from billing.models import Invoice
from clients.models import Client
from compliance.models import ComplianceDeadline
from notifications.models import NotificationLog
from notifications.services import send_whatsapp_message


class Command(BaseCommand):
    help = 'Run automated system maintenance tasks'

    def handle(self, *args, **options):
        self.stdout.write('Starting automated tasks...')
        
        # Task 1: Generate monthly compliance deadlines (1st of month)
        self.generate_monthly_compliance_deadlines()
        
        # Task 2: Update overdue invoices
        self.update_overdue_invoices()
        
        # Task 3: Update client statuses
        self.update_client_statuses()
        
        # Task 4: Send compliance reminders
        self.send_compliance_reminders()
        
        # Task 5: Generate recurring job cards
        self.generate_recurring_jobs()
        
        # Task 6: Clean up old notifications
        self.cleanup_old_notifications()
        
        self.stdout.write(self.style.SUCCESS('✓ All automated tasks completed'))

    def generate_monthly_compliance_deadlines(self):
        """Generate compliance deadlines for ALL clients (not just active) on 1st of month"""
        from compliance.models import ComplianceObligation, ComplianceDeadline
        from services.models import ServiceType
        import calendar
        
        today = timezone.now().date()
        
        # Only run on the 1st of each month
        if today.day != 1:
            return
        
        current_month = today.month
        current_year = today.year
        
        # Get previous month for period label
        if current_month == 1:
            prev_month = 12
            prev_year = current_year - 1
        else:
            prev_month = current_month - 1
            prev_year = current_year
        
        # Period label (e.g., "January 2026")
        period_label = f"{calendar.month_name[prev_month]} {prev_year}"
        
        # Due date is 15th of current month
        due_date = today.replace(day=15)
        
        # Get monthly tax services (PAYE, VAT, Excise Duty, NSSF)
        monthly_services = ServiceType.objects.filter(
            Q(name__icontains='PAYE') | 
            Q(name__icontains='VAT') |
            Q(name__icontains='Excise') |
            Q(name__icontains='NSSF') |
            Q(name__icontains='Withholding'),
            is_active=True
        )
        
        created_count = 0
        obligation_count = 0
        
        # Get ALL clients (not just active)
        all_clients = Client.objects.all().exclude(status='blacklisted')
        
        for client in all_clients:
            for service in monthly_services:
                # Create or get obligation for this client-service combination
                obligation, created = ComplianceObligation.objects.get_or_create(
                    client=client,
                    service_type=service,
                    defaults={
                        'frequency': 'monthly',
                        'is_active': True
                    }
                )
                
                if created:
                    obligation_count += 1
                
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
        
        # Also create annual deadlines (Income Tax - Dec 31)
        annual_services = ServiceType.objects.filter(
            Q(name__icontains='Income Tax') | Q(name__icontains='Annual Return'),
            is_active=True
        )
        
        annual_period = f"FY {current_year}"
        annual_due = timezone.datetime(current_year, 12, 31).date()
        
        for client in all_clients:
            for service in annual_services:
                obligation, created = ComplianceObligation.objects.get_or_create(
                    client=client,
                    service_type=service,
                    defaults={
                        'frequency': 'annual',
                        'is_active': True
                    }
                )
                
                if created:
                    obligation_count += 1
                
                deadline_exists = ComplianceDeadline.objects.filter(
                    obligation=obligation,
                    period_label=annual_period
                ).exists()
                
                if not deadline_exists and current_month == 1:  # Create annual deadlines in January
                    ComplianceDeadline.objects.create(
                        obligation=obligation,
                        period_label=annual_period,
                        due_date=annual_due,
                        status='upcoming'
                    )
                    created_count += 1
        
        self.stdout.write(f'  → {obligation_count} new obligations + {created_count} compliance deadlines generated for ALL clients')

    def update_overdue_invoices(self):
        """Mark invoices as overdue when due date passes"""
        today = timezone.now().date()
        updated = Invoice.objects.filter(
            status__in=['sent', 'partially_paid'],
            due_date__lt=today
        ).update(status='overdue')
        
        self.stdout.write(f'  → {updated} invoices marked as overdue')

    def update_client_statuses(self):
        """Update client statuses based on activity and debt"""
        today = timezone.now().date()
        
        # Suspend clients with 60+ days overdue debt
        suspended_count = 0
        for client in Client.objects.filter(status='active', total_outstanding__gt=0):
            overdue_60 = Invoice.objects.filter(
                client=client,
                status='overdue',
                due_date__lt=today - timezone.timedelta(days=60)
            ).exists()
            
            if overdue_60:
                client.status = 'suspended'
                client.save(update_fields=['status'])
                suspended_count += 1
                
                # Send suspension notice
                msg = f"⚠️ Your account has been suspended due to overdue payments. Outstanding: UGX {client.total_outstanding:,.0f}. Please contact us immediately."
                send_whatsapp_message(client.get_whatsapp_number(), msg)
        
        # Mark dormant clients (no activity in 6 months)
        dormant_count = 0
        for client in Client.objects.filter(status='active'):
            if client.last_transaction_date:
                days_inactive = (today - client.last_transaction_date).days
                if days_inactive > 180:
                    client.status = 'dormant'
                    client.save(update_fields=['status'])
                    dormant_count += 1
        
        # Reactivate clients who paid off debt
        reactivated = Client.objects.filter(
            status='suspended',
            total_outstanding=0
        ).update(status='active')
        
        self.stdout.write(f'  → {suspended_count} clients suspended, {dormant_count} marked dormant, {reactivated} reactivated')

    def send_compliance_reminders(self):
        """Send reminders for upcoming compliance deadlines to ALL clients via WhatsApp and Email (15 days before)"""
        from core.email_utils import send_bulk_compliance_reminders
        
        today = timezone.now().date()
        upcoming_15days = today + timezone.timedelta(days=15)
        upcoming_7days = today + timezone.timedelta(days=7)
        upcoming_3days = today + timezone.timedelta(days=3)
        
        # Send reminders at 15 days, 7 days, and 3 days before deadline
        reminder_dates = [upcoming_15days, upcoming_7days, upcoming_3days]
        
        whatsapp_sent = 0
        for reminder_date in reminder_dates:
            deadlines = ComplianceDeadline.objects.filter(
                due_date=reminder_date,
                status='upcoming'
            ).select_related('obligation__client', 'obligation__service_type')
            
            for deadline in deadlines:
                days_left = (deadline.due_date - today).days
                client = deadline.obligation.client
                service_name = deadline.obligation.service_type.name
                
                # Skip blacklisted clients
                if client.status == 'blacklisted':
                    continue
                
                # Customize message based on urgency
                if days_left <= 3:
                    urgency = "⚠️ URGENT"
                elif days_left <= 7:
                    urgency = "🔔 Important"
                else:
                    urgency = "📅 Reminder"
                
                msg = f"{urgency}: {service_name} for {deadline.period_label} is due in {days_left} days ({deadline.due_date.strftime('%d %b %Y')}). Please prepare your documents."
                
                if send_whatsapp_message(client.get_whatsapp_number(), msg):
                    whatsapp_sent += 1
        
        # Send email reminders (15 days before) to ALL clients
        email_sent = send_bulk_compliance_reminders(days_ahead=15)
        
        self.stdout.write(f'  → {whatsapp_sent} WhatsApp + {email_sent} email compliance reminders sent to ALL clients')

    def generate_recurring_jobs(self):
        """Auto-generate job cards for recurring services 15 days before deadline"""
        from services.models import ClientServiceSubscription, JobCard, JobCardLineItem
        from core.models import User
        import calendar
        
        today = timezone.now().date()
        
        # Calculate which month's services are due in 15 days
        deadline_date = today + timezone.timedelta(days=15)
        
        # For monthly services with 15th deadline, generate jobs 15 days before
        # If today is March 1st, deadline_date is March 16th
        # We want to create jobs for February (due March 15th)
        
        # Determine the period we're creating jobs for
        if deadline_date.day >= 15:
            # We're within 15 days of next month's 15th
            # Create jobs for current month
            target_month = today.month
            target_year = today.year
        else:
            # We're within 15 days of current month's 15th
            # Create jobs for previous month
            if today.month == 1:
                target_month = 12
                target_year = today.year - 1
            else:
                target_month = today.month - 1
                target_year = today.year
        
        # Calculate the actual due date (15th of next month after target period)
        if target_month == 12:
            due_month = 1
            due_year = target_year + 1
        else:
            due_month = target_month + 1
            due_year = target_year
        
        due_date = timezone.datetime(due_year, due_month, 15).date()
        
        # Only proceed if we're within 15 days of the deadline
        days_to_deadline = (due_date - today).days
        if days_to_deadline > 15 or days_to_deadline < 0:
            self.stdout.write(f'  → Not within 15-day window for job generation (next deadline: {due_date}, {days_to_deadline} days away)')
            return
        
        period_label = f"{calendar.month_name[target_month]} {target_year}"
        
        created_count = 0
        subscriptions = ClientServiceSubscription.objects.filter(
            is_active=True,
            service_type__is_recurring=True
        ).select_related('client', 'service_type', 'client__assigned_officer')
        
        for sub in subscriptions:
            # Check if job already exists for this period
            existing = JobCard.objects.filter(
                client=sub.client,
                period_month=target_month,
                period_year=target_year,
                line_items__service_type=sub.service_type
            ).exists()
            
            if existing:
                continue
            
            # Create job card
            officer = sub.client.assigned_officer or User.objects.filter(
                role='tax_officer', is_active=True
            ).first()
            
            if not officer:
                continue
            
            job = JobCard.objects.create(
                client=sub.client,
                period_month=target_month,
                period_year=target_year,
                assigned_to=officer,
                status='open',
                is_periodic=True,
                due_date=due_date,
                created_by=officer
            )
            
            # Add line item
            vat_amount = sub.negotiated_price * Decimal('0.18') if sub.service_type.vat_applicable else Decimal('0')
            JobCardLineItem.objects.create(
                job_card=job,
                service_type=sub.service_type,
                default_price=sub.service_type.default_price,
                negotiated_price=sub.negotiated_price,
                vat_amount=vat_amount,
                status='not_handled',
                period_label=period_label
            )
            
            job.update_total()
            
            # Auto-create invoice
            from billing.models import Invoice
            invoice_due = due_date  # Invoice due same as service deadline
            Invoice.objects.create(
                client=sub.client,
                job_card=job,
                due_date=invoice_due,
                subtotal=sub.negotiated_price,
                vat_total=vat_amount,
                grand_total=sub.negotiated_price + vat_amount,
                status='draft',
                created_by=officer
            )
            
            created_count += 1
            
            # Send notification to client
            msg = f"📋 New job card created for {sub.service_type.name} - {period_label}. Due: {due_date.strftime('%d %b %Y')}. Please prepare your documents."
            send_whatsapp_message(sub.client.get_whatsapp_number(), msg)
        
        self.stdout.write(f'  → {created_count} recurring job cards auto-generated for {period_label} (due {due_date})')

    def cleanup_old_notifications(self):
        """Delete notification logs older than 90 days"""
        cutoff = timezone.now() - timezone.timedelta(days=90)
        deleted, _ = NotificationLog.objects.filter(created_at__lt=cutoff).delete()
        self.stdout.write(f'  → {deleted} old notifications cleaned up')
