from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from billing.models import Invoice
from clients.models import Client
from core.models import User


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

        response = self.client.post(reverse('billing:create_manual'), {
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
