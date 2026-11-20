from datetime import datetime, timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory
from django.test import TestCase
from django.urls import reverse

from clients.models import Client, WalkInIntake
from clients import views
from core.models import Branch, Company, User


class ClientOnboardingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='clienttester',
            password='pass1234',
            role='admin',
        )
        self.staff = User.objects.create_user(
            username='stafftester',
            password='pass1234',
            role='tax_officer',
            is_active_staff=True,
        )
        self.client.force_login(self.user)
        self.factory = RequestFactory()
        self.existing_client = Client.objects.create(
            full_name='Existing Client',
            phone_primary='+256700123123',
            created_by=self.user,
        )

    def test_client_list_is_sorted_by_most_recently_modified(self):
        older_client = Client.objects.create(
            full_name='Older Update',
            phone_primary='+256700123124',
            created_by=self.user,
        )
        newer_client = Client.objects.create(
            full_name='Newer Update',
            phone_primary='+256700123125',
            created_by=self.user,
        )
        Client.objects.filter(pk=self.existing_client.pk).update(
            updated_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        Client.objects.filter(pk=older_client.pk).update(
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        Client.objects.filter(pk=newer_client.pk).update(
            updated_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )

        response = self.client.get(reverse('clients:list'))

        self.assertEqual(response.status_code, 200)
        listed_clients = list(response.context['clients'].object_list)
        self.assertEqual(
            [client.pk for client in listed_clients[:2]],
            [newer_client.pk, older_client.pk],
        )

    def test_create_route_uses_add_customer_page(self):
        request = self.factory.get(reverse('clients:create'))
        request.user = self.user
        response = views.client_create(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Add Customer', response.content)

    def test_quick_client_create_adds_customer_for_payment_popover(self):
        response = self.client.post(reverse('clients:quick_create'), {
            'client_type': 'individual',
            'full_name': 'Popover Payment Client',
            'phone_primary': '+256700123129',
            'district': 'Kampala',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(response.status_code, 200)
        client = Client.objects.get(full_name='Popover Payment Client')
        self.assertEqual(client.created_by, self.user)
        self.assertEqual(response.json()['id'], client.pk)

    def test_quick_client_create_returns_form_errors_without_creating_client(self):
        response = self.client.post(reverse('clients:quick_create'), {
            'client_type': 'individual',
            'full_name': 'Duplicate Phone Client',
            'phone_primary': self.existing_client.phone_primary,
            'district': 'Kampala',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(response.status_code, 400)
        self.assertIn('phone_primary', response.json()['errors'])
        self.assertFalse(Client.objects.filter(full_name='Duplicate Phone Client').exists())

    def test_clients_in_other_branches_are_not_duplicate_candidates(self):
        company = Company.objects.create(name='Branch Duplicate Co', slug='branch-duplicate')
        entry_branch = Branch.objects.create(company=company, name='TAXMAN')
        other_branch = Branch.objects.create(
            company=company, name='PRIME FOCUS', external_reporting=True,
        )
        branch_user = User.objects.create_user(
            username='branch-client-creator', password='pass1234',
            role='tax_officer', company=company, branch=entry_branch,
        )
        Client.objects.create(
            full_name='Branch Shared Client', tin='1234567890',
            phone_primary='+256700888111', branch=other_branch,
        )
        self.client.force_login(branch_user)

        duplicate_check = self.client.get(reverse('clients:check_duplicates'), {
            'tin': '1234567890',
            'phone': '+256700888111',
        })
        self.assertEqual(duplicate_check.status_code, 200)
        self.assertEqual(duplicate_check.json()['duplicates'], [])

        response = self.client.post(reverse('clients:quick_create'), {
            'client_type': 'individual',
            'full_name': 'Branch Shared Client',
            'tin': '1234567890',
            'phone_primary': '+256700888111',
            'district': 'Kampala',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(response.status_code, 200, response.content)
        created_client = Client.objects.get(pk=response.json()['id'])
        self.assertEqual(created_client.branch, entry_branch)
        self.assertEqual(created_client.find_duplicate_candidates(), [])

    def test_walkin_route_uses_add_customer_page(self):
        request = self.factory.get(reverse('clients:walkin'))
        request.user = self.user
        response = views.walkin_create(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Add Customer', response.content)

    def test_onboarding_page_does_not_render_walkin_intake_section(self):
        request = self.factory.get(reverse('clients:create'))
        request.user = self.user
        response = views.client_create(request)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'Walk-in Intake', response.content)

    def test_import_route_uses_add_customer_page(self):
        request = self.factory.get(reverse('clients:import'))
        request.user = self.user
        response = views.client_import(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Add Customer', response.content)

    def test_new_client_post_still_creates_client(self):
        response = self.client.post(reverse('clients:create'), {
            'client_type': 'individual',
            'full_name': 'Merged Page Client',
            'trading_name': '',
            'tin': '',
            'phone_primary': '+256700555666',
            'phone_whatsapp': '+256700555666',
            'email': 'merged@example.com',
            'district': 'Kampala',
            'physical_address': 'Plot 1',
            'referred_by': '',
            'assigned_officer': str(self.staff.pk),
            'notes': 'Created from merged page',
        })

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Client.objects.filter(full_name='Merged Page Client').exists())

    def test_client_create_rejects_duplicate_tin(self):
        response = self.client.post(reverse('clients:create'), {
            'client_type': 'individual',
            'full_name': 'Duplicate TIN Client',
            'trading_name': '',
            'tin': '',
            'phone_primary': '+256700555777',
            'phone_whatsapp': '+256700555777',
            'email': 'dup@example.com',
            'district': 'Kampala',
            'physical_address': 'Plot 2',
            'referred_by': '',
            'assigned_officer': str(self.staff.pk),
            'notes': 'Duplicate TIN test',
        })
        # Should create because existing client has no TIN
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Client.objects.filter(full_name='Duplicate TIN Client').exists())

    def test_client_create_rejects_duplicate_phone_primary(self):
        response = self.client.post(reverse('clients:create'), {
            'client_type': 'individual',
            'full_name': 'Duplicate Phone',
            'trading_name': '',
            'tin': '1234567890',
            'phone_primary': '+256700123123',
            'phone_whatsapp': '+256700123123',
            'email': 'phone@example.com',
            'district': 'Kampala',
            'physical_address': 'Plot 3',
            'referred_by': '',
            'assigned_officer': str(self.staff.pk),
            'notes': 'Duplicate phone test',
        })

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'A client with this phone number already exists.', response.content)
        self.assertFalse(Client.objects.filter(full_name='Duplicate Phone').exists())

    def test_client_search_api_includes_phone_whatsapp(self):
        client = Client.objects.create(
            full_name='WhatsApp Search',
            phone_primary='+256700999999',
            phone_whatsapp='+256700888888',
            created_by=self.user,
        )
        response = self.client.get(reverse('clients:search'), {'q': '+256700888888'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'WhatsApp Search', response.content)

    def test_walkin_post_creates_intake_and_respects_selected_staff(self):
        response = self.client.post(reverse('clients:walkin'), {
            'client': str(self.existing_client.pk),
            'purpose': 'Needs VAT filing help',
            'assigned_staff': str(self.staff.pk),
            'notes': 'Walked in this morning',
            'outcome': 'pending',
        })

        self.assertEqual(response.status_code, 302)
        intake = WalkInIntake.objects.get()
        self.assertEqual(intake.client, self.existing_client)
        self.assertEqual(intake.assigned_staff, self.staff)

    def test_batch_import_post_creates_clients(self):
        csv_content = (
            "full_name,phone_primary,client_type,trading_name,tin,email,phone_whatsapp,district,address\n"
            "Import Client,+256701111222,company,IC Ltd,1001234567,import@example.com,+256701111222,Kampala,Plot 7\n"
        )
        upload = SimpleUploadedFile('clients.csv', csv_content.encode('utf-8'), content_type='text/csv')

        response = self.client.post(reverse('clients:import'), {
            'csv_file': upload,
        })

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Client.objects.filter(full_name='Import Client').exists())


class ClientDetailWorkspaceTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Workspace Co', slug='workspace-co')
        self.current_branch = Branch.objects.create(
            company=self.company, name='TAXMAN',
        )
        self.client_branch = Branch.objects.create(
            company=self.company, name='ABA UGANDA',
        )
        self.admin = User.objects.create_user(
            username='workspace_admin',
            password='pass1234',
            role='admin',
            company=self.company,
            branch=self.current_branch,
        )
        self.other_client = Client.objects.create(
            full_name='ABA Client',
            phone_primary='+256700111111',
            branch=self.client_branch,
            created_by=self.admin,
        )

    def test_company_admin_can_switch_to_client_workspace_from_detail_link(self):
        self.client.force_login(self.admin)
        session = self.client.session
        session['active_branch_id'] = self.current_branch.pk
        session.save()

        url = reverse('clients:detail', args=[self.other_client.pk])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'clients/client_workspace_required.html')
        self.assertContains(response, 'ABA UGANDA workspace')

        switch_response = self.client.post(reverse('dashboard:switch_branch'), {
            'branch': self.client_branch.pk,
            'next': url,
        })

        self.assertRedirects(switch_response, url)
        detail_response = self.client.get(url)
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.context['client'], self.other_client)

    def test_branch_staff_cannot_use_workspace_prompt_to_view_other_branch_client(self):
        staff = User.objects.create_user(
            username='workspace_staff',
            password='pass1234',
            role='tax_officer',
            company=self.company,
            branch=self.current_branch,
        )
        self.client.force_login(staff)

        response = self.client.get(
            reverse('clients:detail', args=[self.other_client.pk]),
        )

        self.assertEqual(response.status_code, 404)


class ClientArchiveTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name='Client Archive Co',
            slug='client-archive',
        )
        self.branch = Branch.objects.create(
            company=self.company,
            name='Archive Branch',
        )
        self.admin = User.objects.create_user(
            username='archive_admin',
            password='pass1234',
            role='admin',
            company=self.company,
        )
        self.client_record = Client.objects.create(
            full_name='Archived Client',
            phone_primary='+256700111222',
            created_by=self.admin,
            branch=self.branch,
        )
        self.intake = WalkInIntake.objects.create(client=self.client_record)

    def test_admin_can_archive_and_restore_client_without_removing_records(self):
        self.client.force_login(self.admin)

        page = self.client.get(reverse('clients:list'))
        self.assertContains(
            page,
            reverse('clients:archive', args=[self.client_record.pk]),
        )

        response = self.client.post(
            reverse('clients:archive', args=[self.client_record.pk]),
        )

        self.assertRedirects(
            response,
            reverse('clients:detail', args=[self.client_record.pk]),
        )
        self.client_record.refresh_from_db()
        self.assertEqual(self.client_record.status, 'dormant')
        self.assertTrue(
            WalkInIntake.objects.filter(pk=self.intake.pk).exists(),
        )

        restore_response = self.client.get(
            reverse('core:admin_client_reactivate', args=[self.client_record.pk]),
        )

        self.assertRedirects(
            restore_response,
            reverse('clients:detail', args=[self.client_record.pk]),
        )
        self.client_record.refresh_from_db()
        self.assertEqual(self.client_record.status, 'active')

    def test_non_admin_cannot_archive_client(self):
        manager = User.objects.create_user(
            username='archive_manager',
            password='pass1234',
            role='manager',
            company=self.company,
            branch=self.branch,
        )
        self.client.force_login(manager)

        response = self.client.post(
            reverse('clients:archive', args=[self.client_record.pk]),
        )

        self.assertRedirects(response, reverse('clients:list'))
        self.client_record.refresh_from_db()
        self.assertEqual(self.client_record.status, 'active')
