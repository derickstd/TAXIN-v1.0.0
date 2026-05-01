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
        """Generate compliance deadlines for all clients with active obligations on 1st of month"""
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
            Q(name__iexact='PAYE') | 
            Q(name__iexact='VAT Return') | Q(name__iexact='VAT') |
            Q(name__iexact='Excise Duty') | Q(name__iexact='Excise') |
            Q(name__iexact='NSSF'),
            is_active=True
        )
        
        created_count = 0
        
        # Get all active clients
        active_clients = Client.objects.filter(status='active')
        
        for client in active_clients:
            for service in monthly_services:
                # Check if client has an obligation for this service
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
        
        self.stdout.write(f'  → {created_count} monthly compliance deadlines generated')

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
        """Send reminders for upcoming compliance deadlines via WhatsApp and Email"""
        from core.email_utils import send_bulk_compliance_reminders
        
        today = timezone.now().date()
        upcoming = today + timezone.timedelta(days=7)
        
        deadlines = ComplianceDeadline.objects.filter(
            due_date__gte=today,
            due_date__lte=upcoming,
            status='upcoming'
        ).select_related('obligation__client', 'obligation__service_type')
        
        whatsapp_sent = 0
        for deadline in deadlines:
            days_left = (deadline.due_date - today).days
            client = deadline.obligation.client
            service_name = deadline.obligation.service_type.name
            msg = f"📅 Reminder: {service_name} for {deadline.period_label} is due in {days_left} days ({deadline.due_date}). Please prepare your documents."
            
            if send_whatsapp_message(client.get_whatsapp_number(), msg):
                whatsapp_sent += 1
        
        # Send email reminders
        email_sent = send_bulk_compliance_reminders()
        
        self.stdout.write(f'  → {whatsapp_sent} WhatsApp + {email_sent} email compliance reminders sent')

    def generate_recurring_jobs(self):
        """Auto-generate job cards for recurring services"""
        from services.models import ClientServiceSubscription, JobCard, JobCardLineItem
        from core.models import User
        
        today = timezone.now()
        current_month = today.month
        current_year = today.year
        
        # Only run on the 1st of each month
        if today.day != 1:
            return
        
        created_count = 0
        subscriptions = ClientServiceSubscription.objects.filter(
            is_active=True,
            service_type__is_recurring=True
        ).select_related('client', 'service_type')
        
        for sub in subscriptions:
            # Check if job already exists for this period
            existing = JobCard.objects.filter(
                client=sub.client,
                period_month=current_month,
                period_year=current_year,
                line_items__service_type=sub.service_type
            ).exists()
            
            if existing:
                continue
            
            # Create job card
            officer = sub.client.assigned_officer or User.objects.filter(
                role='tax_officer', is_active=True
            ).first()
            
            job = JobCard.objects.create(
                client=sub.client,
                period_month=current_month,
                period_year=current_year,
                assigned_to=officer,
                status='open',
                is_periodic=True,
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
                period_label=job.get_period_label()
            )
            
            job.update_total()
            
            # Auto-create invoice
            from billing.models import Invoice
            due_date = today.date() + timezone.timedelta(days=14)
            Invoice.objects.create(
                client=sub.client,
                job_card=job,
                due_date=due_date,
                subtotal=sub.negotiated_price,
                vat_total=vat_amount,
                grand_total=sub.negotiated_price + vat_amount,
                status='draft',
                created_by=officer
            )
            
            created_count += 1
        
        self.stdout.write(f'  → {created_count} recurring job cards auto-generated')

    def cleanup_old_notifications(self):
        """Delete notification logs older than 90 days"""
        cutoff = timezone.now() - timezone.timedelta(days=90)
        deleted, _ = NotificationLog.objects.filter(created_at__lt=cutoff).delete()
        self.stdout.write(f'  → {deleted} old notifications cleaned up')
