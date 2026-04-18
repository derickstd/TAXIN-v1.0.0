# Taxman256 PMS — Complete Guide

## Quick Start

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py setup_taxman256
python manage.py runserver 0.0.0.0:8000
```
Open: **http://127.0.0.1:8000**

---

## Default Logins

| Username  | Password  | Role         | Access                        |
|-----------|-----------|--------------|-------------------------------|
| admin     | admin123  | Admin        | Everything including settings |
| manager1  | pass1234  | Manager      | Finance, approvals, reports   |
| officer1  | pass1234  | Tax Officer  | Job cards, clients, filing    |

> ⚠️ Change passwords after first login via `/admin/`

---

## Sample Data Loaded

| Item              | Count | Details                                                |
|-------------------|-------|--------------------------------------------------------|
| Clients           | 9     | Companies, individuals, NGO — Active/Dormant/Suspended |
| Job Cards         | 13    | Various months, statuses, single and multi-service     |
| Invoices          | 13    | Paid, outstanding, overdue                             |
| Payments          | 6     | Mobile money and cash                                  |
| Expenses          | 8     | Mix of approved and pending                            |
| Credentials       | 6     | URA, NSSF, ASYCUDA — all encrypted                     |
| Compliance        | 24    | VAT, PAYE, NSSF, Income Tax deadlines                  |
| Service Types     | 16    | All Uganda tax services pre-loaded                     |

**Suspended client:** Mega Imports Uganda (debt > 60 days)  
**Dormant client:** Peter Okello (no recent transactions)  
**Credential needing reset:** Mega Imports URA login  

---

## Daily Workflow

### Morning Routine
1. **Dashboard** → check overdue invoices (red badge), compliance deadlines (sidebar)
2. **Job Cards** → pick up assigned open jobs from Kanban board
3. Work through each job, updating line item statuses as services are completed

### Filing a Return (VAT example)
1. Open the client's job card for the current month
2. Find the "VAT Return" line item → change status to **"Handled — Awaiting Payment"**
3. Client pays → go to the Invoice → click **Record Payment**
4. Change line item status to **"Handled & Paid"**
5. Once all lines are paid → update job card status to **"Completed"**

### New Walk-in Client
1. **Clients → New Client** — fill in details, save (gets auto TX-XXXX ID)
2. **Clients → Walk-in Intake** — record the visit purpose
3. **Jobs → New Job Card** — select client, search and add services using dropdown

---

## Key Feature Guide

### Price List
- Sidebar → **Price List** (direct link, always visible)
- Shows all 16 services grouped by category with Uganda pricing
- Ctrl+P or "Print" button → print-ready letterhead format for client handouts

### Dropdowns — Select2 Quick Search
All dropdowns support **live search** — just start typing:
- Client search: type name, TIN, or TX-XXXX client ID
- Service search: type service name — price auto-fills when you select
- Staff, category, district, month — all searchable
- "Register new client" link opens in a new tab without losing your work

### Invoicing
- Invoices are **auto-generated** when you save a job card
- Standalone invoice: Sidebar → **Manual Invoice**
- Record payments from the invoice detail page
- **Send via WhatsApp** button on every invoice (demo mode logs it; live with Twilio)

### WhatsApp Reminders (Automated)
| Schedule            | Action                                          |
|---------------------|-------------------------------------------------|
| Every Friday 8AM    | Debt reminder to every client with unpaid invoices |
| Every Saturday 8AM  | Full debt report list to manager (+256785230670)   |
| Every Monday 8AM    | Same manager debt report                           |

Manual trigger: **Notifications** → "Send Debt Reminders Now"

In demo mode (Twilio not configured), messages are **logged** in Notifications but not sent. To enable live sending, add Twilio credentials to `.env`.

### Compliance Calendar
- All VAT/PAYE/NSSF/NSSF deadlines auto-calculated (15th of following month)
- Income Tax: 31 December deadline
- Red badge on sidebar counts deadlines due within 7 days
- "Mark Filed" button updates the record and logs who filed it

### Credential Vault
- Stores URA, NSSF, URSB, ASYCUDA passwords encrypted with AES-256 Fernet
- Only **Managers and Admins** can click "Reveal" to see a password
- Every single reveal is permanently logged (staff name + timestamp)
- Expiry warnings: system alerts when credentials expire within 14 days

### Expenses
1. Sidebar → **Log Expense**
2. Select category from 17-item Uganda-specific dropdown
3. Attach receipt photo (optional)
4. Submit → Manager approves from the expense list
5. Monthly breakdown shown in the By Category panel

### Reports
| Report          | What it shows                                         |
|-----------------|-------------------------------------------------------|
| Price List      | Print-ready service menu with Uganda pricing          |
| Client Statement| All invoices/payments for a client, any date range    |
| Monthly Report  | Revenue, collections, expenses, net profit estimate   |
| Audit Books     | P&L + Balance Sheet with yellow [ENTER VALUE] gaps    |

---

## Mobile Use
- Works on phones and tablets — open in any browser
- Sidebar collapses on mobile (tap ☰ hamburger icon top-left)
- All tables scroll horizontally on small screens
- Date pickers are touch-friendly (Flatpickr)
- Forms are full-width on mobile

---

## Production Setup (Windows)

### 1. PostgreSQL (recommended over SQLite)
```sql
CREATE DATABASE taxman256;
CREATE USER taxman256user WITH PASSWORD 'StrongPassword123!';
GRANT ALL PRIVILEGES ON DATABASE taxman256 TO taxman256user;
```

Update `.env`:
```
DATABASE_URL=postgresql://taxman256user:StrongPassword123!@localhost:5432/taxman256
```

### 2. WhatsApp (Twilio)
```env
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886
MANAGER_WHATSAPP=+256785230670
```

### 3. Run with Waitress (Windows production server)
```bash
pip install waitress
python serve.py
```

### 4. Backup (Windows Task Scheduler — weekly)
```cmd
pg_dump -U taxman256user taxman256 > C:\Backups\taxman256_%date%.sql
```

---

## Troubleshooting

**No CSS/styling visible?**  
→ Make sure `{% load static %}` is the FIRST line of `templates/base.html` (before any `{% if %}`).  
→ Run `python manage.py collectstatic --noinput`  
→ Set `ALLOWED_HOSTS = ['*']` in settings (or add your PC IP)

**Select2 dropdowns not working?**  
→ CDN-loaded — requires internet connection on first use.  
→ Check browser console for blocked script errors.

**WhatsApp not sending?**  
→ Messages are logged in Notifications in demo mode.  
→ Add valid Twilio credentials to `.env` for live sending.

**Job card won't mark as Completed?**  
→ Invoice must be fully paid first. Record payment, then update status.

**Scheduled jobs not running?**  
→ Server must be running (APScheduler runs in-process).  
→ On Windows, use Task Scheduler to run `python manage.py runserver` as a startup service.
