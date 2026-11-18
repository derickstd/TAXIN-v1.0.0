import sys
from datetime import date, datetime, timezone as datetime_timezone
from decimal import Decimal
from unittest.mock import patch

from django.contrib import admin
from django.contrib.contenttypes.models import ContentType
from django.db import DatabaseError
from django.test import RequestFactory, TestCase, override_settings
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
from core.models import User, ModelVisibility, UserModelPermission, SystemModuleVisibility, Company, Branch, AuditLog
from core.utils import is_model_visible, user_can_view_model, user_can_edit_model
from core.branch_access import scope_queryset
from core.views import UserForm


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

    def test_company_user_can_log_in_without_tenant_database(self):
        company = Company.objects.create(name='TAXMAN', slug='taxman')
        user = User.objects.create_user(
            username='companyuser',
            password='pass1234',
            role='admin',
            company=company,
        )

        response = self.client.post(reverse('login'), {
            'username': user.username,
            'password': 'pass1234',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('dashboard:index'))
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)

    def test_superuser_can_log_in_to_reactivate_a_suspended_company(self):
        company = Company.objects.create(name='TAXMAN', slug='taxman', active=False)
        superuser = User.objects.create_superuser(
            username='rootuser',
            password='pass1234',
            email='rootuser@example.com',
            company=company,
        )

        response = self.client.post(reverse('login'), {
            'username': superuser.username,
            'password': 'pass1234',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('dashboard:index'))

    def test_company_signup_cannot_create_another_company(self):
        Company.objects.create(name='TAXMAN', slug='taxman')

        response = self.client.post(reverse('signup'), {
            'company_name': 'Another Company',
            'slug': 'another-company',
            'username': 'anotheradmin',
            'password1': 'pass1234',
            'password2': 'pass1234',
        })

        self.assertRedirects(response, reverse('login'))
        self.assertEqual(Company.objects.count(), 1)
        self.assertFalse(User.objects.filter(username='anotheradmin').exists())

    def test_django_admin_allows_only_the_initial_company(self):
        request = RequestFactory().get('/admin/')
        company_admin = admin.site._registry[Company]

        self.assertTrue(company_admin.has_add_permission(request))
        Company.objects.create(name='TAXMAN', slug='taxman')
        self.assertFalse(company_admin.has_add_permission(request))
        self.assertFalse(company_admin.has_delete_permission(request))

    def test_company_branch_setup_is_limited_to_the_three_supported_branches(self):
        company = Company.objects.create(name='TAXMAN', slug='taxman')
        admin_user = User.objects.create_superuser(
            username='branchsetupadmin',
            password='pass1234',
            email='branchsetupadmin@example.com',
        )
        self.client.force_login(admin_user)
        url = reverse('core:admin_company_branches', args=[company.pk])

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Create New Branch')

        response = self.client.post(url, {'action': 'setup_business_branches'})
        self.assertRedirects(response, url)
        response = self.client.post(url, {'action': 'setup_business_branches'})
        self.assertRedirects(response, url)
        self.assertCountEqual(
            company.branches.values_list('name', flat=True),
            ['TAXMAN', 'PRIME FOCUS', 'ABA UGANDA'],
        )

        self.client.post(url, {'name': 'UNSUPPORTED BRANCH'})
        self.assertEqual(company.branches.count(), 3)

        branch_admin = admin.site._registry[Branch]
        request = RequestFactory().get('/admin/')
        self.assertFalse(branch_admin.has_add_permission(request))
        self.assertFalse(branch_admin.has_delete_permission(request))

    def test_company_admin_has_a_sidebar_link_to_branch_setup(self):
        company = Company.objects.create(name='TAXMAN', slug='taxman')
        admin_user = User.objects.create_user(
            username='branch-link-admin',
            password='pass1234',
            role='admin',
            company=company,
        )
        self.client.force_login(admin_user)

        response = self.client.get(reverse('core:admin_companies'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Company &amp; Branches')
        self.assertContains(
            response,
            reverse('core:admin_company_branches', args=[company.pk]),
        )

    def test_company_admin_pages_render_without_tenant_workflows(self):
        company = Company.objects.create(name='TAXMAN', slug='taxman')
        Branch.objects.create(company=company, name='TAXMAN')
        admin_user = User.objects.create_superuser(
            username='workspaceadmin',
            password='pass1234',
            email='workspaceadmin@example.com',
        )
        self.client.force_login(admin_user)

        pages = (
            'core:admin_dashboard',
            'core:admin_control_center',
            'core:admin_companies',
            'core:admin_analytics',
            'core:admin_health',
        )
        for page_name in pages:
            with self.subTest(page=page_name):
                response = self.client.get(reverse(page_name))
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, 'Manage Tenants')


class BranchAccessTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Branch Test Co', slug='branch-test')
        self.other_company = Company.objects.create(name='Other Co', slug='other-co')
        self.branch_one = Branch.objects.create(company=self.company, name='Branch One')
        self.branch_two = Branch.objects.create(company=self.company, name='Branch Two')
        self.other_branch = Branch.objects.create(company=self.other_company, name='Other Branch')
        self.client_one = Client.objects.create(
            full_name='Branch One Client', phone_primary='+256700100001',
            branch=self.branch_one,
        )
        self.client_two = Client.objects.create(
            full_name='Branch Two Client', phone_primary='+256700100002',
            branch=self.branch_two,
        )
        self.other_client = Client.objects.create(
            full_name='Other Company Client', phone_primary='+256700100003',
            branch=self.other_branch,
        )
        self.staff = User.objects.create_user(
            username='branchstaff', password='pass1234', role='tax_officer',
            company=self.company, branch=self.branch_one,
        )
        self.manager = User.objects.create_user(
            username='branchmanager', password='pass1234', role='manager',
            company=self.company, branch=self.branch_one,
        )
        self.admin = User.objects.create_user(
            username='branchadmin', password='pass1234', role='admin',
            company=self.company,
        )

    def test_staff_is_limited_to_assigned_branch(self):
        visible = scope_queryset(self.staff, Client.objects.all())

        self.assertEqual(list(visible), [self.client_one])

    def test_company_admin_can_see_company_branches_but_not_other_companies(self):
        visible = scope_queryset(self.admin, Client.objects.all())

        self.assertCountEqual(list(visible), [self.client_one, self.client_two])

    def test_unassigned_staff_has_no_branch_data_access(self):
        unassigned = User.objects.create_user(
            username='unassigned', password='pass1234', role='tax_officer',
            company=self.company,
        )

        self.assertFalse(scope_queryset(unassigned, Client.objects.all()).exists())

    def test_manager_cannot_assign_company_leadership_role(self):
        form = UserForm(
            data={'username': 'promoted_user', 'role': 'admin'},
            actor=self.manager,
        )

        self.assertFalse(form.is_valid())
        self.assertNotIn(
            'admin',
            [value for value, _label in form.fields['role'].choices],
        )

    def test_new_user_form_defaults_to_managers_branch(self):
        form = UserForm(actor=self.manager)

        self.assertEqual(form['branch'].value(), self.branch_one.pk)

    def test_unlinked_admin_retains_legacy_unscoped_access(self):
        legacy_admin = User.objects.create_user(
            username='legacyadmin', password='pass1234', role='admin',
        )
        legacy_client = Client.objects.create(
            full_name='Legacy Client', phone_primary='+256700100004',
        )

        self.assertCountEqual(
            list(scope_queryset(legacy_admin, Client.objects.all())),
            [self.client_one, self.client_two, self.other_client, legacy_client],
        )


@override_settings(RECEIVABLES_API_KEY='test-receivables-key')
class ReceivablesSummaryApiTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name='Taxman 256',
            slug='taxman256',
        )
        self.client_obj = Client.objects.create(
            full_name='Monthly Report Client',
            phone_primary='+256700123456',
        )
        self.headers = {'HTTP_AUTHORIZATION': 'Bearer test-receivables-key'}

    def make_invoice(self, amount, issue_date, status='sent'):
        invoice = Invoice.objects.create(
            client=self.client_obj,
            due_date=date(2026, 12, 31),
            grand_total=Decimal(amount),
            status=status,
        )
        Invoice.objects.filter(pk=invoice.pk).update(date_issued=issue_date)
        invoice.refresh_from_db()
        return invoice

    def get_summary(self, **params):
        return self.client.get(
            reverse('receivables_summary'),
            params,
            **self.headers,
        )

    def test_monthly_receivables_totals(self):
        opening_invoice = self.make_invoice('1500000', date(2026, 9, 15))
        month_invoice = self.make_invoice('2400000', date(2026, 10, 5))
        Payment.objects.create(
            invoice=opening_invoice,
            amount=Decimal('300000'),
            payment_date=date(2026, 9, 20),
        )
        Payment.objects.create(
            invoice=opening_invoice,
            amount=Decimal('600000'),
            payment_date=date(2026, 10, 10),
        )
        Payment.objects.create(
            invoice=month_invoice,
            amount=Decimal('1200000'),
            payment_date=date(2026, 10, 15),
        )

        response = self.get_summary(company='TAXMAN256', month='2026-10')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'company': 'TAXMAN256',
            'month': '2026-10',
            'opening_receivables': 1200000.0,
            'work_billed_this_month': 2400000.0,
            'collected_this_month': 1800000.0,
            'closing_receivables': 1800000.0,
            'written_off_this_month': 0.0,
        })

    def test_invalid_month_is_rejected(self):
        for month in ('2026-13', '0000-01'):
            with self.subTest(month=month):
                response = self.get_summary(company='taxman256', month=month)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()['error']['code'], 'invalid_month')
                self.assertTrue(response['X-Request-ID'])

    def test_missing_parameters_are_reported_by_field(self):
        response = self.get_summary(company='taxman256')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], {
            'code': 'missing_parameters',
            'message': 'Provide all required query parameters: company and month.',
            'details': {'missing_fields': ['month']},
        })

    def test_unknown_company_returns_actionable_error(self):
        response = self.get_summary(company='unknown', month='2026-10')

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['error']['code'], 'company_not_found')

    def test_unauthorized_request_is_rejected(self):
        response = self.client.get(reverse('receivables_summary'), {
            'company': 'taxman256',
            'month': '2026-10',
        })

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['error']['code'], 'authentication_required')
        self.assertEqual(response['WWW-Authenticate'], 'Bearer')

    def test_unconfigured_api_returns_service_error(self):
        with self.settings(RECEIVABLES_API_KEY=''):
            response = self.get_summary(company='taxman256', month='2026-10')

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['error']['code'], 'service_unavailable')

    @patch('core.api_views._amount', side_effect=DatabaseError('database detail'))
    def test_database_error_returns_safe_service_error(self, _mock_amount):
        with self.assertLogs('core.api_views', level='ERROR'):
            response = self.get_summary(company='taxman256', month='2026-10')

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['error']['code'], 'service_unavailable')
        self.assertNotIn('database detail', response.content.decode())

    def test_non_get_request_returns_json_method_error(self):
        response = self.client.post(
            reverse('receivables_summary'),
            **self.headers,
        )

        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.json()['error']['code'], 'method_not_allowed')
        self.assertEqual(response['Allow'], 'GET')

    @patch('core.api_views._amount', side_effect=RuntimeError('internal detail'))
    def test_unexpected_error_is_logged_and_not_exposed(self, _mock_amount):
        with self.assertLogs('core.api_views', level='ERROR') as logs:
            response = self.get_summary(company='taxman256', month='2026-10')

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()['error']['code'], 'internal_server_error')
        self.assertNotIn('internal detail', response.content.decode())
        self.assertIn(response.json()['request_id'], logs.output[0])

    def test_write_off_updated_in_month_reduces_closing_balance(self):
        invoice = self.make_invoice('500000', date(2026, 9, 15), status='written_off')
        Invoice.objects.filter(pk=invoice.pk).update(
            updated_at=datetime(2026, 10, 12, tzinfo=datetime_timezone.utc)
        )

        response = self.get_summary(company='taxman256', month='2026-10')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['opening_receivables'], 500000.0)
        self.assertEqual(response.json()['written_off_this_month'], 500000.0)
        self.assertEqual(response.json()['closing_receivables'], 0.0)


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

    def test_branch_manager_cannot_open_company_control_center(self):
        company = Company.objects.create(name='Branch Controls', slug='branch-controls')
        branch = Branch.objects.create(company=company, name='Assigned Branch')
        manager = User.objects.create_user(
            username='branchmanager', password='pass123',
            role='manager', company=company, branch=branch,
        )
        self.client.force_login(manager)

        response = self.client.get(reverse('core:admin_control_center'))

        self.assertEqual(response.status_code, 302)

    def test_company_admin_controls_are_scoped_to_their_company(self):
        self.client.force_login(self.admin)
        company = Company.objects.create(name='Company One', slug='company-one')
        self.admin.company = company
        self.admin.save(update_fields=['company'])

        other_company = Company.objects.create(name='Company Two', slug='company-two')
        other_module = SystemModuleVisibility.objects.create(key='clients', company=other_company, label='Clients', enabled=True)
        company_module = SystemModuleVisibility.objects.create(key='clients', company=company, label='Clients', enabled=True)

        response = self.client.post(reverse('core:admin_control_center'), {'module_clients': 'off'})

        self.assertEqual(response.status_code, 302)
        company_module.refresh_from_db()
        other_module.refresh_from_db()
        self.assertFalse(company_module.enabled)
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
