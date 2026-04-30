# Email System Documentation

## Overview
Taxman256 now includes a comprehensive email notification system that works alongside WhatsApp notifications. All client communications can be sent via both channels automatically.

---

## Features Implemented

### ✅ Email Templates (HTML + Plain Text)
1. **Invoice Email** - Professional invoice delivery with full details
2. **Payment Receipt** - Automatic receipt after payment recording
3. **Debt Reminder** - Outstanding invoice notifications
4. **Compliance Reminder** - Tax deadline alerts
5. **Welcome Email** - New client onboarding

### ✅ Automated Email Sending
- **Invoice Delivery**: Sent when "Send via WhatsApp" button is clicked (sends both)
- **Payment Receipts**: Auto-sent when payment is recorded
- **Welcome Emails**: Sent when new client is created
- **Debt Reminders**: Scheduled bulk sending (daily/weekly)
- **Compliance Reminders**: 7 days before tax deadlines

### ✅ Email Utility Functions
Located in `core/email_utils.py`:
- `send_email()` - Generic HTML email sender
- `send_invoice_email()` - Invoice-specific
- `send_payment_receipt()` - Payment confirmation
- `send_debt_reminder()` - Outstanding balance alerts
- `send_compliance_reminder()` - Tax deadline notifications
- `send_welcome_email()` - New client greeting
- `send_bulk_debt_reminders()` - Batch debt reminders
- `send_bulk_compliance_reminders()` - Batch compliance alerts

---

## Configuration

### Development Mode (Console Backend)
Emails print to terminal - no SMTP needed.

```env
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
```

### Production with Gmail

1. **Enable 2-Factor Authentication** on your Gmail account
2. **Generate App Password**: Google Account → Security → App Passwords
3. **Update .env**:

```env
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-16-char-app-password
DEFAULT_FROM_EMAIL=Taxman256 <noreply@taxman256.ug>
```

### Production with SendGrid

1. **Sign up** at https://sendgrid.com (free tier: 100 emails/day)
2. **Create API Key**: Settings → API Keys → Create API Key
3. **Update .env**:

```env
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.sendgrid.net
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=apikey
EMAIL_HOST_PASSWORD=SG.your-sendgrid-api-key-here
DEFAULT_FROM_EMAIL=Taxman256 <noreply@taxman256.ug>
```

### Production with AWS SES

1. **Verify domain** in AWS SES console
2. **Create SMTP credentials**: SES → SMTP Settings → Create SMTP Credentials
3. **Update .env**:

```env
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=email-smtp.us-east-1.amazonaws.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-ses-smtp-username
EMAIL_HOST_PASSWORD=your-ses-smtp-password
DEFAULT_FROM_EMAIL=Taxman256 <noreply@taxman256.ug>
```

---

## Usage

### Manual Email Sending

#### Send Invoice
```python
from core.email_utils import send_invoice_email
from billing.models import Invoice

invoice = Invoice.objects.get(pk=1)
send_invoice_email(invoice)  # Returns True/False
```

#### Send Payment Receipt
```python
from core.email_utils import send_payment_receipt
from billing.models import Payment

payment = Payment.objects.get(pk=1)
send_payment_receipt(payment)
```

#### Send Welcome Email
```python
from core.email_utils import send_welcome_email
from clients.models import Client

client = Client.objects.get(pk=1)
send_welcome_email(client)
```

### Bulk Email Sending

#### Debt Reminders (All Clients with Outstanding Balance)
```bash
python manage.py send_debt_reminders
```

Or programmatically:
```python
from core.email_utils import send_bulk_debt_reminders
count = send_bulk_debt_reminders()  # Returns number sent
```

#### Compliance Reminders (Upcoming Deadlines)
```python
from core.email_utils import send_bulk_compliance_reminders
count = send_bulk_compliance_reminders()
```

---

## Automated Workflows

### When Invoice is Sent
1. User clicks "Send via WhatsApp" button on invoice
2. System sends WhatsApp message (if phone exists)
3. System sends HTML email (if email exists)
4. Success message shows which channels were used

### When Payment is Recorded
1. User records payment on invoice
2. System updates invoice status
3. System automatically sends payment receipt email
4. Client receives professional receipt

### When Client is Created
1. User saves new client with email address
2. System automatically sends welcome email
3. Client receives onboarding information

### Daily Automation (via `run_automation` command)
1. Compliance reminders sent 7 days before deadlines
2. Both WhatsApp and email sent automatically
3. Runs via scheduled task (cron/Task Scheduler)

---

## Email Templates

All templates located in `templates/emails/`:

### Base Template (`base_email.html`)
- Professional Ocean Teal branding
- Responsive design
- Header with logo
- Footer with contact info

