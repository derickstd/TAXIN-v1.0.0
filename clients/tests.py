from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory
from django.test import TestCase
from django.urls import reverse

from clients.models import Client, WalkInIntake
from clients import views
from core.models import User


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

    def test_create_route_uses_merged_onboarding_page(self):
        request = self.factory.get(reverse('clients:create'))
        request.user = self.user
        response = views.client_create(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Client Onboarding', response.content)

    def test_walkin_route_uses_merged_onboarding_page(self):
        request = self.factory.get(reverse('clients:walkin'))
        request.user = self.user
        response = views.walkin_create(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Client Onboarding', response.content)

    def test_import_route_uses_merged_onboarding_page(self):
        request = self.factory.get(reverse('clients:import'))
        request.user = self.user
        response = views.client_import(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Client Onboarding', response.content)

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
