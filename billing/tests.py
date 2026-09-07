from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from billing.models import Invoice, Payment
from clients.models import Client
from core.models import User


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

    def test_client_overpayment_updates_negative_client_balance(self):
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
        self.assertEqual(invoice.amount_paid, Decimal('1500'))
        self.assertEqual(invoice.balance_due, Decimal('-500'))
        self.assertEqual(self.client_obj.total_outstanding, Decimal('-500'))
        self.assertEqual(Payment.objects.filter(invoice=invoice).count(), 2)

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
