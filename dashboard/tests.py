from django.test import TestCase
from django.urls import reverse

from core.models import User


class DashboardViewTests(TestCase):
    def test_dashboard_adds_staff_completion_metrics(self):
        user = User.objects.create_user(
            username='dashboard-user',
            password='pass123',
            is_staff=True,
            is_active=True,
            is_active_staff=True,
        )
        self.client.force_login(user)

        response = self.client.get(reverse('dashboard:index'))

        self.assertEqual(response.status_code, 200)
        self.assertIn('staff_perf', response.context)
        self.assertTrue(response.context['staff_perf'])
        first_row = response.context['staff_perf'][0]
        self.assertIn('completion_pct', first_row)
        self.assertIn('completion_color', first_row)
