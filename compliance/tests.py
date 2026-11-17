from django.test import TestCase
from django.urls import reverse
from datetime import date
from decimal import Decimal

from billing.models import Invoice, Payment
from clients.models import Client
from core.models import Branch, Company, User
from services.models import JobCard, ServiceType
from .models import ComplianceDeadline, ComplianceObligation


class ExternalBranchComplianceTests(TestCase):
    def setUp(self):
        company = Company.objects.create(name='Compliance Branch Co', slug='compliance-branch')
        self.branch = Branch.objects.create(
            company=company, name='PRIME FOCUS', external_reporting=True,
        )
        self.manager = User.objects.create_user(
            username='compliance_manager', password='pass1234',
            role='manager', company=company, branch=self.branch,
        )
        self.client_obj = Client.objects.create(
            full_name='Prime Client', phone_primary='+256700300001',
            created_by=self.manager, branch=self.branch,
        )
        service = ServiceType.objects.create(
            name='URA Filing', category='ura_filing', default_price=Decimal('50000'),
        )
        obligation = ComplianceObligation.objects.create(
            client=self.client_obj, service_type=service,
        )
        self.deadline = ComplianceDeadline.objects.create(
            obligation=obligation, period_label='January 2099',
            due_date=date(2099, 2, 15),
        )
        self.client.force_login(self.manager)

    def test_external_branch_compliance_status_does_not_create_internal_transactions(self):
        response = self.client.post(reverse(
            'compliance:update_status',
            args=[self.deadline.pk, 'filed_and_paid'],
        ))

        self.assertEqual(response.status_code, 302)
        self.deadline.refresh_from_db()
        self.assertEqual(self.deadline.status, 'filed_and_paid')
        self.assertFalse(JobCard.objects.exists())
        self.assertFalse(Invoice.objects.exists())
        self.assertFalse(Payment.objects.exists())

    def test_manager_cannot_update_another_branch_deadline(self):
        other_branch = Branch.objects.create(
            company=self.branch.company, name='ABA UGANDA', external_reporting=True,
        )
        other_client = Client.objects.create(
            full_name='ABA Client', phone_primary='+256700300002',
            branch=other_branch,
        )
        service = self.deadline.obligation.service_type
        obligation = ComplianceObligation.objects.create(
            client=other_client, service_type=service,
        )
        other_deadline = ComplianceDeadline.objects.create(
            obligation=obligation, period_label='January 2099',
            due_date=date(2099, 2, 15),
        )

        response = self.client.post(reverse(
            'compliance:update_status',
            args=[other_deadline.pk, 'filed_and_paid'],
        ))

        self.assertEqual(response.status_code, 404)
