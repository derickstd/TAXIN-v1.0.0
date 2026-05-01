# CLIENT REGISTRATION TROUBLESHOOTING GUIDE

## Current Status
✅ Backend code: WORKING (verified with test_registration command)
✅ Template structure: CORRECT (services inside form tag)
❌ Web form: NOT WORKING (services not submitting)

## Root Cause
The Django server is using CACHED templates. Template changes require server restart.

## SOLUTION - Follow These Steps EXACTLY:

### Step 1: Stop Django Server
1. Go to the terminal where Django is running
2. Press `Ctrl + C` to stop the server
3. Wait for it to fully stop

### Step 2: Restart Django Server
```bash
python manage.py runserver 0.0.0.0:8000
```

### Step 3: Clear Browser Cache (CRITICAL!)
**Option A - Clear Cache:**
1. Press `Ctrl + Shift + Delete`
2. Select "Cached images and files"
3. Click "Clear data"

**Option B - Use Incognito Mode (RECOMMENDED):**
1. Press `Ctrl + Shift + N` (Chrome) or `Ctrl + Shift + P` (Firefox)
2. Go to: http://127.0.0.1:8000/clients/new/

### Step 4: Register Test Client
Fill in the form:

**Basic Information:**
- Client Type: `Company`
- Full Name: `ABC TEST COMPANY LIMITED`
- TIN: `1234567890`
- Primary Phone: `+256700123456`
- Email: `test@abc.com`
- District: `Kampala`

**Client Services:**
1. Click "Add Service" button
2. Select: `VAT`
3. Price: `150000` (auto-fills)
4. Frequency: `Monthly`

**Click "Save Client"**

### Step 5: Check Terminal Output
You should see in the terminal:

```
=== DEBUG: Service fields in POST ===
Service fields found: ['service_type_0', 'service_price_0', 'service_frequency_0']
  service_type_0 = 2
  service_price_0 = 150000
  service_frequency_0 = monthly
=== END DEBUG ===

=== Processing services ===
Found service: type_id=2, price=150000, freq=monthly
  Service type found: VAT
  Subscription created: X
  Obligation created: X (new=True)
Total services processed: 1
=== End processing services ===
```

### Step 6: Verify Success
Run this command:
```bash
python manage.py check_clients
```

Expected output:
```
✅ TX-00XX - ABC TEST COMPANY LIMITED
   Subscriptions: 1
   Obligations: 1
   Deadlines: 1
```

## If Still Not Working:

### Check 1: Verify Template File
Run:
```bash
type templates\clients\client_onboarding.html | findstr /N "servicesContainer"
```
Should show line 106

### Check 2: Check Server is Running
Look for this in terminal:
```
Starting development server at http://0.0.0.0:8000/
```

### Check 3: Test Backend Directly
Run:
```bash
python manage.py test_registration
```
Should show: `✅ ALL SYSTEMS WORKING!`

## Common Issues:

1. **Server not restarted** → Services won't submit
2. **Browser cache** → Old JavaScript/HTML loaded
3. **Wrong URL** → Make sure using http://127.0.0.1:8000/clients/new/
4. **JavaScript error** → Check browser console (F12)

## Need Help?
1. Send screenshot of terminal output
2. Send screenshot of browser console (F12 → Console tab)
3. Run `python manage.py check_clients` and send output
