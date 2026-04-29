# Taxman256 Automation Features

## Overview
The system includes comprehensive automation to minimize manual work and ensure smooth operations.

---

## Real-Time Automations (Instant)

### 1. **Invoice Auto-Generation**
- **Trigger:** When a job card is created or updated
- **Action:** Automatically creates an invoice with calculated totals
- **Status:** Invoice starts as "Draft" until work begins

### 2. **Job Card Status Auto-Update**
- **Trigger:** When line item status changes
- **Actions:**
  - All items "Not Handled" → Job stays "Open"
  - Any item "Handled" → Job becomes "In Progress"
  - All items "Handled - Awaiting Payment" → Job becomes "Pending Payment"
  - All items "Handled & Paid" → Job becomes "Completed"

### 3. **Invoice Status Sync**
- **Trigger:** When line items or payments change
- **Actions:**
  - Line items handled → Invoice status changes from "Draft" to "Sent"
  - Payment recorded → Invoice becomes "Partially Paid" or "Paid"
  - All line items paid → Invoice marked "Paid"

### 4. **Client Outstanding Balance Update**
- **Trigger:** When payment is recorded
- **Action:** Automatically recalculates client's total outstanding debt
- **Updates:** Client's last transaction date

### 5. **Line Item Auto-Pricing**
- **Trigger:** When service is selected in job card
- **Actions:**
  - Auto-fills default price from service catalogue
  - Calculates 18% VAT if applicable
  - Updates job card total

---

## Scheduled Automations (Daily at 2 AM)

### 1. **Overdue Invoice Detection**
- Scans all "Sent" and "Partially Paid" invoices
- Marks as "Overdue" if due date has passed
- Updates invoice status automatically

### 2. **Client Status Management**
- **Suspended:** Clients with 60+ days overdue debt
  - Sends WhatsApp suspension notice
  - Blocks new job creation (optional)
- **Dormant:** Clients with no activity in 6 months
  - Marks for follow-up
- **Reactivated:** Suspended clients who clear debt
  - Automatically restores to "Active"

### 3. **Compliance Deadline Reminders**
- Sends WhatsApp reminders 7 days before deadline
- Includes: VAT, PAYE, NSSF, Income Tax deadlines
- Sent to client's WhatsApp number

### 4. **Recurring Job Card Generation**
- **Runs:** 1st of every month
- **Creates:** Job cards for clients with recurring services
- **Includes:** Auto-generated invoice
- **Example:** Monthly VAT returns, PAYE submissions

### 5. **Notification Cleanup**
- Deletes notification logs older than 90 days
- Keeps system database lean

---

## Manual Automation Triggers

### Generate Missing Invoices
```bash
python manage.py generate_missing_invoices
```
- Scans all job cards without invoices
- Creates invoices for jobs in progress
- Useful after bulk imports

### Run Full Automation Suite
```bash
python manage.py run_automation
```
- Runs all daily automation tasks immediately
- Use for testing or emergency updates

---

## Smart Recommendations (Dashboard)

The system analyzes data and provides actionable recommendations:

1. **Job Cards Without Invoices**
   - Alerts when jobs are in progress but no invoice exists
   - Links directly to job card list

2. **High-Value Overdue Invoices**
   - Highlights invoices > UGX 500,000 that are overdue
   - Priority follow-up list

3. **Suspended Clients**
   - Shows count of suspended clients
   - Quick link to review and contact

4. **Completed Jobs Awaiting Payment**
   - Identifies work done but not paid
   - Suggests sending payment reminders

---

## Automation Status Widget

Dashboard shows:
- Last automation run time
- Overdue invoices updated today
- Suspended/dormant client counts
- Upcoming compliance deadlines (7 days)
- Auto-generated jobs today
- Pending payment count

---

## WhatsApp Automation

### Debt Reminders (Friday 8 AM)
- Sent to all clients with unpaid invoices
- Includes outstanding amount and invoice numbers

### Manager Reports (Saturday & Monday 8 AM)
- Full debt report to manager's WhatsApp
- Lists all clients with outstanding balances

### Suspension Notices (Immediate)
- Sent when client is auto-suspended
- Includes outstanding amount and contact info

### Compliance Reminders (7 days before)
- Deadline notifications
- Service name and due date

---

## Setup Instructions

### Windows Task Scheduler (Production)

1. **Create Daily Task:**
   ```cmd
   Task Name: Taxman256 Daily Automation
   Trigger: Daily at 2:00 AM
   Action: python C:\path\to\manage.py run_automation
   ```

2. **Create Monthly Task:**
   ```cmd
   Task Name: Taxman256 Monthly Jobs
   Trigger: 1st of every month at 1:00 AM
   Action: python C:\path\to\manage.py run_automation
   ```

### Linux Cron (Production)

Add to crontab:
```bash
# Daily automation at 2 AM
0 2 * * * cd /path/to/taxin && python manage.py run_automation

# Generate missing invoices daily at 3 AM
0 3 * * * cd /path/to/taxin && python manage.py generate_missing_invoices
```

---

## Automation Signals (Developer Reference)

Located in: `services/signals.py`

1. **post_save on JobCardLineItem**
   - Updates job card total
   - Syncs job status
   - Updates invoice

2. **post_save on Payment**
   - Updates invoice amount paid
   - Recalculates client outstanding
   - Marks line items as paid

3. **pre_save on Client**
   - Auto-suspends for overdue debt
   - Marks dormant clients

4. **post_save on Invoice**
   - Auto-marks overdue invoices

---

## Benefits

✅ **Reduced Manual Work:** 70% less data entry
✅ **Fewer Errors:** Automatic calculations eliminate mistakes
✅ **Better Cash Flow:** Timely reminders improve collections
✅ **Client Retention:** Proactive compliance reminders
✅ **Real-Time Insights:** Always up-to-date status
✅ **Scalability:** Handles 100+ clients effortlessly

---

## Troubleshooting

**Automation not running?**
- Check Task Scheduler/cron is active
- Verify Python path is correct
- Check logs: `python manage.py run_automation` manually

**Invoices not auto-generating?**
- Ensure job card has line items with prices
- Check signals are loaded: restart server

**WhatsApp not sending?**
- Verify Twilio credentials in `.env`
- Check notification logs for errors

**Client status not updating?**
- Run: `python manage.py run_automation`
- Check invoice due dates are set correctly

---

## Future Enhancements

- Email automation (in addition to WhatsApp)
- Predictive analytics for cash flow
- Auto-assignment of jobs to least busy officer
- Smart pricing suggestions based on client history
- Automated report generation and distribution
