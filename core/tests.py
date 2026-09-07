import sys
from decimal import Decimal
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
import core

from billing.models import Invoice
from services.models import JobCard, StaffActivityLog
from core.models import TransactionEditLog
from billing.models import Payment, OtherIncome
from expenses.models import Expense, ExpenseCategory
from services.models import ClientServiceSubscription, ServiceType
from core.jobs import generate_monthly_jobcards
from clients.models import Client
from core.apps import CoreConfig
from core.models import User, ModelVisibility, UserModelPermission, SystemModuleVisibility, Company, AuditLog
from core.utils import is_model_visible, user_can_view_model, user_can_edit_model


class CoreVisibilityTests(TestCase):
    def setUp(self):
        self.client_ct = ContentType.objects.get_for_model(Client)
        self.user = User.objects.create_user(username='testuser', password='pass123', is_staff=True)

    def test_is_model_visible_defaults_true(self):
        self.assertTrue(is_model_visible(Client))

    def test_is_model_visible_disabled(self):
        ModelVisibility.objects.create(content_type=self.client_ct, enabled=False)
        self.assertFalse(is_model_visible(Client))

    def test_user_can_view_model_with_permission(self):
        UserModelPermission.objects.create(
            user=self.user,
            content_type=self.client_ct,
            can_view=False,
            can_edit=True,
        )
        self.assertFalse(user_can_view_model(self.user, Client))
        self.assertTrue(user_can_edit_model(self.user, Client))

    def test_user_can_edit_model_defaults_to_staff(self):
        self.assertTrue(user_can_edit_model(self.user, Client))

    def test_user_can_view_model_superuser(self):
        admin = User.objects.create_superuser(username='admin', password='pass123', email='admin@example.com')
        self.assertTrue(user_can_view_model(admin, Client))
        self.assertTrue(user_can_edit_model(admin, Client))


class SchedulerStartupTests(TestCase):
    @patch('core.apps.CoreConfig._start_scheduler')
    def test_ready_skips_scheduler_for_management_checks(self, mock_start_scheduler):
        original_argv = sys.argv[:]
        sys.argv = ['manage.py', 'check']
        try:
            config = CoreConfig('core', core)
            config.ready()
        finally:
            sys.argv = original_argv

        mock_start_scheduler.assert_not_called()


class AdminUserAndClientManagementTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='adminuser',
            password='pass123',
            role='admin',
            is_staff=True,
        )
        self.staff = User.objects.create_user(
            username='staffuser',
            password='pass123',
            role='tax_officer',
            is_staff=True,
        )
        self.client_obj = Client.objects.create(
            full_name='Client Account',
            phone_primary='+256700000003',
            created_by=self.admin,
        )

    def test_admin_can_suspend_and_reactivate_client_account(self):
        self.client.force_login(self.admin)

        response = self.client.post(reverse('core:admin_client_suspend', args=[self.client_obj.pk]))
        self.assertEqual(response.status_code, 302)
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.status, 'suspended')

        response = self.client.post(reverse('core:admin_client_reactivate', args=[self.client_obj.pk]))
        self.assertEqual(response.status_code, 302)
        self.client_obj.refresh_from_db()
        self.assertEqual(self.client_obj.status, 'active')

    def test_admin_can_delete_user_account(self):
        self.client.force_login(self.admin)

        response = self.client.post(reverse('core:admin_user_delete', args=[self.staff.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.objects.filter(pk=self.staff.pk).exists())


class AdminControlCenterTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='adminuser',
            password='pass123',
            role='admin',
            is_staff=True,
        )
        self.staff = User.objects.create_user(
            username='staffuser',
            password='pass123',
            role='tax_officer',
            is_staff=True,
        )

    def test_admin_can_open_control_center(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:admin_control_center'))
        self.assertEqual(response.status_code, 200)

    def test_admin_can_toggle_module_visibility(self):
        self.client.force_login(self.admin)
        module = SystemModuleVisibility.objects.create(key='clients', label='Clients', enabled=True)

        response = self.client.post(reverse('core:admin_control_center'), {'module_clients': 'off'})

        self.assertEqual(response.status_code, 302)
        module.refresh_from_db()
        self.assertFalse(module.enabled)

    def test_tenant_admin_controls_are_scoped_to_their_company(self):
        self.client.force_login(self.admin)
        company = Company.objects.create(name='Tenant One', slug='tenant-one')
        self.admin.company = company
        self.admin.save(update_fields=['company'])

        other_company = Company.objects.create(name='Tenant Two', slug='tenant-two')
        other_module = SystemModuleVisibility.objects.create(key='clients', company=other_company, label='Clients', enabled=True)
        tenant_module = SystemModuleVisibility.objects.create(key='clients', company=company, label='Clients', enabled=True)

        response = self.client.post(reverse('core:admin_control_center'), {'module_clients': 'off'})

        self.assertEqual(response.status_code, 302)
        tenant_module.refresh_from_db()
        other_module.refresh_from_db()
        self.assertFalse(tenant_module.enabled)
        self.assertTrue(other_module.enabled)


class TransactionEditPermissionTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='adminuser',
            password='pass123',
            role='admin',
            is_staff=True,
        )
        self.staff = User.objects.create_user(
            username='staffuser',
            password='pass123',
            role='tax_officer',
            is_staff=True,
        )
        self.client_obj = Client.objects.create(
            full_name='Invoice Client',
            phone_primary='+256700000002',
            created_by=self.admin,
        )
        self.invoice = Invoice.objects.create(
            client=self.client_obj,
            due_date=timezone.now().date(),
            subtotal=Decimal('1000'),
            grand_total=Decimal('1000'),
            status='sent',
            created_by=self.admin,
        )

    def test_staff_cannot_access_transaction_edit(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('core:edit_transaction', args=['invoice', self.invoice.pk]))
        self.assertEqual(response.status_code, 403)

    def test_staff_cannot_access_transaction_edit_log(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse('core:transaction_edits'))
        self.assertEqual(response.status_code, 403)

    def test_admin_can_access_transaction_edit(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:edit_transaction', args=['invoice', self.invoice.pk]))
        self.assertEqual(response.status_code, 200)

    def test_admin_can_access_transaction_edit_log(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:transaction_edits'))
        self.assertEqual(response.status_code, 200)

    def test_audit_logs_section_includes_job_activity_and_transaction_edits(self):
        job = JobCard.objects.create(client=self.client_obj, created_by=self.admin)
        StaffActivityLog.objects.create(
            job_card=job,
            staff=self.admin,
            action='Job card created',
        )
        TransactionEditLog.objects.create(
            transaction_type='invoice',
            transaction_id=self.invoice.pk,
            transaction_code='INV-TEST',
            client=self.client_obj,
            reason='Corrected invoice amount',
            edited_by=self.admin,
        )

        self.client.force_login(self.admin)
        response = self.client.get(reverse('core:admin_audit_logs'))

        self.assertEqual(response.status_code, 200)
        model_names = [log['model_name'] for log in response.context['logs']]
        self.assertIn('job_card_activity', model_names)
        self.assertIn('invoice_edit', model_names)

    def test_audit_logs_track_business_records_and_login(self):
        self.client.force_login(self.admin)
        AuditLog.objects.all().delete()
        client = Client.objects.create(
            full_name='Audited Client',
            phone_primary='+256700000099',
            created_by=self.admin,
        )
        category = ExpenseCategory.objects.create(name='Audited Expense')
        Expense.objects.create(
            expense_date=timezone.now().date(),
            category=category,
            description='Audited expense',
            amount=Decimal('1000'),
            created_by=self.admin,
        )
        invoice = Invoice.objects.create(
            client=client,
            due_date=timezone.now().date(),
            grand_total=Decimal('1000'),
            created_by=self.admin,
        )
        Payment.objects.create(invoice=invoice, amount=Decimal('1000'), received_by=self.admin)
        OtherIncome.objects.create(
            source_name='Audited income', amount=Decimal('500'),
            income_date=timezone.now().date(), recorded_by=self.admin,
        )

        self.client.logout()
        self.client.post(reverse('login'), {
            'username': 'adminuser',
            'password': 'pass123',
        })
        response = self.client.get(reverse('core:admin_audit_logs'))

        self.assertEqual(response.status_code, 200)
        model_names = [log['model_name'] for log in response.context['logs']]
        for model_name in ('client', 'expense', 'invoice', 'payment', 'other_income', 'login'):
            self.assertIn(model_name, model_names)

    def test_monthly_job_generation_is_idempotent(self):
        service = ServiceType.objects.create(
            name='Monthly VAT',
            category='ura_filing',
            default_price=Decimal('1000'),
            deadline_type='monthly_15',
            is_recurring=True,
        )
        ClientServiceSubscription.objects.create(
            client=self.client_obj,
            service_type=service,
            negotiated_price=Decimal('1000'),
        )

        generate_monthly_jobcards()
        generate_monthly_jobcards()

        jobs = self.client_obj.job_cards.filter(is_periodic=True)
        self.assertEqual(jobs.count(), 1)
        self.assertEqual(jobs.first().line_items.filter(service_type=service).count(), 1)
