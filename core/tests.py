from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from billing.models import Invoice
from clients.models import Client
from core.models import User, ModelVisibility, UserModelPermission
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
