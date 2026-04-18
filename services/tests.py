from django.test import TestCase
from django.urls import reverse
from decimal import Decimal

from clients.models import Client
from core.models import User
from services.models import JobCard, JobCardLineItem, ServiceType


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