### Invoice Email (`invoice_email.html`)
- Invoice number and dates
- Line item breakdown
- VAT calculation
- Payment instructions
- Balance due highlighted

### Payment Receipt (`payment_receipt.html`)
- Receipt number
- Payment details
- Remaining balance
- "Fully Paid" badge if complete

### Debt Reminder (`debt_reminder.html`)
- Total outstanding amount (red highlight)
- List of overdue invoices
- Payment methods
- Urgent tone for overdue items

### Compliance Reminder (`compliance_reminder.html`)
- Upcoming deadlines table
- Days remaining countdown
- Color-coded urgency (red/yellow/green)
- Action items checklist

### Welcome Email (`welcome_client.html`)
- Client ID and details
- Services overview
- What's next steps
- Contact information

---

## Testing Emails

### Test in Console (Development)
```bash
# Emails will print to terminal
python manage.py shell
>>> from core.email_utils import send_welcome_email
>>> from clients.models import Client
>>> client = Client.objects.first()
>>> send_welcome_email(client)
```

### Test with Real SMTP
```bash
# Configure .env with real SMTP settings
python manage.py shell
>>> from django.core.mail import send_mail
>>> send_mail(
...     'Test Email',
...     'This is a test.',
...     'noreply@taxman256.ug',
...     ['your-email@example.com'],
... )
```

### Django Test Email Command
```bash
python manage.py sendtestemail your-email@example.com
```

---

## Troubleshooting

### Emails Not Sending

**Check 1: Email Backend**
```python
from django.conf import settings
print(settings.EMAIL_BACKEND)
# Should be: django.core.mail.backends.smtp.EmailBackend (production)
```

**Check 2: SMTP Credentials**
```bash
# Test SMTP connection
python manage.py shell
>>> from django.core.mail import get_connection
>>> conn = get_connection()
>>> conn.open()  # Should return True
```

**Check 3: Client Has Email**
```python
from clients.models import Client
client = Client.objects.get(pk=1)
print(client.email)  # Should not be empty
```

**Check 4: Logs**
```bash
# Check for error messages
tail -f logs/email.log  # If logging configured
```

### Gmail "Less Secure Apps" Error
- Gmail no longer supports "less secure apps"
- **Solution**: Use App Passwords (requires 2FA enabled)
- Go to: Google Account → Security → App Passwords

### SendGrid Not Sending
- Check API key is valid
- Verify sender email in SendGrid dashboard
- Check SendGrid activity logs

### AWS SES Sandbox Mode
- New AWS SES accounts start in sandbox mode
- Can only send to verified email addresses
- **Solution**: Request production access in AWS console

---

## Scheduled Tasks

### Windows Task Scheduler

**Daily Debt Reminders (8 AM)**
```cmd
schtasks /create /tn "Taxman256 Debt Reminders" /tr "C:\path\to\python.exe C:\path\to\manage.py send_debt_reminders" /sc daily /st 08:00
```

**Daily Automation (includes compliance reminders)**
```cmd
schtasks /create /tn "Taxman256 Daily Automation" /tr "C:\path\to\python.exe C:\path\to\manage.py run_automation" /sc daily /st 06:00
```

### Linux Cron

```bash
# Edit crontab
crontab -e

# Add these lines:
0 8 * * * /path/to/python /path/to/manage.py send_debt_reminders
0 6 * * * /path/to/python /path/to/manage.py run_automation
```

---

## Email Metrics

### Track Email Success
All email sending is logged. Check logs:

```python
import logging
logger = logging.getLogger(__name__)
# Logs show: "Email sent successfully: [subject] to [recipient]"
```

### Monitor Delivery
- **Gmail**: Check Sent folder
- **SendGrid**: Activity dashboard shows delivery status
- **AWS SES**: CloudWatch metrics

---

## Best Practices

1. **Always provide fallback**: If email fails, WhatsApp still works
2. **Test templates**: Send test emails before going live
3. **Monitor bounce rates**: Remove invalid emails
4. **Respect opt-outs**: Add unsubscribe option if needed
5. **Use professional sender**: `Taxman256 <noreply@taxman256.ug>`
6. **Keep templates updated**: Match branding with system theme

---

## Future Enhancements

Potential additions:
- Email open tracking
- Click tracking on payment links
- Email templates editor in admin
- Client email preferences (opt-in/opt-out)
- Attachment support (PDF invoices)
- Email queue for bulk sending
- Retry logic for failed sends

---

## Support

For email system issues:
1. Check logs in terminal/console
2. Verify SMTP settings in .env
3. Test with Django's sendtestemail command
4. Check email provider's dashboard for errors
5. Ensure client email addresses are valid

---

**Email system is now fully operational! 📧**
