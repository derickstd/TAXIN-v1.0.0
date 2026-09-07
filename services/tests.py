from datetime import timedelta
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from decimal import Decimal
import calendar as cal

from billing.models import Invoice, Payment
from clients.models import Client
from core.models import User
from core.models import AuditLog
from core.duplicate_detection import check_duplicate_transaction
from expenses.models import Expense, ExpenseCategory
from services.models import JobCard, JobCardLineItem, ServiceType
from services.views import _auto_create_invoice


class JobCardCreateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='tester',
            password='pass1234',
            role='tax_officer',
        )
        self.client.force_login(self.user)
        self.client_obj = Client.objects.create(
            full_name='Acme Ltd',
            phone_primary='+256700000000',
            created_by=self.user,
        )

    def test_create_jobcard_handles_blank_default_price_for_custom_line_item(self):
        response = self.client.post(reverse('services:create'), {
            'client': self.client_obj.pk,
            'period_month': '4',
            'period_year': '2026',
            'assigned_to': '',
            'priority': 'normal',
            'due_date': '',
            'notes': 'Regression test',
            'is_periodic': '',
            'line_items-TOTAL_FORMS': '1',
            'line_items-INITIAL_FORMS': '0',
            'line_items-MIN_NUM_FORMS': '0',
            'line_items-MAX_NUM_FORMS': '1000',
            'line_items-0-service_type': '',
            'line_items-0-custom_description': '',
            'line_items-0-default_price': '',
            'line_items-0-negotiated_price': '150000',
            'line_items-0-status': 'not_handled',
            'line_items-0-period_label': 'April 2026',
            'line_items-0-notes': 'Manual fee',
        })

        self.assertEqual(response.status_code, 302)
        job = JobCard.objects.get()
        item = job.line_items.get()
        self.assertEqual(item.default_price, 0)
        self.assertEqual(item.negotiated_price, 150000)
        self.assertEqual(item.vat_amount, 0)

    def test_create_jobcard_backfills_default_price_from_service_type(self):
        service = ServiceType.objects.create(
            name='VAT Filing',
            category='ura_filing',
            default_price='100000',
            vat_applicable=True,
        )

        response = self.client.post(reverse('services:create'), {
            'client': self.client_obj.pk,
            'period_month': '4',
            'period_year': '2026',
            'assigned_to': '',
            'priority': 'normal',
            'due_date': '',
            'notes': '',
            'is_periodic': '',
            'line_items-TOTAL_FORMS': '1',
            'line_items-INITIAL_FORMS': '0',
            'line_items-MIN_NUM_FORMS': '0',
            'line_items-MAX_NUM_FORMS': '1000',
            'line_items-0-service_type': str(service.pk),
            'line_items-0-custom_description': '',
            'line_items-0-default_price': '',
            'line_items-0-negotiated_price': '',
            'line_items-0-status': 'not_handled',
            'line_items-0-period_label': '',
            'line_items-0-notes': '',
        })

        self.assertEqual(response.status_code, 302)
        item = JobCardLineItem.objects.get()
        expected_price = Decimal('100000')
        self.assertEqual(item.default_price, expected_price)
        self.assertEqual(item.negotiated_price, expected_price)
        self.assertEqual(item.vat_amount, expected_price * Decimal('0.18'))

    def test_no_deadline_jobcard_shows_recorded_timestamp(self):
        service = ServiceType.objects.create(
            name='Business Advisory',
            category='advisory',
            default_price='75000',
            deadline_type='none',
        )

        response = self.client.post(reverse('services:create'), {
            'client': self.client_obj.pk,
            'period_month': '',
            'period_year': '',
            'assigned_to': '',
            'priority': 'normal',
            'due_date': '',
            'notes': '',
            'is_periodic': '',
            'line_items-TOTAL_FORMS': '1',
            'line_items-INITIAL_FORMS': '0',
            'line_items-MIN_NUM_FORMS': '0',
            'line_items-MAX_NUM_FORMS': '1000',
            'line_items-0-service_type': str(service.pk),
            'line_items-0-custom_description': '',
            'line_items-0-default_price': '',
            'line_items-0-negotiated_price': '',
            'line_items-0-status': 'not_handled',
            'line_items-0-period_label': '',
            'line_items-0-notes': '',
        })

        self.assertEqual(response.status_code, 302)
        job = JobCard.objects.get()
        detail = self.client.get(reverse('services:detail', args=[job.pk]))
        recorded_at = timezone.localtime(job.created_at).strftime('%d %b %Y %H:%M')
        self.assertContains(detail, recorded_at)

    def test_create_jobcard_does_not_auto_create_invoice(self):
        response = self.client.post(reverse('services:create'), {
            'client': self.client_obj.pk,
            'period_month': '4',
            'period_year': '2026',
            'assigned_to': '',
            'priority': 'normal',
            'due_date': '',
            'notes': 'No invoice until handled',
            'is_periodic': '',
            'line_items-TOTAL_FORMS': '1',
            'line_items-INITIAL_FORMS': '0',
            'line_items-MIN_NUM_FORMS': '0',
            'line_items-MAX_NUM_FORMS': '1000',
            'line_items-0-service_type': '',
            'line_items-0-custom_description': 'Manual consulting',
            'line_items-0-default_price': '0',
            'line_items-0-negotiated_price': '150000',
            'line_items-0-status': 'not_handled',
            'line_items-0-period_label': 'April 2026',
            'line_items-0-notes': 'Manual fee',
        })

        self.assertEqual(response.status_code, 302)
        job = JobCard.objects.get()
        self.assertFalse(Invoice.objects.filter(job_card=job).exists())

    def test_create_jobcard_generates_invoice_and_applies_client_credit(self):
        credit_invoice = Invoice.objects.create(
            client=self.client_obj,
            due_date=timezone.now().date(),
            subtotal=Decimal('100000'),
            grand_total=Decimal('100000'),
            status='sent',
            created_by=self.user,
        )
        Payment.objects.create(
            invoice=credit_invoice,
            amount=Decimal('150000'),
            method='cash',
            received_by=self.user,
        )

        response = self.client.post(reverse('services:create'), {
            'client': self.client_obj.pk,
            'period_month': '',
            'period_year': '',
            'assigned_to': '',
            'priority': 'normal',
            'notes': 'Use existing credit',
            'create_invoice': 'yes',
            'line_items-TOTAL_FORMS': '1',
            'line_items-INITIAL_FORMS': '0',
            'line_items-MIN_NUM_FORMS': '0',
            'line_items-MAX_NUM_FORMS': '1000',
            'line_items-0-service_type': '',
            'line_items-0-custom_description': 'New filing',
            'line_items-0-default_price': '100000',
            'line_items-0-negotiated_price': '100000',
            'line_items-0-status': 'not_handled',
            'line_items-0-period_label': '',
            'line_items-0-notes': '',
        })

        self.assertEqual(response.status_code, 302)
        new_job = JobCard.objects.exclude(pk=None).order_by('-pk').first()
        new_invoice = Invoice.objects.get(job_card=new_job)
        new_invoice.refresh_from_db()
        credit_invoice.refresh_from_db()
        self.assertEqual(new_invoice.amount_paid, Decimal('50000'))
        self.assertEqual(new_invoice.balance_due, Decimal('50000'))
        self.assertEqual(credit_invoice.amount_paid, Decimal('100000'))

    def test_jobcard_quick_create_creates_jobcard_and_invoice_payment(self):
        service = ServiceType.objects.create(
            name='VAT Filing',
            category='ura_filing',
            default_price=Decimal('100000'),
            vat_applicable=True,
        )
        staff = User.objects.create_user(
            username='taxstaff',
            password='pass1234',
            role='tax_officer',
        )

        response = self.client.post(reverse('services:quick_create'), {
            'client': self.client_obj.pk,
            'service_type': service.pk,
            'assigned_to': staff.pk,
            'priority': 'urgent',
            'notes': 'Quick create test',
            'create_invoice': 'yes',
            'payment_received': 'yes',
            'payment_amount': '120000',
            'payment_method': 'cash',
            'payment_reference': 'REF123',
            'jobcardlineitem_set-TOTAL_FORMS': '1',
            'jobcardlineitem_set-INITIAL_FORMS': '0',
            'jobcardlineitem_set-MIN_NUM_FORMS': '0',
            'jobcardlineitem_set-MAX_NUM_FORMS': '1000',
            'jobcardlineitem_set-0-service_type': str(service.pk),
            'jobcardlineitem_set-0-default_price': '100000',
            'jobcardlineitem_set-0-negotiated_price': '100000',
            'jobcardlineitem_set-0-status': 'not_handled',
            'jobcardlineitem_set-0-period_label': 'April 2026',
            'jobcardlineitem_set-0-notes': 'Quick job',
        })

        self.assertEqual(response.status_code, 302)
        job = JobCard.objects.latest('pk')
        self.assertEqual(job.client, self.client_obj)
        self.assertEqual(job.assigned_to, staff)
        self.assertEqual(job.priority, 'urgent')
        self.assertEqual(job.notes, 'Quick create test')
        self.assertTrue(job.line_items.exists())
        self.assertTrue(Invoice.objects.filter(job_card=job).exists())
        invoice = Invoice.objects.get(job_card=job)
        self.assertEqual(invoice.grand_total, Decimal('118000'))
        self.assertTrue(invoice.payments.exists())
        payment = invoice.payments.first()
        self.assertEqual(payment.amount, Decimal('120000'))
        self.assertEqual(payment.reference, 'REF123')

    def test_quick_create_duplicate_warning_serializes_match_date(self):
        service = ServiceType.objects.create(
            name='VAT Return',
            category='ura_filing',
            default_price=Decimal('100000'),
            deadline_type='monthly_15',
            is_recurring=True,
        )
        now = timezone.now()
        existing_job = JobCard.objects.create(
            client=self.client_obj,
            period_month=now.month,
            period_year=now.year,
            created_by=self.user,
        )
        JobCardLineItem.objects.create(
            job_card=existing_job,
            service_type=service,
            default_price=Decimal('100000'),
            negotiated_price=Decimal('100000'),
            vat_amount=Decimal('0'),
            status='not_handled',
            period_label=f'{cal.month_name[now.month]} {now.year}',
        )

        response = self.client.post(reverse('services:quick_create'), {
            'client': self.client_obj.pk,
            'service_type': service.pk,
            'jobcardlineitem_set-TOTAL_FORMS': '1',
            'jobcardlineitem_set-INITIAL_FORMS': '0',
            'jobcardlineitem_set-MIN_NUM_FORMS': '0',
            'jobcardlineitem_set-MAX_NUM_FORMS': '1000',
            'jobcardlineitem_set-0-service_type': service.pk,
            'jobcardlineitem_set-0-period_label': f'{cal.month_name[now.month]} {now.year}',
        })

        self.assertEqual(response.status_code, 302)
        self.assertIsInstance(self.client.session['duplicate_matches'][0]['date'], str)

    def test_ajax_check_duplicate_falls_back_to_current_period_for_recurring_service(self):
        service = ServiceType.objects.create(
            name='VAT Return',
            category='ura_filing',
            default_price=Decimal('100000'),
            deadline_type='monthly_15',
            is_recurring=True,
        )
        now = timezone.now()
        existing_job = JobCard.objects.create(
            client=self.client_obj,
            period_month=now.month,
            period_year=now.year,
            created_by=self.user,
        )
        JobCardLineItem.objects.create(
            job_card=existing_job,
            service_type=service,
            default_price=Decimal('100000'),
            negotiated_price=Decimal('100000'),
            vat_amount=Decimal('18000'),
            status='not_handled',
            period_label=f"{cal.month_name[now.month]} {now.year}",
        )

        response = self.client.get(reverse('services:ajax_check_duplicate'), {
            'client': self.client_obj.pk,
            'service_type': service.pk,
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get('matches'))
        self.assertTrue(any(item['type'] == 'job_card' for item in response.json()['matches']))


class DuplicateTransactionDetectionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='dupchecker',
            password='pass1234',
            role='tax_officer',
        )
        self.client.force_login(self.user)
        self.client_obj = Client.objects.create(
            full_name='Duplicate Test Client',
            phone_primary='+256700444555',
            created_by=self.user,
        )

    def test_duplicate_detection_uses_same_period_and_relevant_deadline_rules(self):
        service = ServiceType.objects.create(
            name='VAT Return',
            category='ura_filing',
            default_price=Decimal('100000'),
            deadline_type='monthly_15',
            is_recurring=True,
        )
        existing_job = JobCard.objects.create(
            client=self.client_obj,
            period_month=4,
            period_year=2026,
            created_by=self.user,
        )
        JobCardLineItem.objects.create(
            job_card=existing_job,
            service_type=service,
            default_price=Decimal('100000'),
            negotiated_price=Decimal('100000'),
            vat_amount=Decimal('0'),
            status='not_handled',
            period_label='April 2026',
        )

        similar = check_duplicate_transaction(
            self.client_obj,
            service_type=service,
            period_year=2026,
            period_month=4,
            within_days=30,
        )

        self.assertTrue(any(item['type'] == 'job_card' for item in similar))

    def test_ajax_check_duplicate_endpoint_returns_existing_jobcard(self):
        service = ServiceType.objects.create(
            name='VAT Return',
            category='ura_filing',
            default_price=Decimal('100000'),
            deadline_type='monthly_15',
            is_recurring=True,
        )
        existing_job = JobCard.objects.create(
            client=self.client_obj,
            period_month=4,
            period_year=2026,
            created_by=self.user,
        )
        JobCardLineItem.objects.create(
            job_card=existing_job,
            service_type=service,
            default_price=Decimal('100000'),
            negotiated_price=Decimal('100000'),
            vat_amount=Decimal('0'),
            status='not_handled',
            period_label='April 2026',
        )

        response = self.client.get(reverse('services:ajax_check_duplicate'), {
            'client': self.client_obj.pk,
            'service_type': service.pk,
            'period_month': '4',
            'period_year': '2026',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('matches', response.json())
        self.assertTrue(any(item['type'] == 'job_card' for item in response.json()['matches']))

    def test_duplicate_detection_skips_services_outside_allowed_deadline_rules(self):
        service = ServiceType.objects.create(
            name='Advisory Service',
            category='advisory',
            default_price=Decimal('50000'),
            deadline_type='none',
            is_recurring=False,
        )
        existing_job = JobCard.objects.create(
            client=self.client_obj,
            period_month=4,
            period_year=2026,
            created_by=self.user,
        )
        JobCardLineItem.objects.create(
            job_card=existing_job,
            service_type=service,
            default_price=Decimal('50000'),
            negotiated_price=Decimal('50000'),
            vat_amount=Decimal('0'),
            status='not_handled',
            period_label='April 2026',
        )

        similar = check_duplicate_transaction(
            self.client_obj,
            service_type=service,
            period_year=2026,
            period_month=4,
            within_days=30,
        )

        self.assertEqual(similar, [])

    def test_duplicate_detection_ignores_old_transaction_even_when_period_matches(self):
        service = ServiceType.objects.create(
            name='VAT Return',
            category='ura_filing',
            default_price=Decimal('100000'),
            deadline_type='monthly_15',
            is_recurring=True,
        )
        existing_job = JobCard.objects.create(
            client=self.client_obj,
            period_month=4,
            period_year=2026,
            created_by=self.user,
        )
        JobCard.objects.filter(pk=existing_job.pk).update(created_at=timezone.now() - timedelta(days=45))
        JobCardLineItem.objects.create(
            job_card=existing_job,
            service_type=service,
            default_price=Decimal('100000'),
            negotiated_price=Decimal('100000'),
            vat_amount=Decimal('0'),
            status='not_handled',
            period_label='April 2026',
        )

        similar = check_duplicate_transaction(
            self.client_obj,
            service_type=service,
            period_year=2026,
            period_month=4,
            within_days=14,
        )

        self.assertFalse(any(item['type'] == 'job_card' for item in similar))


class JobCardDetailDuplicateStatusTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='detailstatus',
            password='pass1234',
            role='tax_officer',
        )
        self.client.force_login(self.user)
        self.client_obj = Client.objects.create(
            full_name='Duplicate Status Client',
            phone_primary='+256700333444',
            created_by=self.user,
        )

    def test_jobcard_detail_marks_duplicate_transaction_for_same_period_service(self):
        service = ServiceType.objects.create(
            name='VAT Return',
            category='ura_filing',
            default_price=Decimal('100000'),
            deadline_type='monthly_15',
            is_recurring=True,
        )
        existing_job = JobCard.objects.create(
            client=self.client_obj,
            period_month=4,
            period_year=2026,
            created_by=self.user,
        )
        JobCardLineItem.objects.create(
            job_card=existing_job,
            service_type=service,
            default_price=Decimal('100000'),
            negotiated_price=Decimal('100000'),
            vat_amount=Decimal('0'),
            status='not_handled',
            period_label='April 2026',
        )
        current_job = JobCard.objects.create(
            client=self.client_obj,
            period_month=4,
            period_year=2026,
            created_by=self.user,
        )
        JobCardLineItem.objects.create(
            job_card=current_job,
            service_type=service,
            default_price=Decimal('100000'),
            negotiated_price=Decimal('100000'),
            vat_amount=Decimal('0'),
            status='not_handled',
            period_label='April 2026',
        )

        response = self.client.get(reverse('services:detail', kwargs={'pk': current_job.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['is_duplicate_transaction'])

    def test_jobcard_list_marks_duplicate_transaction_for_same_period_service(self):
        service = ServiceType.objects.create(
            name='VAT Return',
            category='ura_filing',
            default_price=Decimal('100000'),
            deadline_type='monthly_15',
            is_recurring=True,
        )
        existing_job = JobCard.objects.create(
            client=self.client_obj,
            period_month=4,
            period_year=2026,
            created_by=self.user,
        )
        JobCardLineItem.objects.create(
            job_card=existing_job,
            service_type=service,
            default_price=Decimal('100000'),
            negotiated_price=Decimal('100000'),
            vat_amount=Decimal('0'),
            status='not_handled',
            period_label='April 2026',
        )
        current_job = JobCard.objects.create(
            client=self.client_obj,
            period_month=4,
            period_year=2026,
            created_by=self.user,
        )
        JobCardLineItem.objects.create(
            job_card=current_job,
            service_type=service,
            default_price=Decimal('100000'),
            negotiated_price=Decimal('100000'),
            vat_amount=Decimal('0'),
            status='not_handled',
            period_label='April 2026',
        )

        response = self.client.get(reverse('services:list'))

        self.assertEqual(response.status_code, 200)
        self.assertIn('duplicate_statuses', response.context)
        self.assertTrue(response.context['duplicate_statuses'].get(current_job.pk, False))


class ServiceCatalogueManagementTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='adminuser',
            password='pass1234',
            role='admin',
        )
        self.staff = User.objects.create_user(
            username='staffuser',
            password='pass1234',
            role='tax_officer',
        )

    def test_admin_can_add_service_with_price(self):
        self.client.force_login(self.admin)

        response = self.client.post(reverse('services:service_new'), {
            'name': 'PAYE Filing',
            'category': 'ura_filing',
            'default_price': '85000',
            'deadline_type': 'monthly_15',
            'is_recurring': 'on',
            'vat_applicable': 'on',
            'description': 'Monthly payroll filing support',
        })

        self.assertEqual(response.status_code, 302)
        service = ServiceType.objects.get(name='PAYE Filing')
        self.assertEqual(service.default_price, Decimal('85000'))
        self.assertTrue(service.is_recurring)
        self.assertTrue(service.vat_applicable)
        self.assertTrue(service.is_active)

    def test_remove_unused_service_deletes_it(self):
        service = ServiceType.objects.create(
            name='Dormant Account Reactivation',
            category='miscellaneous',
            default_price=Decimal('50000'),
        )
        self.client.force_login(self.admin)

        response = self.client.post(reverse('services:service_toggle', args=[service.pk]), {
            'action': 'remove',
        })

        self.assertEqual(response.status_code, 302)
        self.assertFalse(ServiceType.objects.filter(pk=service.pk).exists())

    def test_remove_used_service_deactivates_it(self):
        service = ServiceType.objects.create(
            name='VAT Advisory',
            category='ura_advisory',
            default_price=Decimal('120000'),
        )
        client = Client.objects.create(
            full_name='In Use Client',
            phone_primary='+256700000123',
            created_by=self.admin,
        )
        job = JobCard.objects.create(client=client, created_by=self.admin)
        JobCardLineItem.objects.create(
            job_card=job,
            service_type=service,
            default_price=Decimal('120000'),
            negotiated_price=Decimal('120000'),
        )
        self.client.force_login(self.admin)

        response = self.client.post(reverse('services:service_toggle', args=[service.pk]), {
            'action': 'remove',
        })

        self.assertEqual(response.status_code, 302)
        service.refresh_from_db()
        self.assertFalse(service.is_active)

    def test_non_admin_cannot_add_service(self):
        self.client.force_login(self.staff)

        response = self.client.post(reverse('services:service_new'), {
            'name': 'Blocked Service',
            'category': 'miscellaneous',
            'default_price': '1000',
        })

        self.assertEqual(response.status_code, 302)
        self.assertFalse(ServiceType.objects.filter(name='Blocked Service').exists())


class JobCardLineItemStatusTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='tester2',
            password='pass1234',
            role='tax_officer',
        )
        self.client.force_login(self.user)
        self.client_obj = Client.objects.create(
            full_name='Future Ltd',
            phone_primary='+256700000001',
            created_by=self.user,
        )
        self.service = ServiceType.objects.create(
            name='Compliance Check',
            category='ura_advisory',
            default_price=Decimal('90000'),
            vat_applicable=False,
        )

    def test_paid_not_yet_handled_line_item_sets_job_in_progress(self):
        job = JobCard.objects.create(client=self.client_obj, created_by=self.user)
        item = JobCardLineItem.objects.create(
            job_card=job,
            service_type=self.service,
            default_price=Decimal('90000'),
            negotiated_price=Decimal('90000'),
            vat_amount=Decimal('0'),
            status='not_handled',
        )

        response = self.client.post(reverse('services:line_status', args=[item.pk]), {
            'status': 'paid_not_handled',
        })

        self.assertEqual(response.status_code, 302)
        job.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(item.status, 'paid_not_handled')
        self.assertEqual(job.status, 'in_progress')

    def test_paid_not_yet_handled_invoice_payment_does_not_auto_complete_job(self):
        job = JobCard.objects.create(client=self.client_obj, created_by=self.user)
        item = JobCardLineItem.objects.create(
            job_card=job,
            service_type=self.service,
            default_price=Decimal('90000'),
            negotiated_price=Decimal('90000'),
            vat_amount=Decimal('0'),
            status='paid_not_handled',
        )
        invoice = Invoice.objects.create(
            client=self.client_obj,
            job_card=job,
            due_date=timezone.now().date(),
            subtotal=item.negotiated_price,
            vat_total=item.vat_amount,
            grand_total=item.negotiated_price + item.vat_amount,
            status='sent',
            created_by=self.user,
        )

        Payment.objects.create(
            invoice=invoice,
            amount=invoice.grand_total,
            method='cash',
            received_by=self.user,
        )

        job.refresh_from_db()
        item.refresh_from_db()
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, 'paid')
        self.assertEqual(invoice.amount_paid, invoice.grand_total)
        self.assertEqual(item.status, 'paid_not_handled')
        self.assertNotEqual(job.status, 'completed')

    def test_handled_line_item_auto_creates_invoice(self):
        job = JobCard.objects.create(client=self.client_obj, created_by=self.user)
        item = JobCardLineItem.objects.create(
            job_card=job,
            service_type=self.service,
            default_price=Decimal('90000'),
            negotiated_price=Decimal('90000'),
            vat_amount=Decimal('0'),
            status='not_handled',
        )

        response = self.client.post(reverse('services:line_status', args=[item.pk]), {
            'status': 'handled_not_paid',
        })

        self.assertEqual(response.status_code, 302)
        job.refresh_from_db()
        self.assertTrue(Invoice.objects.filter(job_card=job).exists())
        invoice = job.invoice
        self.assertEqual(invoice.status, 'sent')
        self.assertEqual(invoice.grand_total, Decimal('90000'))

    def test_handled_and_paid_records_payment_and_audit_log(self):
        job = JobCard.objects.create(client=self.client_obj, created_by=self.user)
        item = JobCardLineItem.objects.create(
            job_card=job,
            service_type=self.service,
            default_price=Decimal('90000'),
            negotiated_price=Decimal('90000'),
            vat_amount=Decimal('0'),
            status='not_handled',
        )

        response = self.client.post(reverse('services:line_status', args=[item.pk]), {
            'status': 'handled_paid',
        })

        self.assertEqual(response.status_code, 302)
        invoice = Invoice.objects.get(job_card=job)
        payment = Payment.objects.get(invoice=invoice)
        self.assertEqual(payment.amount, invoice.grand_total)
        self.assertEqual(payment.received_by, self.user)
        self.assertTrue(AuditLog.objects.filter(
            model_name='job_card',
            object_id=str(job.pk),
            notes__icontains='marked handled and paid',
        ).exists())

        self.client.post(reverse('services:line_status', args=[item.pk]), {
            'status': 'handled_paid',
        })
        self.assertEqual(Payment.objects.filter(invoice=invoice).count(), 1)

    def test_auto_created_invoice_includes_billable_linked_expenses(self):
        job = JobCard.objects.create(client=self.client_obj, created_by=self.user)
        JobCardLineItem.objects.create(
            job_card=job,
            service_type=self.service,
            default_price=Decimal('90000'),
            negotiated_price=Decimal('90000'),
            vat_amount=Decimal('0'),
            status='not_handled',
        )
        category = ExpenseCategory.objects.create(name='Transport', approval_required=False)
        Expense.objects.create(
            expense_date=timezone.now().date(),
            category=category,
            description='Taxi to client site',
            amount=Decimal('25000'),
            paid_by=self.user,
            client=self.client_obj,
            job_card=job,
            is_billable=True,
            created_by=self.user,
            status='submitted',
        )

        invoice = _auto_create_invoice(job, self.user)

        self.assertEqual(invoice.subtotal, Decimal('115000'))
        self.assertEqual(invoice.grand_total, Decimal('115000'))
