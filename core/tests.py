import sys
from datetime import date, datetime, timezone as datetime_timezone
from decimal import Decimal
from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib import admin
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image
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


class LogoutViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='logout-user',
            password='logout-pass-123',
        )
        self.client.force_login(self.user)

    def test_get_logout_shows_confirmation_without_ending_session(self):
        response = self.client.get(reverse('logout'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Sign out of Taxin?')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)

    def test_post_logout_ends_session_and_redirects_to_login(self):
        response = self.client.post(reverse('logout'))

        self.assertRedirects(response, reverse('login'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_get_logout_redirects_unauthenticated_users_to_login(self):
        self.client.logout()

        response = self.client.get(reverse('logout'))

        self.assertRedirects(response, reverse('login'))


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
        self.assertContains(response, 'Branch details')
        self.assertContains(response, 'Save company and branches')

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

    def test_company_branch_page_updates_company_and_adds_branch(self):
        company = Company.objects.create(
            name='Initial Company',
            slug='initial-company',
            email='old@example.test',
        )
        branch = Branch.objects.create(
            company=company, name='Main', slug='initial-company-main',
            phone='111',
        )
        admin_user = User.objects.create_user(
            username='company-editor', password='pass1234',
            role='admin', company=company,
        )
        self.client.force_login(admin_user)
        url = reverse('core:admin_company_branches', args=[company.pk])
        response = self.client.get(url)
        formset = response.context['branch_formset']
        prefix = formset.prefix
        data = {
            'action': 'save_company_branches',
            'name': 'Updated Company Name',
            'registration_number': 'REG-22',
            'tin': 'TIN-22',
            'email': 'updated@example.test',
            'phone': '+256700000000',
            'address': 'New company address',
            'default_branch': str(branch.pk),
            f'{prefix}-TOTAL_FORMS': '2',
            f'{prefix}-INITIAL_FORMS': '1',
            f'{prefix}-MIN_NUM_FORMS': '0',
            f'{prefix}-MAX_NUM_FORMS': '1000',
            f'{prefix}-0-id': str(branch.pk),
            f'{prefix}-0-name': branch.name,
            f'{prefix}-0-slug': branch.slug,
            f'{prefix}-0-address': branch.address,
            f'{prefix}-0-phone': '+256700000009',
            f'{prefix}-0-is_active': 'on',
            f'{prefix}-0-external_reporting': '',
            f'{prefix}-1-name': 'North Branch',
            f'{prefix}-1-slug': '',
            f'{prefix}-1-address': 'North address',
            f'{prefix}-1-phone': '+256700000001',
            f'{prefix}-1-is_active': 'on',
            f'{prefix}-1-external_reporting': 'on',
        }

        response = self.client.post(url, data)

        self.assertRedirects(response, url)
        company.refresh_from_db()
        self.assertEqual(company.name, 'Updated Company Name')
        self.assertEqual(company.email, 'updated@example.test')
        self.assertEqual(company.phone, '+256700000000')
        branch.refresh_from_db()
        self.assertEqual(branch.phone, '+256700000009')
        new_branch = company.branches.get(name='North Branch')
        self.assertEqual(new_branch.slug, 'initial-company-north-branch')
        self.assertEqual(new_branch.phone, '+256700000001')
        self.assertTrue(new_branch.external_reporting)

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
            ('core:admin_dashboard', 'Admin Dashboard'),
            ('core:admin_control_center', 'System Control Center'),
            ('core:admin_companies', 'Company and Branches'),
            ('core:admin_analytics', 'System Analytics'),
            ('core:admin_health', 'System Health'),
        )
        for page_name, breadcrumb in pages:
            with self.subTest(page=page_name):
                response = self.client.get(reverse(page_name))
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, 'Manage Tenants')
                self.assertContains(
                    response,
                    f'<li class="active">{breadcrumb}</li>',
                    html=True,
                )


class SettingsToolsTests(TestCase):
    def setUp(self):
                self.company = Company.objects.create(name='Settings Co', slug='settings-co')
                self.branch = Branch.objects.create(company=self.company, name='Main Branch')
                self.company.default_branch = self.branch
                self.company.save(update_fields=['default_branch'])
                self.admin = User.objects.create_user(
                    username='settings-admin', password='pass1234',
                    role='admin', company=self.company,
                )
                self.client.force_login(self.admin)

    def test_settings_displays_workspace_branch_and_user_tools(self):
                response = self.client.get(reverse('core:settings'))

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'Workspace Settings')
                self.assertContains(response, 'Main Branch')
                self.assertContains(response, 'Add Branch')
                self.assertContains(response, 'branchFormTemplate')
                self.assertContains(response, '__prefix__')
                self.assertContains(response, 'Add User')
                self.assertContains(response, 'settingsUserModal')
                self.assertContains(response, reverse('dashboard:switch_branch'))
                self.assertContains(response, reverse('core:users'))

    def test_settings_add_user_uses_company_and_branch_scope(self):
                response = self.client.post(reverse('core:settings'), {
                    'settings_action': 'add_user',
                    'username': 'quick-staff',
                    'first_name': 'Quick',
                    'last_name': 'Staff',
                    'role': 'tax_officer',
                    'branch': str(self.branch.pk),
                    'ui_theme': 'ocean',
                    'password1': 'temporary-pass-123',
                    'password2': 'temporary-pass-123',
                    'receive_debt_alerts': 'on',
                    'receive_task_reminders': 'on',
                })

                self.assertRedirects(response, reverse('core:settings'))
                new_user = User.objects.get(username='quick-staff')
                self.assertEqual(new_user.company, self.company)
                self.assertEqual(new_user.branch, self.branch)
                self.assertTrue(new_user.check_password('temporary-pass-123'))
                self.assertTrue(new_user.is_active)
                self.assertTrue(new_user.is_active_staff)

    def test_settings_add_user_rejects_non_admin(self):
                staff = User.objects.create_user(
                    username='settings-staff', password='pass1234',
                    role='tax_officer', company=self.company, branch=self.branch,
                )
                self.client.force_login(staff)

                response = self.client.post(reverse('core:settings'), {
                    'settings_action': 'add_user',
                    'username': 'unauthorized-staff',
                    'role': 'tax_officer',
                    'ui_theme': 'ocean',
                })

                self.assertRedirects(response, reverse('dashboard:index'))
                self.assertFalse(User.objects.filter(username='unauthorized-staff').exists())

    def test_settings_formset_adds_branch(self):
                response = self.client.get(reverse('core:settings'))
                formset = response.context['branch_formset']
                prefix = formset.prefix
                payload = {
                    'name': self.company.name,
                    'registration_number': self.company.registration_number,
                    'tin': self.company.tin,
                    'email': self.company.email,
                    'phone': self.company.phone,
                    'address': self.company.address,
                    'default_branch': str(self.branch.pk),
                    'first_name': self.admin.first_name,
                    'last_name': self.admin.last_name,
                    'email_notify': self.admin.email_notify,
                    'phone_whatsapp': self.admin.phone_whatsapp,
                    'receive_debt_alerts': 'on',
                    'receive_task_reminders': 'on',
                    'ui_theme': self.admin.ui_theme,
                    f'{prefix}-TOTAL_FORMS': str(formset.total_form_count()),
                    f'{prefix}-INITIAL_FORMS': str(formset.initial_form_count()),
                    f'{prefix}-MIN_NUM_FORMS': str(formset.min_num),
                    f'{prefix}-MAX_NUM_FORMS': str(formset.max_num),
                }
                for index, branch_form in enumerate(formset.forms):
                    for hidden in branch_form.hidden_fields():
                        payload[hidden.html_name] = hidden.value() or ''
                    if branch_form.instance.pk:
                        values = {
                            'name': branch_form.instance.name,
                            'slug': branch_form.instance.slug,
                            'address': branch_form.instance.address,
                            'phone': branch_form.instance.phone,
                            'is_active': 'on' if branch_form.instance.is_active else '',
                        }
                    else:
                        values = {
                            'name': 'New Branch',
                            'slug': 'new-branch',
                            'address': 'New branch address',
                            'phone': '0700000000',
                            'is_active': 'on',
                        }
                    for field, value in values.items():
                        payload[f'{prefix}-{index}-{field}'] = value
                    payload[f'{prefix}-{index}-DELETE'] = ''

                logo_content = BytesIO()
                Image.new('RGB', (16, 16), color='teal').save(logo_content, format='PNG')
                new_branch_index = formset.total_form_count() - 1
                payload[f'{prefix}-{new_branch_index}-logo'] = SimpleUploadedFile(
                    'branch-logo.png',
                    logo_content.getvalue(),
                    content_type='image/png',
                )
                with TemporaryDirectory() as media_root:
                    with override_settings(MEDIA_ROOT=media_root):
                        response = self.client.post(reverse('core:settings'), payload)
                        new_branch = self.company.branches.get(name='New Branch')
                        self.assertTrue(new_branch.logo.name.startswith('branch_logos/'))

                self.assertRedirects(response, reverse('core:settings'))
                self.assertTrue(self.company.branches.filter(name='New Branch').exists())


class UserEditTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='User Edit Co', slug='user-edit')
        self.branch = Branch.objects.create(company=self.company, name='Main Branch')
        self.admin = User.objects.create_user(
            username='user-edit-admin',
            password='admin-pass-123',
            role='admin',
            company=self.company,
        )
        self.target = User.objects.create_user(
            username='user-edit-target',
            password='old-pass-123',
            role='tax_officer',
            company=self.company,
            branch=self.branch,
            first_name='Original',
        )
        self.client.force_login(self.admin)

    def _edit_data(self, password1, password2, first_name='Updated'):
        return {
            'username': self.target.username,
            'first_name': first_name,
            'last_name': '',
            'email': '',
            'email_notify': '',
            'phone_whatsapp': '',
            'branch': str(self.branch.pk),
            'role': 'tax_officer',
            'ui_theme': 'ocean',
            'is_active_staff': 'on',
            'is_active': 'on',
            'receive_debt_alerts': 'on',
            'receive_task_reminders': 'on',
            'date_joined_firm': '',
            'password1': password1,
            'password2': password2,
        }

    def test_user_edit_saves_matching_new_password(self):
        response = self.client.post(
            reverse('core:user_edit', args=[self.target.pk]),
            self._edit_data('new-pass-123', 'new-pass-123'),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'User {self.target.username} updated.')
        self.target.refresh_from_db()
        self.assertEqual(self.target.first_name, 'Updated')
        self.assertTrue(self.target.check_password('new-pass-123'))

    def test_user_edit_shows_validation_error_when_passwords_do_not_match(self):
        response = self.client.post(
            reverse('core:user_edit', args=[self.target.pk]),
            self._edit_data('new-pass-123', 'different-pass-123'),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'User was not updated.')
        self.assertContains(response, 'Passwords do not match.')
        self.target.refresh_from_db()
        self.assertEqual(self.target.first_name, 'Original')
        self.assertTrue(self.target.check_password('old-pass-123'))


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

    def test_company_ceo_can_see_company_branches_but_not_other_companies(self):
        ceo = User.objects.create_user(
            username='branchceo', password='pass1234', role='ceo',
            company=self.company,
        )

        visible = scope_queryset(ceo, Client.objects.all())

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


class BranchArchiveTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name='Branch Archive Co',
            slug='branch-archive',
        )
        self.branch = Branch.objects.create(
            company=self.company,
            name='Archive Branch',
        )
        self.company.default_branch = self.branch
        self.company.save(update_fields=['default_branch'])
        self.admin = User.objects.create_user(
            username='branch_archive_admin',
            password='pass1234',
            role='admin',
            company=self.company,
        )
        self.payment = Payment.objects.create(
            branch=self.branch,
            amount=Decimal('500'),
            payment_date=date.today(),
            received_by=self.admin,
        )

    def test_admin_can_archive_and_restore_branch_without_removing_records(self):
        self.client.force_login(self.admin)
        url = reverse(
            'core:admin_branch_archive',
            args=[self.company.pk, self.branch.pk],
        )

        page = self.client.get(
            reverse('core:admin_company_branches', args=[self.company.pk]),
        )
        self.assertContains(page, url)

        response = self.client.post(url)

        self.assertRedirects(
            response,
            reverse('core:admin_company_branches', args=[self.company.pk]),
        )
        self.branch.refresh_from_db()
        self.company.refresh_from_db()
        self.assertFalse(self.branch.is_active)
        self.assertIsNone(self.company.default_branch)
        self.assertTrue(Payment.objects.filter(pk=self.payment.pk).exists())
        self.assertTrue(AuditLog.objects.filter(
            model_name='branch',
            object_id=str(self.branch.pk),
            action='UPDATE',
            changed_by=self.admin,
        ).exists())

        self.client.post(url)
        self.branch.refresh_from_db()
        self.assertTrue(self.branch.is_active)

    def test_manager_cannot_archive_branch(self):
        manager = User.objects.create_user(
            username='branch_archive_manager',
            password='pass1234',
            role='manager',
            company=self.company,
            branch=self.branch,
        )
        self.client.force_login(manager)

        response = self.client.post(reverse(
            'core:admin_branch_archive',
            args=[self.company.pk, self.branch.pk],
        ))

        self.assertRedirects(response, reverse('dashboard:index'))
        self.branch.refresh_from_db()
        self.assertTrue(self.branch.is_active)


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


class UserDeletionPermissionsTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='User Delete Co', slug='user-delete')

    def test_company_admin_and_ceo_can_delete_users_from_user_list(self):
        for role in ('admin', 'ceo'):
            with self.subTest(role=role):
                actor = User.objects.create_user(
                    username=f'{role}_deleter',
                    password='pass123',
                    role=role,
                    company=self.company,
                )
                target = User.objects.create_user(
                    username=f'{role}_target',
                    password='pass123',
                    role='tax_officer',
                    company=self.company,
                )
                self.client.force_login(actor)

                page = self.client.get(reverse('core:users'))
                self.assertEqual(page.status_code, 200)
                self.assertContains(
                    page,
                    f'action="{reverse("core:user_delete", args=[target.pk])}"',
                )

                response = self.client.post(
                    reverse('core:user_delete', args=[target.pk]),
                )

                self.assertRedirects(response, reverse('core:users'))
                self.assertFalse(User.objects.filter(pk=target.pk).exists())
                self.assertTrue(AuditLog.objects.filter(
                    model_name='user',
                    object_id=str(target.pk),
                    action='DELETE',
                    changed_by=actor,
                ).exists())

    def test_manager_cannot_delete_users(self):
        branch = Branch.objects.create(company=self.company, name='Delete Test Branch')
        manager = User.objects.create_user(
            username='delete_manager',
            password='pass123',
            role='manager',
            company=self.company,
            branch=branch,
        )
        target = User.objects.create_user(
            username='manager_delete_target',
            password='pass123',
            role='tax_officer',
            company=self.company,
            branch=branch,
        )
        self.client.force_login(manager)

        page = self.client.get(reverse('core:users'))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(
            page,
            reverse('core:user_delete', args=[target.pk]),
        )

        response = self.client.post(
            reverse('core:user_delete', args=[target.pk]),
        )

        self.assertRedirects(response, reverse('core:users'))
        self.assertTrue(User.objects.filter(pk=target.pk).exists())

        admin_page_response = self.client.post(
            reverse('core:admin_user_delete', args=[target.pk]),
        )

        self.assertRedirects(
            admin_page_response,
            reverse('dashboard:index'),
        )
        self.assertTrue(User.objects.filter(pk=target.pk).exists())

    def test_admin_cannot_delete_user_in_another_company(self):
        other_company = Company.objects.create(
            name='Other User Delete Co',
            slug='other-user-delete',
        )
        admin = User.objects.create_user(
            username='company_admin',
            password='pass123',
            role='admin',
            company=self.company,
        )
        target = User.objects.create_user(
            username='other_company_target',
            password='pass123',
            role='tax_officer',
            company=other_company,
        )
        self.client.force_login(admin)

        response = self.client.post(
            reverse('core:user_delete', args=[target.pk]),
        )

        self.assertEqual(response.status_code, 404)
        self.assertTrue(User.objects.filter(pk=target.pk).exists())


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
