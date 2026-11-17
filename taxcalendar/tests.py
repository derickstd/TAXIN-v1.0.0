from django.test import TestCase
from django.urls import reverse

from core.models import Branch, Company, User
from .forms import TaxEventForm
from .models import TaxEvent


class TaxCalendarBranchAccessTests(TestCase):
    def setUp(self):
        company = Company.objects.create(name='Calendar Test Co', slug='calendar-test')
        self.branch = Branch.objects.create(company=company, name='Assigned Branch')
        other_branch = Branch.objects.create(company=company, name='Other Branch')
        self.manager = User.objects.create_user(
            username='calendar_manager', password='pass1234',
            role='manager', company=company, branch=self.branch,
        )
        self.branch_staff = User.objects.create_user(
            username='calendar_staff', password='pass1234',
            role='tax_officer', company=company, branch=self.branch,
        )
        self.other_staff = User.objects.create_user(
            username='other_calendar_staff', password='pass1234',
            role='tax_officer', company=company, branch=other_branch,
        )
        self.own_event = TaxEvent.objects.create(
            title='Assigned branch event', due_date='2099-01-01',
            created_by=self.manager,
        )
        self.other_event = TaxEvent.objects.create(
            title='Other branch event', due_date='2099-01-01',
            created_by=self.other_staff,
        )
        self.client.force_login(self.manager)

    def test_calendar_lists_only_events_created_in_assigned_branch(self):
        response = self.client.get(reverse('taxcalendar:list'))

        self.assertEqual(response.status_code, 200)
        event_titles = {event.title for event in response.context['events']}
        self.assertIn(self.own_event.title, event_titles)
        self.assertNotIn(self.other_event.title, event_titles)

    def test_event_assignees_are_limited_to_assigned_branch(self):
        form = TaxEventForm(user=self.manager)

        self.assertCountEqual(
            list(form.fields['assigned_to'].queryset),
            [self.manager, self.branch_staff],
        )
        self.assertNotIn(self.other_staff, form.fields['assigned_to'].queryset)

    def test_manager_cannot_change_another_branch_event(self):
        response = self.client.post(
            reverse('taxcalendar:update_status', args=[self.other_event.pk]),
            {'status': 'done'},
        )

        self.assertEqual(response.status_code, 404)
