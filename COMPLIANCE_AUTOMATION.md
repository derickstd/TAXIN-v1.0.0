# Automatic Compliance Deadline Generation

## Overview
The system automatically generates monthly compliance deadlines for all active clients on the 1st day of each month. This ensures that PAYE, VAT, Excise Duty, and NSSF obligations are tracked for every client.

---

## How It Works

### Automatic Generation (1st of Each Month)
When the daily automation runs on the 1st of any month:

1. **Identifies Active Clients**: All clients with status = 'active'
2. **Creates Obligations**: For each client, creates/updates obligations for:
   - PAYE
   - VAT Return
   - Excise Duty
   - NSSF
3. **Generates Deadlines**: Creates compliance deadlines with:
   - **Period**: Previous month (e.g., "January 2026")
   - **Due Date**: 15th of current month
   - **Status**: 'upcoming'

### Example
- **Date**: February 1, 2026
- **Period Generated**: January 2026
- **Due Date**: February 15, 2026
- **Services**: PAYE, VAT Return, Excise Duty, NSSF
- **Clients**: All active clients

---

## Manual Generation

### Generate for Current Month
```bash
python manage.py generate_compliance_deadlines
```

### Generate for Specific Month
```bash
# Generate deadlines for March 2026
python manage.py generate_compliance_deadlines --month 3 --year 2026
```

### What It Does
- Creates compliance obligations for all active clients
- Generates deadlines for the specified period
- Skips deadlines that already exist
- Shows breakdown by service type

---

## Compliance Workflow

### 1. Automatic Generation (1st of Month)
```
February 1, 2026
↓
System creates deadlines for January 2026
↓
Due date: February 15, 2026
↓
All active clients get 4 deadlines (PAYE, VAT, Excise, NSSF)
```

### 2. Staff Handling
- Staff view compliance calendar
- See all upcoming deadlines
- Process each client's obligations
- Mark as "Filed" when complete

### 3. Reminders (7 Days Before)
- **February 8, 2026**: System sends reminders
- WhatsApp + Email to clients
- Lists all upcoming deadlines

### 4. Overdue Detection
- **February 16, 2026**: Unfiled deadlines marked as 'overdue'
- Penalties can be recorded
- Follow-up actions triggered

---

## Service Types Required

The system looks for these exact service names:
- **PAYE** - Pay As You Earn (employee tax)
- **VAT Return** - Value Added Tax
- **Excise Duty** - Excise tax on specific goods
- **NSSF** - National Social Security Fund

### Creating Service Types
If these don't exist, create them:

1. Go to **Services → Service Catalogue**
2. Click **Add Service**
3. Create each service with:
   - Name: Exact match (e.g., "PAYE")
   - Category: Tax Compliance
   - Is Recurring: Yes
   - Deadline Type: Monthly

---

## Compliance Obligation Model

### Fields
- **client**: Which client has this obligation
- **service_type**: PAYE, VAT, Excise, or NSSF
- **frequency**: 'monthly' (auto-set)
- **is_active**: True (auto-set)

### Auto-Creation
Obligations are automatically created when:
- Compliance deadlines are generated
- Client doesn't have obligation for that service yet

---

## Compliance Deadline Model

### Fields
- **obligation**: Links to ComplianceObligation
- **period_label**: "January 2026"
- **due_date**: February 15, 2026
- **status**: 'upcoming', 'filed_and_paid', 'overdue', etc.
- **filed_date**: When marked as filed
- **filed_by**: Staff member who filed it

### Status Flow
```
upcoming → filed_and_paid (ideal)
upcoming → filed_not_paid (filed but client hasn't paid)
upcoming → overdue (past due date, not filed)
overdue → penalty_issued (URA penalty applied)
```

---

## Dashboard Integration

### Compliance Widget
Shows deadlines due within 7 days:
- Client name
- Service type
- Due date
- "Mark Filed" button

### Automation Status
Shows count of upcoming deadlines:
- Clickable card
- Links to full compliance calendar

---

## Scheduled Task Setup

### Windows Task Scheduler
```cmd
schtasks /create /tn "Taxman256 Daily Automation" /tr "C:\path\to\python.exe C:\path\to\manage.py run_automation" /sc daily /st 06:00
```

### Linux Cron
```bash
# Run daily at 6 AM
0 6 * * * /path/to/python /path/to/manage.py run_automation
```

### What Runs Daily
1. Generate compliance deadlines (1st of month only)
2. Update overdue invoices
3. Update client statuses
4. Send compliance reminders (7 days before)
5. Generate recurring job cards
6. Clean up old notifications

---

## Client Filtering

### Who Gets Deadlines?
- **Status = 'active'**: Yes
- **Status = 'dormant'**: No
- **Status = 'suspended'**: No
- **Status = 'blacklisted'**: No

### Reactivating Clients
When a suspended client pays off debt:
- Status changes to 'active'
- Next month's deadlines will be generated automatically

---

## Customization

### Different Due Dates
Edit `run_automation.py`:
```python
# Change from 15th to 20th
due_date = today.replace(day=20)
```

### Additional Services
Add more services to the list:
```python
monthly_services = ServiceType.objects.filter(
    name__in=['PAYE', 'VAT Return', 'Excise Duty', 'NSSF', 'WHT'],  # Added WHT
    is_active=True
)
```

### Quarterly Services
For quarterly obligations (e.g., Income Tax):
```python
# Generate only in specific months
if current_month in [4, 7, 10, 1]:  # Q1, Q2, Q3, Q4
    # Generate quarterly deadlines
```

---

## Troubleshooting

### No Deadlines Generated
**Check 1**: Are service types created?
```bash
python manage.py shell
>>> from services.models import ServiceType
>>> ServiceType.objects.filter(name__in=['PAYE', 'VAT Return', 'Excise Duty', 'NSSF'])
```

**Check 2**: Are there active clients?
```bash
>>> from clients.models import Client
>>> Client.objects.filter(status='active').count()
```

**Check 3**: Run manually
```bash
python manage.py generate_compliance_deadlines
```

### Duplicate Deadlines
The system checks for existing deadlines before creating:
```python
deadline_exists = ComplianceDeadline.objects.filter(
    obligation=obligation,
    period_label=period_label
).exists()
```

### Wrong Due Date
Check the logic in `run_automation.py`:
- Period: Previous month
- Due date: 15th of current month

---

## Benefits

### For Staff
- ✅ No manual deadline entry
- ✅ Consistent tracking across all clients
- ✅ Automatic reminders
- ✅ Clear workflow

### For Clients
- ✅ Never miss a deadline
- ✅ Timely reminders
- ✅ Professional service
- ✅ Avoid URA penalties

### For Business
- ✅ Scalable compliance management
- ✅ Reduced administrative overhead
- ✅ Better client retention
- ✅ Audit trail

---

## Future Enhancements

Potential additions:
- Client-specific due dates
- Service-specific frequencies
- Automatic job card creation from deadlines
- Integration with URA API for filing
- Penalty calculation automation
- Client portal for self-service

---

**Automatic compliance deadline generation is now active! 📅**
