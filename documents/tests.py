from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from billing.models import Invoice, Payment
from clients.models import Client
from core.models import User


class DocumentReportsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='reporttester',
            password='pass1234',
            role='admin',
        )
        self.client.force_login(self.user)
        self.client_obj = Client.objects.create(
            full_name='Reporting Client',
            phone_primary='+256700000010',
            created_by=self.user,
        )

    def test_monthly_report_uses_payment_date_for_collections(self):
        # Use a far-future month to avoid polluted test database values.
        invoice_old = Invoice.objects.create(
            client=self.client_obj,
            due_date=date(2099, 3, 1),
            subtotal=Decimal('1000'),
            vat_total=Decimal('0'),
            grand_total=Decimal('1000'),
            date_issued=date(2099, 1, 10),
            status='sent',
            created_by=self.user,
        )
        pay_old = Payment.objects.create(
            invoice=invoice_old,
            amount=Decimal('500'),
            received_by=self.user,
        )
        Payment.objects.filter(pk=pay_old.pk).update(payment_date=date(2099, 2, 10))

        invoice_current = Invoice.objects.create(
            client=self.client_obj,
            due_date=date(2099, 3, 1),
            subtotal=Decimal('2000'),
            vat_total=Decimal('0'),
            grand_total=Decimal('2000'),
            status='sent',
            created_by=self.user,
        )
        Invoice.objects.filter(pk=invoice_current.pk).update(date_issued=date(2099, 2, 5))
        invoice_current.refresh_from_db()
        pay_current = Payment.objects.create(
            invoice=invoice_current,
            amount=Decimal('2500'),
            received_by=self.user,
        )
        Payment.objects.filter(pk=pay_current.pk).update(payment_date=date(2099, 2, 15))

        response = self.client.get(reverse('documents:monthly_report'), {
            'month': '2',
            'year': '2099',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_invoiced'], Decimal('2000'))
        self.assertEqual(response.context['total_collected'], Decimal('3000'))

    def test_audit_books_uses_payment_date_for_yearly_collections(self):
        invoice_current = Invoice.objects.create(
            client=self.client_obj,
            due_date=date(2025, 3, 1),
            subtotal=Decimal('2000'),
            vat_total=Decimal('0'),
            grand_total=Decimal('2000'),
            status='sent',
            created_by=self.user,
        )
        Invoice.objects.filter(pk=invoice_current.pk).update(date_issued=date(2025, 2, 5))
        invoice_current.refresh_from_db()

        invoice_old = Invoice.objects.create(
            client=self.client_obj,
            due_date=date(2024, 2, 1),
            subtotal=Decimal('1000'),
            vat_total=Decimal('0'),
            grand_total=Decimal('1000'),
            status='sent',
            created_by=self.user,
        )
        Invoice.objects.filter(pk=invoice_old.pk).update(date_issued=date(2024, 1, 10))
        invoice_old.refresh_from_db()

        pay_current = Payment.objects.create(
            invoice=invoice_current,
            amount=Decimal('2000'),
            received_by=self.user,
        )
        Payment.objects.filter(pk=pay_current.pk).update(payment_date=date(2025, 2, 15))

        pay_old = Payment.objects.create(
            invoice=invoice_old,
            amount=Decimal('500'),
            received_by=self.user,
        )
        Payment.objects.filter(pk=pay_old.pk).update(payment_date=date(2025, 2, 18))

        response = self.client.get(reverse('documents:audit_books'), {
            'year': '2025',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_revenue'], Decimal('2000'))
        self.assertEqual(response.context['total_collected'], Decimal('2500'))
