from io import BytesIO
from tempfile import TemporaryDirectory
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from billing.models import (
    BranchDailySummary, BranchDailyTransaction, Invoice, OtherIncome, Payment,
    PaymentSubmission,
)
from clients.models import Client
from core.models import Branch, Company, User
from services.models import ServiceCategory, ServiceType
from services.forms import ServiceTypeForm, service_category_choices


class ClientPaymentFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='clientpaytester',
            password='pass1234',
            role='admin',
        )
        self.client.force_login(self.user)
        self.client_obj = Client.objects.create(
            full_name='Lump Sum Client',
            phone_primary='+256700555666',
            created_by=self.user,
        )

    def test_client_detail_page_exposes_lump_sum_payment_form(self):
        Invoice.objects.create(
            client=self.client_obj,
            due_date=timezone.now().date(),
            subtotal=Decimal('1000'),
            grand_total=Decimal('1000'),
            status='sent',
            created_by=self.user,
        )

        response = self.client.get(reverse('clients:detail', args=[self.client_obj.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Record Lump-Sum Payment')
        self.assertContains(response, reverse('billing:client_pay'))
        self.assertContains(response, 'earliest periods first')
        self.assertContains(response, 'Pending invoices')
        self.assertContains(response, 'name="invoice_ids"')
        self.assertContains(response, 'name="payment_submission_token"')

    def test_client_detail_groups_secondary_header_actions(self):
        response = self.client.get(reverse('clients:detail', args=[self.client_obj.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Client actions')
        self.assertContains(response, 'Edit client')
        self.assertContains(response, 'Account statement')
        self.assertContains(response, 'Credentials (0)')

    def test_repeated_client_payment_submission_records_payment_once(self):
        invoice = Invoice.objects.create(
            client=self.client_obj,
            due_date=timezone.now().date(),
            subtotal=Decimal('1000'),
            grand_total=Decimal('1000'),
            status='sent',
            created_by=self.user,
        )
        token = str(uuid4())
        payload = {
            'payment_submission_token': token,
            'client': self.client_obj.pk,
            'amount': '1000',
            'method': 'cash',
            'payment_date': timezone.localdate().isoformat(),
        }

        first = self.client.post(reverse('billing:client_pay'), payload)
        replay = self.client.post(reverse('billing:client_pay'), payload)

        self.assertEqual(first.status_code, 302)
        self.assertEqual(replay.status_code, 302)
        self.assertEqual(Payment.objects.filter(invoice=invoice).count(), 1)
        self.assertEqual(PaymentSubmission.objects.filter(token=token).count(), 1)


class QuickPaymentTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='quickpaytester',
            password='pass1234',
            role='admin',
        )
        self.client.force_login(self.user)
        self.client_obj = Client.objects.create(
            full_name='Quick Payment Client',
            phone_primary='+256700555667',
            created_by=self.user,
        )

    def test_quick_payment_page_replaces_floating_message_link(self):
        anonymous_client = Client.objects.create(
            full_name='Anonymous Customer',
            phone_primary='N/A',
            created_by=self.user,
        )
        response = self.client.get(reverse('billing:quick_payment'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="floating-payment-button"')
        self.assertContains(response, reverse('billing:quick_payment'))
        self.assertContains(response, reverse('clients:quick_create'))
        self.assertContains(response, 'data-open-quick-customer')
        self.assertContains(response, 'Walk-in / anonymous (Walk-in Customers)')
        self.assertContains(response, self.client_obj.get_display_name())
        self.assertContains(response, f'value="{anonymous_client.pk}"')
        self.assertContains(response, reverse('clients:create'))
        self.assertContains(response, 'Add Customer')
        self.assertContains(response, 'class="quick-payment-form"')
        self.assertContains(response, 'aria-label="Add customer"')
        self.assertContains(response, 'aria-label="Add service"')
        self.assertContains(response, 'Search by name, phone, or TIN')
        self.assertContains(response, 'Receipt number, mobile money ID, or bank reference')
        self.assertContains(response, 'Optional: add allocation details, receipt context, or other payment notes')
        self.assertContains(response, 'payment-service')
        self.assertContains(response, 'class="form-control s2" id="payment-client"')
        self.assertContains(response, 'data-open-quick-service')
        self.assertContains(response, 'data-open-quick-category')
        self.assertContains(response, 'quickServiceCategoryInline')
        self.assertContains(response, 'Record Payment')
        self.assertContains(response, 'name="payment_submission_token"')
        self.assertContains(response, 'Capital Injection')
        self.assertContains(response, 'Credit')
        self.assertNotContains(response, 'New staff message')

    def test_repeated_quick_payment_submission_records_payment_once(self):
        token = str(uuid4())
        payload = {
            'payment_submission_token': token,
            'client': self.client_obj.pk,
            'amount': '1500',
            'method': 'cash',
            'payment_date': timezone.localdate().isoformat(),
        }

        first = self.client.post(
            reverse('billing:quick_payment'),
            payload,
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        replay = self.client.post(
            reverse('billing:quick_payment'),
            payload,
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.json()['success'])
        self.assertEqual(replay.status_code, 200)
        self.assertTrue(replay.json()['duplicate'])
        self.assertEqual(
            Payment.objects.filter(client=self.client_obj, amount=Decimal('1500')).count(),
            1,
        )
        self.assertEqual(PaymentSubmission.objects.filter(token=token).count(), 1)

    def test_credit_sale_requires_a_registered_customer(self):
        service = ServiceType.objects.create(
            name='Credit Filing Service', category='ura_filing',
        )

        response = self.client.post(reverse('billing:quick_payment'), {
            'service_type': service.pk,
            'amount': '25000',
            'method': 'credit',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(response.status_code, 400)
        self.assertIn('registered customer', response.json()['error'])
        self.assertFalse(Invoice.objects.exists())
        self.assertFalse(Payment.objects.exists())

    def test_credit_sale_creates_receivable_invoice_without_cash_payment(self):
        company = Company.objects.create(name='Credit Sale Co', slug='credit-sale')
        branch = Branch.objects.create(company=company, name='TAXMAN')
        self.user.company = company
        self.user.branch = branch
        self.user.save(update_fields=['company', 'branch'])
        self.client_obj.branch = branch
        self.client_obj.save(update_fields=['branch'])
        service = ServiceType.objects.create(
            name='Credit Filing Service', category='ura_filing',
        )
        service.branches.add(branch)
        business_date = timezone.localdate()

        response = self.client.post(reverse('billing:quick_payment'), {
            'client': self.client_obj.pk,
            'service_type': service.pk,
            'amount': '25000',
            'method': 'credit',
            'payment_date': business_date.isoformat(),
            'reference': 'CREDIT-001',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertIn('No cash payment was recorded', response.json()['message'])
        invoice = Invoice.objects.get(client=self.client_obj)
        self.client_obj.refresh_from_db()
        self.assertTrue(invoice.is_credit_sale)
        self.assertEqual(invoice.service_type, service)
        self.assertEqual(invoice.branch, branch)
        self.assertEqual(invoice.date_issued, business_date)
        self.assertEqual(invoice.due_date, business_date + timezone.timedelta(days=14))
        self.assertEqual(invoice.grand_total, Decimal('25000'))
        self.assertEqual(self.client_obj.total_outstanding, Decimal('25000'))
        self.assertFalse(Payment.objects.exists())
        self.assertFalse(BranchDailyTransaction.objects.exists())

        report = self.client.get(reverse('documents:financial_reports'), {
            'period': 'this_month',
            'branch': branch.pk,
        })
        self.assertEqual(report.context['accounts_receivable'], Decimal('25000'))
        self.assertEqual(report.context['cash_inflow'], Decimal('0'))
        self.assertEqual(list(report.context['transactions'])[0]['type_key'], 'credit')

    def test_external_credit_sale_updates_receivable_without_ledger_cash(self):
        company = Company.objects.create(
            name='External Credit Co', slug='external-credit',
        )
        branch = Branch.objects.create(
            company=company, name='ABA UGANDA', external_reporting=True,
        )
        self.user.company = company
        self.user.branch = branch
        self.user.save(update_fields=['company', 'branch'])
        self.client_obj.branch = branch
        self.client_obj.save(update_fields=['branch'])
        service = ServiceType.objects.create(
            name='External Credit Filing', category='ura_filing',
        )
        service.branches.add(branch)

        response = self.client.post(reverse('billing:quick_payment'), {
            'client': self.client_obj.pk,
            'service_type': service.pk,
            'amount': '15000',
            'method': 'credit',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertTrue(Invoice.objects.get().is_credit_sale)
        self.assertFalse(Payment.objects.exists())
        self.assertFalse(BranchDailyTransaction.objects.exists())
        report = self.client.get(reverse('documents:financial_reports'), {
            'period': 'this_month',
            'branch': branch.pk,
        })
        self.assertEqual(report.context['accounts_receivable'], Decimal('15000'))
        self.assertEqual(report.context['cash_inflow'], Decimal('0'))

    def test_capital_injection_is_recorded_separately_from_payment(self):
        company = Company.objects.create(name='Capital Injection Co', slug='capital-injection')
        branch = Branch.objects.create(company=company, name='TAXMAN')
        self.user.company = company
        self.user.branch = branch
        self.user.save(update_fields=['company', 'branch'])

        response = self.client.post(reverse('billing:quick_payment'), {
            'amount': '40000',
            'method': 'bank_transfer',
            'service_type': 'capital_injection',
            'payment_date': timezone.localdate().isoformat(),
            'reference': 'CAP-001',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        income = OtherIncome.objects.get(reference='CAP-001')
        self.assertEqual(income.category, 'capital_injection')
        self.assertEqual(income.branch, branch)
        self.assertEqual(income.amount, Decimal('40000'))
        self.assertFalse(Payment.objects.exists())

    def test_external_capital_injection_flows_to_the_branch_ledger(self):
        company = Company.objects.create(
            name='External Capital Co', slug='external-capital',
        )
        branch = Branch.objects.create(
            company=company, name='ABA UGANDA', external_reporting=True,
        )
        self.user.company = company
        self.user.branch = branch
        self.user.save(update_fields=['company', 'branch'])
        self.client_obj.branch = branch
        self.client_obj.save(update_fields=['branch'])

        response = self.client.post(reverse('billing:quick_payment'), {
            'client': self.client_obj.pk,
            'amount': '40000',
            'method': 'mobile_money',
            'service_type': 'capital_injection',
            'payment_date': timezone.localdate().isoformat(),
            'reference': 'ABA-CAP-001',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        entry = BranchDailyTransaction.objects.get(reference='ABA-CAP-001')
        self.assertEqual(entry.branch, branch)
        self.assertEqual(entry.direction, 'inflow')
        self.assertEqual(entry.category, 'capital_injection')
        self.assertEqual(entry.account, 'mobile_money')
        self.assertEqual(entry.amount, Decimal('40000'))
        self.assertFalse(Payment.objects.exists())
        self.assertFalse(OtherIncome.objects.exists())

    def test_anonymous_payment_is_recorded_under_shared_walkin_customer(self):
        response = self.client.post(reverse('billing:quick_payment'), {
            'amount': '12500',
            'method': 'cash',
            'payment_date': '2026-11-16',
            'reference': 'walkin-cash',
        })

        walkin = Client.objects.get(full_name='Walk-in Customers')
        payment = Payment.objects.get(reference='walkin-cash')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('clients:detail', args=[walkin.pk]))
        self.assertIsNone(payment.invoice)
        self.assertEqual(payment.client, walkin)
        self.assertEqual(payment.amount, Decimal('12500'))
        self.assertEqual(payment.received_by, self.user)

    def test_payment_popover_endpoint_returns_form_fragment(self):
        response = self.client.get(reverse('billing:quick_payment'), {'popover': '1'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'quickPaymentPanel')
        self.assertContains(response, 'quickCustomerPanel')
        self.assertNotContains(response, '<html')

    def test_ajax_payment_submission_returns_success_json(self):
        response = self.client.post(reverse('billing:quick_payment'), {
            'amount': '2500',
            'method': 'cash',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(Payment.objects.get().client.full_name, 'Walk-in Customers')

    def test_existing_anonymous_client_payment_uses_shared_walkin_customer(self):
        anonymous_client = Client.objects.create(
            full_name='Anonymous Customer',
            phone_primary='N/A',
            created_by=self.user,
        )

        self.client.post(reverse('billing:quick_payment'), {
            'client': anonymous_client.pk,
            'amount': '5000',
            'method': 'mobile_money',
        })

        payment = Payment.objects.get()
        self.assertEqual(payment.client.full_name, 'Walk-in Customers')
        self.assertNotEqual(payment.client, anonymous_client)

    def test_quick_payment_is_associated_with_selected_named_client(self):
        response = self.client.post(reverse('billing:quick_payment'), {
            'client': self.client_obj.pk,
            'amount': '7500',
            'method': 'bank_transfer',
        })

        payment = Payment.objects.get()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(payment.client, self.client_obj)
        self.assertIsNone(payment.invoice)

    def test_external_branch_quick_payment_is_saved_and_added_to_daily_entries(self):
        company = Company.objects.create(name='External Quick Pay Co', slug='external-quick-pay')
        branch = Branch.objects.create(
            company=company, name='ABA UGANDA', external_reporting=True,
        )
        self.user.company = company
        self.user.branch = branch
        self.user.save(update_fields=['company', 'branch'])
        self.client_obj.branch = branch
        self.client_obj.save(update_fields=['branch'])
        service = ServiceType.objects.create(
            name='External Tax Filing', category='ura_filing',
        )
        service.branches.add(branch)
        invoice = Invoice.objects.create(
            client=self.client_obj, branch=branch,
            due_date=timezone.localdate(), subtotal=Decimal('500'),
            grand_total=Decimal('500'), status='sent', created_by=self.user,
        )
        business_date = timezone.localdate()

        response = self.client.post(reverse('billing:quick_payment'), {
            'client': self.client_obj.pk,
            'service_type': service.pk,
            'amount': '750',
            'method': 'mobile_money',
            'payment_date': business_date.isoformat(),
            'reference': 'ABA-QP-001',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertIn('Added to Branch Daily Entries', response.json()['message'])
        self.assertCountEqual(
            Payment.objects.filter(client=self.client_obj).values_list('amount', flat=True),
            [Decimal('500'), Decimal('250')],
        )
        transaction_entry = BranchDailyTransaction.objects.get(
            branch=branch, business_date=business_date,
        )
        self.assertEqual(transaction_entry.direction, 'inflow')
        self.assertEqual(transaction_entry.category, 'service_receipt')
        self.assertEqual(transaction_entry.account, 'mobile_money')
        self.assertEqual(transaction_entry.amount, Decimal('750'))
        self.assertEqual(transaction_entry.reference, 'ABA-QP-001')
        self.assertIn(self.client_obj.full_name, transaction_entry.description)
        self.assertIn(service.name, transaction_entry.description)

        ledger_response = self.client.get(reverse('documents:branch_daily_ledger'), {
            'branch': branch.pk,
            'date': business_date.isoformat(),
        })
        self.assertEqual(ledger_response.status_code, 200)
        self.assertEqual(ledger_response.context['total_inflow'], Decimal('750'))
        self.assertEqual(ledger_response.context['transactions'].paginator.count, 1)

        summary_response = self.client.get(reverse('documents:branch_daily_summaries'), {
            'branch': branch.pk,
            'date': business_date.isoformat(),
            'open': 'summary',
        })
        self.assertEqual(
            summary_response.context['form']['cash_inflow'].value(),
            Decimal('750'),
        )

    def test_external_branch_quick_payment_respects_reviewed_day_lock(self):
        company = Company.objects.create(name='Locked Quick Pay Co', slug='locked-quick-pay')
        branch = Branch.objects.create(
            company=company, name='PRIME FOCUS', external_reporting=True,
        )
        self.user.company = company
        self.user.branch = branch
        self.user.save(update_fields=['company', 'branch'])
        self.client_obj.branch = branch
        self.client_obj.save(update_fields=['branch'])
        business_date = timezone.localdate()
        BranchDailySummary.objects.create(
            branch=branch, business_date=business_date,
            opening_balance=Decimal('0'), cash_inflow=Decimal('0'),
            cash_outflow=Decimal('0'), closing_balance=Decimal('0'),
            submitted_by=self.user, reviewed_by=self.user,
            reviewed_at=timezone.now(),
        )

        response = self.client.post(reverse('billing:quick_payment'), {
            'client': self.client_obj.pk,
            'amount': '750',
            'method': 'cash',
            'payment_date': business_date.isoformat(),
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(response.status_code, 400)
        self.assertIn('reviewed and locked', response.json()['error'])
        self.assertFalse(Payment.objects.exists())
        self.assertFalse(BranchDailyTransaction.objects.exists())

    def test_quick_payment_allocates_to_oldest_invoices_and_reconciles_client_balance(self):
        company = Company.objects.create(name='Quick Pay Co', slug='quick-pay')
        branch = Branch.objects.create(company=company, name='TAXMAN')
        self.user.company = company
        self.user.branch = branch
        self.user.save(update_fields=['company', 'branch'])
        self.client_obj.branch = branch
        self.client_obj.save(update_fields=['branch'])
        service = ServiceType.objects.create(
            name='Tax Filing', category='ura_filing', default_price=Decimal('1000'),
        )
        service.branches.add(branch)
        older = Invoice.objects.create(
            client=self.client_obj, branch=branch,
            due_date=timezone.localdate(), subtotal=Decimal('1000'),
            grand_total=Decimal('1000'), status='sent', created_by=self.user,
        )
        newer = Invoice.objects.create(
            client=self.client_obj, branch=branch,
            due_date=timezone.localdate(), subtotal=Decimal('1000'),
            grand_total=Decimal('1000'), status='sent', created_by=self.user,
        )

        response = self.client.post(reverse('billing:quick_payment'), {
            'client': self.client_obj.pk,
            'service_type': service.pk,
            'amount': '1500',
            'method': 'cash',
            'reference': 'quick-invoice-pay',
        })

        older.refresh_from_db()
        newer.refresh_from_db()
        self.client_obj.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(older.amount_paid, Decimal('1000'))
        self.assertEqual(newer.amount_paid, Decimal('500'))
        self.assertEqual(self.client_obj.total_outstanding, Decimal('500'))
        self.assertEqual(
            list(Payment.objects.order_by('invoice_id').values_list('invoice_id', 'amount')),
            [(older.pk, Decimal('1000')), (newer.pk, Decimal('500'))],
        )
        self.assertTrue(Payment.objects.filter(service_type=service).exists())

    def test_quick_payment_keeps_overpayment_as_unapplied_client_credit(self):
        invoice = Invoice.objects.create(
            client=self.client_obj,
            due_date=timezone.localdate(),
            subtotal=Decimal('1000'),
            grand_total=Decimal('1000'),
            status='sent',
            created_by=self.user,
        )

        self.client.post(reverse('billing:quick_payment'), {
            'client': self.client_obj.pk,
            'amount': '1250',
            'method': 'cash',
            'reference': 'quick-credit',
        })

        invoice.refresh_from_db()
        self.client_obj.refresh_from_db()
        credit = Payment.objects.get(client=self.client_obj, invoice__isnull=True)
        self.assertEqual(invoice.amount_paid, Decimal('1000'))
        self.assertEqual(invoice.balance_due, Decimal('0'))
        self.assertEqual(self.client_obj.total_outstanding, Decimal('0'))
        self.assertEqual(credit.amount, Decimal('250'))

        response = self.client.get(reverse('clients:detail', args=[self.client_obj.pk]))
        self.assertEqual(response.context['unapplied_payment_total'], Decimal('250'))

    def test_quick_service_creation_adds_service_to_selected_branch_catalogue(self):
        company = Company.objects.create(name='Service Quick Co', slug='service-quick')
        branch = Branch.objects.create(company=company, name='PRIME FOCUS')
        self.user.company = company
        self.user.branch = branch
        self.user.save(update_fields=['company', 'branch'])

        category_response = self.client.post(
            reverse('services:service_category_quick_create'),
            {'name': 'Printing Support'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(category_response.status_code, 200)
        category = ServiceCategory.objects.get(name='Printing Support')
        duplicate_response = self.client.post(
            reverse('services:service_category_quick_create'),
            {'name': 'printing support'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(duplicate_response.status_code, 200)
        self.assertTrue(duplicate_response.json()['existing'])
        self.assertEqual(ServiceCategory.objects.count(), 1)
        self.assertIn((category.name, category.name), service_category_choices())
        self.assertIn(
            (category.name, category.name),
            ServiceTypeForm(user=self.user).fields['category'].choices,
        )

        service_data = {
            'name': 'Custom Printing',
            'category': category.name,
            'default_price': '2500',
            'deadline_type': 'none',
            'branches': [branch.pk],
        }
        service_form = ServiceTypeForm(service_data, user=self.user)
        self.assertTrue(
            service_form.fields['category'].valid_value(category.name),
            service_form.fields['category'].choices,
        )
        self.assertTrue(service_form.is_valid(), service_form.errors)
        response = self.client.post(
            reverse('services:service_quick_create'),
            service_data,
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200, response.content)
        service = ServiceType.objects.get(name='Custom Printing')
        self.assertEqual(service.category, category.name)
        self.assertEqual(list(service.branches.all()), [branch])
        self.assertEqual(response.json()['id'], service.pk)

    def test_staff_cannot_add_service_categories(self):
        staff = User.objects.create_user(
            username='category-staff',
            password='pass1234',
            role='tax_officer',
        )
        self.client.force_login(staff)

        response = self.client.post(reverse('services:service_category_quick_create'), {
            'name': 'Restricted Category',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(response.status_code, 403)
        self.assertFalse(ServiceCategory.objects.filter(name='Restricted Category').exists())

    def test_quick_payment_rejects_nonpositive_amount(self):
        response = self.client.post(reverse('billing:quick_payment'), {
            'amount': '0',
            'method': 'cash',
        })

        self.assertRedirects(response, reverse('billing:quick_payment'))
        self.assertFalse(Payment.objects.exists())
        self.assertFalse(Client.objects.filter(full_name='Walk-in Customers').exists())

    def test_quick_payment_rejects_amount_with_more_than_two_decimal_places(self):
        response = self.client.post(reverse('billing:quick_payment'), {
            'amount': '100.001',
            'method': 'cash',
        })

        self.assertRedirects(response, reverse('billing:quick_payment'))
        self.assertFalse(Payment.objects.exists())


class InvoiceNumberingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='billingtester',
            password='pass1234',
            role='admin',
        )
        self.client.force_login(self.user)
        self.client_obj = Client.objects.create(
            full_name='Billing Client',
            phone_primary='+256700333444',
            created_by=self.user,
        )

    def test_invoice_list_groups_related_finance_navigation(self):
        response = self.client.get(reverse('billing:list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'New invoice')
        self.assertContains(response, 'Finance reports')
        self.assertContains(response, 'Payments &amp; Receipts')
        self.assertContains(response, 'Invoice aging')
        self.assertContains(response, 'Bad debts')

    def test_invoice_detail_groups_secondary_header_actions(self):
        invoice = Invoice.objects.create(
            client=self.client_obj,
            due_date=timezone.localdate(),
            subtotal=Decimal('1000'),
            grand_total=Decimal('1000'),
            status='sent',
            created_by=self.user,
        )

        response = self.client.get(reverse('billing:detail', args=[invoice.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'More actions')
        self.assertContains(response, 'Edit invoice')
        self.assertContains(response, 'Delete invoice')
        self.assertContains(response, 'Send WhatsApp')
        self.assertContains(response, 'Print invoice')

    def test_client_lump_sum_payment_clears_oldest_unpaid_invoices(self):
        older = Invoice.objects.create(
            client=self.client_obj,
            due_date=timezone.now().date(),
            subtotal=Decimal('1000'),
            grand_total=Decimal('1000'),
            status='sent',
            created_by=self.user,
        )
        newer = Invoice.objects.create(
            client=self.client_obj,
            due_date=timezone.now().date(),
            subtotal=Decimal('1000'),
            grand_total=Decimal('1000'),
            status='sent',
            created_by=self.user,
        )

        response = self.client.post(reverse('billing:client_pay'), {
            'client': self.client_obj.pk,
            'amount': '1500',
            'method': 'cash',
            'reference': 'bulk-pay',
        })

        self.assertEqual(response.status_code, 302)
        older.refresh_from_db()
        newer.refresh_from_db()
        self.assertEqual(older.amount_paid, Decimal('1000'))
        self.assertEqual(newer.amount_paid, Decimal('500'))
        self.assertEqual(Payment.objects.filter(invoice=older).count(), 1)
        self.assertEqual(Payment.objects.filter(invoice=newer).count(), 1)
        self.assertTrue(Payment.objects.filter(invoice=older, client=self.client_obj).exists())
        self.assertTrue(Payment.objects.filter(invoice=newer, client=self.client_obj).exists())

    def test_client_payment_can_target_only_selected_pending_invoices(self):
        selected = Invoice.objects.create(
            client=self.client_obj,
            due_date=timezone.now().date(),
            subtotal=Decimal('1000'),
            grand_total=Decimal('1000'),
            status='sent',
            created_by=self.user,
        )
        unselected = Invoice.objects.create(
            client=self.client_obj,
            due_date=timezone.now().date(),
            subtotal=Decimal('2000'),
            grand_total=Decimal('2000'),
            status='sent',
            created_by=self.user,
        )

        response = self.client.post(reverse('billing:client_pay'), {
            'client': self.client_obj.pk,
            'invoice_ids': [selected.pk],
            'amount': '1000',
            'method': 'cash',
            'reference': 'selected-only',
        })

        self.assertEqual(response.status_code, 302)
        selected.refresh_from_db()
        unselected.refresh_from_db()
        self.assertEqual(selected.amount_paid, Decimal('1000'))
        self.assertEqual(unselected.amount_paid, Decimal('0'))

    def test_client_overpayment_is_recorded_as_unapplied_credit(self):
        invoice = Invoice.objects.create(
            client=self.client_obj,
            due_date=timezone.now().date(),
            subtotal=Decimal('1000'),
            grand_total=Decimal('1000'),
            status='sent',
            created_by=self.user,
        )

        response = self.client.post(reverse('billing:client_pay'), {
            'client': self.client_obj.pk,
            'amount': '1500',
            'method': 'cash',
            'reference': 'overpay',
        })

        self.assertEqual(response.status_code, 302)
        invoice.refresh_from_db()
        self.client_obj.refresh_from_db()
        self.assertEqual(invoice.amount_paid, Decimal('1000'))
        self.assertEqual(invoice.balance_due, Decimal('0'))
        self.assertEqual(self.client_obj.total_outstanding, Decimal('0'))
        self.assertEqual(Payment.objects.filter(invoice=invoice).count(), 1)
        self.assertEqual(
            Payment.objects.get(client=self.client_obj, invoice__isnull=True).amount,
            Decimal('500'),
        )

    def test_payment_on_current_invoice_can_clear_older_unpaid_invoices(self):
        older = Invoice.objects.create(
            client=self.client_obj,
            due_date=timezone.now().date(),
            subtotal=Decimal('1000'),
            grand_total=Decimal('1000'),
            status='sent',
            created_by=self.user,
        )
        newer = Invoice.objects.create(
            client=self.client_obj,
            due_date=timezone.now().date(),
            subtotal=Decimal('1000'),
            grand_total=Decimal('1000'),
            status='sent',
            created_by=self.user,
        )

        response = self.client.post(reverse('billing:pay', args=[newer.pk]), {
            'amount': '1500',
            'method': 'cash',
            'reference': 'current-pay',
        })

        self.assertEqual(response.status_code, 302)
        older.refresh_from_db()
        newer.refresh_from_db()
        self.assertEqual(older.amount_paid, Decimal('1000'))
        self.assertEqual(newer.amount_paid, Decimal('500'))
        self.assertEqual(Payment.objects.filter(invoice=older).count(), 1)
        self.assertEqual(Payment.objects.filter(invoice=newer).count(), 1)

    def test_record_payment_parses_posted_date_before_creating_receipt(self):
        invoice = Invoice.objects.create(
            client=self.client_obj,
            due_date=timezone.localdate(),
            subtotal=Decimal('1000'),
            grand_total=Decimal('1000'),
            status='sent',
            created_by=self.user,
        )
        self.client_obj.email = 'receipts@example.test'
        self.client_obj.save(update_fields=['email'])

        with patch('core.email_utils.send_email') as send_email:
            response = self.client.post(reverse('billing:pay', args=[invoice.pk]), {
                'amount': '1000',
                'method': 'cash',
                'payment_date': '2026-11-17',
            })

        payment = Payment.objects.get(invoice=invoice)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(payment.payment_date.isoformat(), '2026-11-17')
        self.assertIn('RCT-2026', send_email.call_args.kwargs['subject'])

    def test_repeated_invoice_payment_submission_records_payment_once(self):
        invoice = Invoice.objects.create(
            client=self.client_obj,
            due_date=timezone.localdate(),
            subtotal=Decimal('1000'),
            grand_total=Decimal('1000'),
            status='sent',
            created_by=self.user,
        )
        token = str(uuid4())
        payload = {
            'payment_submission_token': token,
            'amount': '1000',
            'method': 'cash',
            'payment_date': timezone.localdate().isoformat(),
        }

        first = self.client.post(reverse('billing:pay', args=[invoice.pk]), payload)
        replay = self.client.post(reverse('billing:pay', args=[invoice.pk]), payload)

        self.assertEqual(first.status_code, 302)
        self.assertEqual(replay.status_code, 302)
        self.assertEqual(Payment.objects.filter(invoice=invoice).count(), 1)
        self.assertEqual(PaymentSubmission.objects.filter(token=token).count(), 1)

    def test_recorded_payment_feeds_the_branch_daily_ledger(self):
        company = Company.objects.create(name='Payment Ledger Co', slug='payment-ledger')
        branch = Branch.objects.create(company=company, name='TAXMAN')
        self.user.company = company
        self.user.branch = branch
        self.user.is_superuser = True
        self.user.save(update_fields=['company', 'branch', 'is_superuser'])
        self.client_obj.branch = branch
        self.client_obj.save(update_fields=['branch'])
        business_date = timezone.localdate()
        invoice = Invoice.objects.create(
            client=self.client_obj,
            due_date=business_date,
            subtotal=Decimal('1000'),
            grand_total=Decimal('1000'),
            status='sent',
            created_by=self.user,
        )

        response = self.client.post(reverse('billing:pay', args=[invoice.pk]), {
            'amount': '400',
            'method': 'cash',
            'payment_date': business_date.isoformat(),
        })

        payment = Payment.objects.get(invoice=invoice)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(payment.branch, branch)

        ledger_response = self.client.get(reverse('documents:branch_daily_ledger'), {
            'branch': branch.pk,
            'date': business_date.isoformat(),
        })

        self.assertEqual(ledger_response.status_code, 200)
        self.assertEqual(ledger_response.context['transactions'].paginator.count, 1)
        self.assertEqual(ledger_response.context['total_inflow'], Decimal('400'))
        self.assertContains(ledger_response, invoice.invoice_number)

    def test_payment_does_not_allocate_to_another_branch_invoice(self):
        company = Company.objects.create(name='Branch Payment Co', slug='branch-payment')
        current_branch = Branch.objects.create(company=company, name='TAXMAN')
        other_branch = Branch.objects.create(company=company, name='PRIME FOCUS')
        self.user.company = company
        self.user.branch = current_branch
        self.user.save(update_fields=['company', 'branch'])
        self.client_obj.branch = current_branch
        self.client_obj.save(update_fields=['branch'])

        older_other_branch_invoice = Invoice.objects.create(
            client=self.client_obj,
            branch=other_branch,
            due_date=timezone.now().date(),
            subtotal=Decimal('1000'),
            grand_total=Decimal('1000'),
            status='sent',
            created_by=self.user,
        )
        current_branch_invoice = Invoice.objects.create(
            client=self.client_obj,
            branch=current_branch,
            due_date=timezone.now().date(),
            subtotal=Decimal('1000'),
            grand_total=Decimal('1000'),
            status='sent',
            created_by=self.user,
        )
        session = self.client.session
        session['active_branch_id'] = str(current_branch.pk)
        session.save()

        response = self.client.post(reverse('billing:pay', args=[current_branch_invoice.pk]), {
            'amount': '1500',
            'method': 'cash',
            'reference': 'branch-scoped-payment',
        })

        self.assertEqual(response.status_code, 302)
        older_other_branch_invoice.refresh_from_db()
        current_branch_invoice.refresh_from_db()
        self.assertEqual(older_other_branch_invoice.amount_paid, Decimal('0'))
        self.assertEqual(current_branch_invoice.amount_paid, Decimal('1000'))
        self.assertEqual(
            Payment.objects.get(client=self.client_obj, invoice__isnull=True).amount,
            Decimal('500'),
        )

    def test_manual_invoice_uses_next_highest_existing_number(self):
        year = timezone.now().year
        older = Invoice.objects.create(
            client=self.client_obj,
            due_date=timezone.now().date(),
            subtotal=Decimal('1000'),
            grand_total=Decimal('1000'),
            created_by=self.user,
        )
        newer = Invoice.objects.create(
            client=self.client_obj,
            due_date=timezone.now().date(),
            subtotal=Decimal('2000'),
            grand_total=Decimal('2000'),
            created_by=self.user,
        )

        Invoice.objects.filter(pk=older.pk).update(invoice_number=f'INV-{year}-0010')
        Invoice.objects.filter(pk=newer.pk).update(invoice_number=f'INV-{year}-0002')

        response = self.client.post(reverse('billing:create'), {
            'client': self.client_obj.pk,
            'description': 'Manual invoice regression',
            'amount': '3500',
            'due_date': '',
        })

        self.assertEqual(response.status_code, 302)
        created = Invoice.objects.exclude(pk__in=[older.pk, newer.pk]).get()
        self.assertEqual(created.invoice_number, f'INV-{year}-0011')

    def test_convert_to_invoice_uses_safe_next_number(self):
        year = timezone.now().year
        existing_invoice = Invoice.objects.create(
            client=self.client_obj,
            due_date=timezone.now().date(),
            subtotal=Decimal('3000'),
            grand_total=Decimal('3000'),
            created_by=self.user,
        )
        quotation = Invoice.objects.create(
            client=self.client_obj,
            document_type='quotation',
            due_date=timezone.now().date(),
            subtotal=Decimal('4000'),
            grand_total=Decimal('4000'),
            status='draft',
            created_by=self.user,
        )

        Invoice.objects.filter(pk=existing_invoice.pk).update(invoice_number=f'INV-{year}-0007')
        Invoice.objects.filter(pk=quotation.pk).update(invoice_number=f'QUO-{year}-0003')

        response = self.client.post(reverse('billing:convert', args=[quotation.pk]))

        self.assertEqual(response.status_code, 302)
        quotation.refresh_from_db()
        self.assertEqual(quotation.document_type, 'invoice')
        self.assertEqual(quotation.invoice_number, f'INV-{year}-0008')


class PaymentReceiptReportTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name='Receipts Company',
            slug='receipts-company',
        )
        self.branch = Branch.objects.create(
            company=self.company,
            name='TAXMAN',
        )
        self.user = User.objects.create_user(
            username='receiptsadmin',
            password='pass1234',
            role='admin',
            company=self.company,
        )
        self.client.force_login(self.user)
        self.customer = Client.objects.create(
            full_name='Searchable Customer',
            phone_primary='+256700555000',
            created_by=self.user,
            branch=self.branch,
        )
        self.other_customer = Client.objects.create(
            full_name='Other Customer',
            phone_primary='+256700555001',
            created_by=self.user,
            branch=self.branch,
        )
        self.service = ServiceType.objects.create(
            name='Searchable Service',
            category='ura_filing',
        )
        self.service.branches.add(self.branch)
        self.payment_date = timezone.localdate()
        self.payment = Payment.objects.create(
            client=self.customer,
            service_type=self.service,
            branch=self.branch,
            amount=Decimal('1234.50'),
            method='cash',
            payment_date=self.payment_date,
            reference='receipt-reference-123',
            received_by=self.user,
        )

    def test_receipt_report_filters_and_summarizes_matching_payments(self):
        other_service = ServiceType.objects.create(
            name='Other Service',
            category='ura_filing',
        )
        other_service.branches.add(self.branch)
        other_payment = Payment.objects.create(
            client=self.other_customer,
            service_type=other_service,
            branch=self.branch,
            amount=Decimal('900'),
            method='bank_transfer',
            payment_date=self.payment_date,
            received_by=self.user,
        )

        response = self.client.get(reverse('billing:payments_report'), {
            'search': self.payment.receipt_number,
            'date_from': self.payment_date.isoformat(),
            'date_to': self.payment_date.isoformat(),
            'client': self.customer.pk,
            'service_type': self.service.pk,
            'method': 'cash',
            'branch': self.branch.pk,
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['record_count'], 1)
        self.assertEqual(response.context['total_amount'], Decimal('1234.50'))
        self.assertContains(response, self.payment.receipt_number)
        self.assertNotContains(response, other_payment.receipt_number)
        self.assertContains(response, 'Searchable Customer')
        self.assertContains(response, 'class="form-control s2"')
        self.assertContains(
            response,
            reverse('billing:payment_receipt', args=[self.payment.pk]),
        )

    def test_payment_receipt_can_be_viewed_and_downloaded_with_branch_branding(self):
        logo_content = BytesIO()
        Image.new('RGB', (32, 24), color='teal').save(logo_content, format='PNG')
        receipt_url = reverse('billing:payment_receipt', args=[self.payment.pk])

        with TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                self.branch.logo.save(
                    'branch-logo.png',
                    ContentFile(logo_content.getvalue()),
                    save=True,
                )
                response = self.client.get(receipt_url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, self.company.name)
                self.assertContains(response, self.branch.logo.url)
                self.assertContains(response, self.payment.receipt_number)

                pdf_response = self.client.get(receipt_url, {'format': 'pdf'})
                self.assertEqual(pdf_response.status_code, 200)
                self.assertEqual(pdf_response['Content-Type'], 'application/pdf')
                self.assertIn(b'%PDF-', pdf_response.content[:10])
                self.assertIn('attachment;', pdf_response['Content-Disposition'])

    def test_payment_receipt_obeys_active_branch_scope(self):
        other_branch = Branch.objects.create(
            company=self.company,
            name='Other Branch',
        )
        other_payment = Payment.objects.create(
            client=self.other_customer,
            branch=other_branch,
            amount=Decimal('500'),
            method='cash',
            payment_date=self.payment_date,
            received_by=self.user,
        )
        session = self.client.session
        session['active_branch_id'] = str(self.branch.pk)
        session.save()

        response = self.client.get(
            reverse('billing:payment_receipt', args=[other_payment.pk]),
        )

        self.assertEqual(response.status_code, 404)

    def test_invalid_date_range_does_not_show_unfiltered_payments(self):
        response = self.client.get(reverse('billing:payments_report'), {
            'date_from': '2026-11-19',
            'date_to': '2026-11-18',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['record_count'], 0)
        self.assertContains(response, 'The end date must be on or after the start date.')
        self.assertNotContains(response, self.payment.receipt_number)

    def test_receipt_report_respects_active_branch_workspace(self):
        other_branch = Branch.objects.create(
            company=self.company,
            name='PRIME FOCUS',
        )
        other_payment = Payment.objects.create(
            client=self.other_customer,
            branch=other_branch,
            amount=Decimal('500'),
            method='cash',
            payment_date=self.payment_date,
            received_by=self.user,
        )
        session = self.client.session
        session['active_branch_id'] = str(self.branch.pk)
        session.save()

        response = self.client.get(reverse('billing:payments_report'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['record_count'], 1)
        self.assertContains(response, self.payment.receipt_number)
        self.assertNotContains(response, other_payment.receipt_number)
