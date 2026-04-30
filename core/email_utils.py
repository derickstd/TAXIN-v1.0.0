"""
Email utility functions for Taxman256 PMS
Handles all email sending with HTML templates
"""
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.utils.html import strip_tags
import logging

logger = logging.getLogger(__name__)


def send_email(subject, to_email, template_name, context, from_email=None):
    """
    Send HTML email with fallback to plain text
    
    Args:
        subject: Email subject line
        to_email: Recipient email address (string or list)
        template_name: Template path (e.g., 'emails/invoice_email.html')
        context: Dictionary of template variables
        from_email: Sender email (defaults to settings.DEFAULT_FROM_EMAIL)
    
    Returns:
        Boolean indicating success
    """
    if not to_email:
        logger.warning(f"No recipient email provided for: {subject}")
        return False
    
    # Ensure to_email is a list
    if isinstance(to_email, str):
        to_email = [to_email]
    
    # Filter out empty emails
    to_email = [email.strip() for email in to_email if email and email.strip()]
    if not to_email:
        logger.warning(f"No valid recipient emails for: {subject}")
        return False
    
    try:
        # Render HTML content
        html_content = render_to_string(template_name, context)
        
        # Create plain text version by stripping HTML tags
        text_content = strip_tags(html_content)
        
        # Create email message
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=from_email or settings.DEFAULT_FROM_EMAIL,
            to=to_email,
        )
        
        # Attach HTML version
        email.attach_alternative(html_content, "text/html")
        
        # Send email
        email.send(fail_silently=False)
        
        logger.info(f"Email sent successfully: {subject} to {', '.join(to_email)}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send email '{subject}' to {to_email}: {str(e)}")
        return False


def send_invoice_email(invoice):
    """Send invoice to client via email"""
    if not invoice.client.email:
        logger.warning(f"No email for client {invoice.client.client_id}")
        return False
    
    subject = f"Invoice {invoice.invoice_number} from Taxman256"
    context = {'invoice': invoice}
    
    return send_email(
        subject=subject,
        to_email=invoice.client.email,
        template_name='emails/invoice_email.html',
        context=context,
    )


def send_payment_receipt(payment):
    """Send payment receipt to client via email"""
    if not payment.invoice.client.email:
        logger.warning(f"No email for client {payment.invoice.client.client_id}")
        return False
    
    subject = f"Payment Receipt - {payment.receipt_number}"
    context = {'payment': payment}
    
    return send_email(
        subject=subject,
        to_email=payment.invoice.client.email,
        template_name='emails/payment_receipt.html',
        context=context,
    )


def send_debt_reminder(client, invoices):
    """Send debt reminder to client with outstanding invoices"""
    if not client.email:
        logger.warning(f"No email for client {client.client_id}")
        return False
    
    subject = "Payment Reminder - Outstanding Invoices"
    context = {
        'client': client,
        'invoices': invoices,
    }
    
    return send_email(
        subject=subject,
        to_email=client.email,
        template_name='emails/debt_reminder.html',
        context=context,
    )


def send_compliance_reminder(client, deadlines):
    """Send compliance deadline reminder to client"""
    if not client.email:
        logger.warning(f"No email for client {client.client_id}")
        return False
    
    subject = "Tax Compliance Reminder - Upcoming Deadlines"
    context = {
        'client': client,
        'deadlines': deadlines,
    }
    
    return send_email(
        subject=subject,
        to_email=client.email,
        template_name='emails/compliance_reminder.html',
        context=context,
    )


def send_welcome_email(client):
    """Send welcome email to new client"""
    if not client.email:
        logger.warning(f"No email for client {client.client_id}")
        return False
    
    subject = "Welcome to Taxman256 Professional Management Services"
    context = {'client': client}
    
    return send_email(
        subject=subject,
        to_email=client.email,
        template_name='emails/welcome_client.html',
        context=context,
    )


def send_bulk_debt_reminders():
    """
    Send debt reminders to all clients with outstanding invoices
    Returns count of emails sent
    """
    from clients.models import Client
    from billing.models import Invoice
    
    sent_count = 0
    clients_with_debt = Client.objects.filter(total_outstanding__gt=0, status='active')
    
    for client in clients_with_debt:
        if not client.email:
            continue
        
        outstanding_invoices = Invoice.objects.filter(
            client=client
        ).exclude(status__in=['paid', 'written_off']).order_by('due_date')
        
        if outstanding_invoices.exists():
            if send_debt_reminder(client, outstanding_invoices):
                sent_count += 1
    
    logger.info(f"Bulk debt reminders sent: {sent_count} emails")
    return sent_count


def send_bulk_compliance_reminders():
    """
    Send compliance reminders to clients with upcoming deadlines (within 7 days)
    Returns count of emails sent
    """
    from compliance.models import ComplianceDeadline
    from django.utils import timezone
    from datetime import timedelta
    
    sent_count = 0
    today = timezone.now().date()
    week_ahead = today + timedelta(days=7)
    
    # Get upcoming deadlines
    upcoming = ComplianceDeadline.objects.filter(
        due_date__gte=today,
        due_date__lte=week_ahead,
        status='upcoming'
    ).select_related('obligation__client', 'obligation__service_type')
    
    # Group by client
    client_deadlines = {}
    for deadline in upcoming:
        client = deadline.obligation.client
        if client not in client_deadlines:
            client_deadlines[client] = []
        client_deadlines[client].append(deadline)
    
    # Send emails
    for client, deadlines in client_deadlines.items():
        if not client.email:
            continue
        
        if send_compliance_reminder(client, deadlines):
            sent_count += 1
    
    logger.info(f"Bulk compliance reminders sent: {sent_count} emails")
    return sent_count
