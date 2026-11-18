from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from core.models import Branch, Company, User
from expenses.models import Expense, ExpenseCategory
from billing.models import BranchDailyTransaction, OtherIncome, Payment
from clients.models import Client


class DashboardViewTests(TestCase):
    def test_company_dashboard_chart_compares_all_branches_and_workspace_shows_statcards(self):
        company = Company.objects.create(name='Dashboard Comparison Co', slug='dashboard-comparison')
        taxman = Branch.objects.create(company=company, name='TAXMAN')
        prime_focus = Branch.objects.create(
            company=company, name='PRIME FOCUS', external_reporting=True,
        )
        aba_uganda = Branch.objects.create(
            company=company, name='ABA UGANDA', external_reporting=True,
        )
        user = User.objects.create_user(
            username='comparison-admin', password='pass1234',
            role='admin', company=company,
        )
        client = Client.objects.create(
            full_name='Dashboard Sales Client', phone_primary='+256700000039',
            branch=taxman, created_by=user,
        )
        today = timezone.localdate()
        week_start = today - timezone.timedelta(days=today.weekday())
        month_start = today.replace(day=1)
        Payment.objects.create(
            client=client, branch=taxman, amount=Decimal('1000'),
            payment_date=today, received_by=user,
        )
        earlier_this_month = week_start - timezone.timedelta(days=1)
        has_earlier_month_payment = earlier_this_month >= month_start
        if has_earlier_month_payment:
            Payment.objects.create(
                client=client, branch=taxman, amount=Decimal('100'),
                payment_date=earlier_this_month, received_by=user,
            )
        category = ExpenseCategory.objects.create(name='Dashboard Test Expense')
        Expense.objects.create(
            expense_date=today, category=category, description='Rent',
            amount=Decimal('200'), status='approved', branch=taxman,
            paid_by=user, created_by=user, approved_by=user,
        )
        for branch, inflow, outflow in (
            (prime_focus, Decimal('300'), Decimal('20')),
            (aba_uganda, Decimal('500'), Decimal('50')),
        ):
            for direction, amount, transaction_category in (
                ('inflow', inflow, 'service_receipt'),
                ('outflow', outflow, 'operating_expense'),
            ):
                BranchDailyTransaction.objects.create(
                    branch=branch, business_date=today, direction=direction,
                    category=transaction_category, description='Daily entry',
                    account='cash', amount=amount, entered_by=user,
                )

        self.client.force_login(user)
        response = self.client.get(reverse('dashboard:index'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['period'], 'this_month')
        self.assertContains(response, 'Reporting period')
        self.assertEqual(
            response.context['branch_chart_data']['labels'],
            ['ABA UGANDA', 'PRIME FOCUS', 'TAXMAN'],
        )
        self.assertEqual(
            response.context['branch_chart_data']['sales'],
            [500.0, 300.0, 1100.0 if has_earlier_month_payment else 1000.0],
        )
        self.assertEqual(
            response.context['branch_chart_data']['expenses'],
            [50.0, 20.0, 200.0],
        )
        self.assertEqual(
            response.context['branch_chart_data']['profit'],
            [450.0, 280.0, 900.0 if has_earlier_month_payment else 800.0],
        )
        self.assertEqual(
            response.context['pie_chart_data'],
            {
                'labels': ['ABA UGANDA', 'PRIME FOCUS', 'TAXMAN'],
                'values': [500.0, 300.0, 1100.0 if has_earlier_month_payment else 1000.0],
            },
        )
        self.assertContains(response, 'branchCashFlowPieChart')
        self.assertContains(response, 'branchPerformanceChart')

        weekly_response = self.client.get(reverse('dashboard:index'), {
            'period': 'this_week',
        })
        self.assertEqual(weekly_response.context['period'], 'this_week')
        self.assertEqual(weekly_response.context['period_start'], week_start)
        self.assertEqual(
            weekly_response.context['branch_chart_data']['sales'],
            [500.0, 300.0, 1000.0],
        )

        self.client.post(reverse('dashboard:switch_branch'), {
            'branch': taxman.pk,
            'next': reverse('dashboard:index'),
        })
        workspace_response = self.client.get(reverse('dashboard:index'), {
            'period': 'this_week',
        })

        self.assertEqual(workspace_response.status_code, 200)
        self.assertEqual(workspace_response.context['workspace_summary']['inflow'], Decimal('1000'))
        self.assertEqual(workspace_response.context['workspace_summary']['outflow'], Decimal('200'))
        self.assertEqual(
            workspace_response.context['pie_chart_data'],
            {'labels': ['Cash in', 'Cash out'], 'values': [1000.0, 200.0]},
        )
        self.assertContains(workspace_response, 'Cash remaining')
        self.assertContains(workspace_response, 'Cash flow mix')
        self.assertContains(
            workspace_response,
            f'?period=this_week&amp;branch={taxman.pk}',
        )
        self.assertNotContains(workspace_response, 'branchPerformanceChart')

        monthly_workspace_response = self.client.get(reverse('dashboard:index'), {
            'period': 'this_month',
        })
        self.assertEqual(
            monthly_workspace_response.context['workspace_summary']['inflow'],
            Decimal('1100') if has_earlier_month_payment else Decimal('1000'),
        )

    def test_day_transaction_details_respect_active_branch_workspace(self):
        company = Company.objects.create(name='Transaction Workspace Co', slug='transaction-workspace')
        taxman = Branch.objects.create(company=company, name='TAXMAN')
        prime_focus = Branch.objects.create(company=company, name='PRIME FOCUS')
        user = User.objects.create_user(
            username='transaction-workspace-admin', password='pass1234',
            role='admin', company=company,
        )
        taxman_client = Client.objects.create(
            full_name='Taxman Ledger Client', phone_primary='+256700000031', branch=taxman,
        )
        prime_client = Client.objects.create(
            full_name='Prime Ledger Client', phone_primary='+256700000032', branch=prime_focus,
        )
        business_date = timezone.localdate()
        Payment.objects.create(
            client=taxman_client, branch=taxman, amount=Decimal('9876'),
            payment_date=business_date, received_by=user,
        )
        Payment.objects.create(
            client=prime_client, branch=prime_focus, amount=Decimal('1234'),
            payment_date=business_date, received_by=user,
        )
        self.client.force_login(user)
        self.client.post(reverse('dashboard:switch_branch'), {
            'branch': prime_focus.pk,
            'next': reverse('dashboard:index'),
        })

        response = self.client.get(reverse('dashboard:day_transactions'), {
            'day': business_date.isoformat(),
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '1,234')
        self.assertNotContains(response, '9,876')

    def test_leadership_can_switch_branch_workspace_and_return_to_company_view(self):
        company = Company.objects.create(name='Workspace Co', slug='workspace')
        taxman = Branch.objects.create(company=company, name='TAXMAN')
        prime_focus = Branch.objects.create(company=company, name='PRIME FOCUS')
        user = User.objects.create_user(
            username='workspace-admin', password='pass1234',
            role='admin', company=company,
        )
        Client.objects.create(
            full_name='Taxman Client', phone_primary='+256700000021', branch=taxman,
        )
        Client.objects.create(
            full_name='Prime Client', phone_primary='+256700000022', branch=prime_focus,
        )
        self.client.force_login(user)

        response = self.client.get(reverse('dashboard:index'))
        self.assertEqual(len(response.context['branches']), 2)
        self.assertContains(response, 'All branches')

        response = self.client.post(reverse('dashboard:switch_branch'), {
            'branch': prime_focus.pk,
            'next': reverse('clients:list'),
        })
        self.assertRedirects(response, reverse('clients:list'))
        self.assertEqual(self.client.session['active_branch_id'], prime_focus.pk)

        response = self.client.get(reverse('clients:list'))
        visible_clients = list(response.context['clients'].object_list)
        self.assertEqual([client.full_name for client in visible_clients], ['Prime Client'])
        self.assertContains(response, 'PRIME FOCUS workspace')

        self.client.post(reverse('dashboard:switch_branch'), {
            'branch': '',
            'next': reverse('dashboard:index'),
        })
        self.assertNotIn('active_branch_id', self.client.session)
        response = self.client.get(reverse('dashboard:index'))
        self.assertEqual(len(response.context['branches']), 2)

    def test_branch_dashboard_prioritizes_contextual_actions_and_hides_charts_by_default(self):
        company = Company.objects.create(name='Minimal Dashboard Co', slug='minimal-dashboard')
        taxman = Branch.objects.create(company=company, name='TAXMAN')
        prime_focus = Branch.objects.create(
            company=company, name='PRIME FOCUS', external_reporting=True,
        )
        user = User.objects.create_user(
            username='minimal-dashboard-admin', password='pass1234',
            role='admin', company=company,
        )
        self.client.force_login(user)

        self.client.post(reverse('dashboard:switch_branch'), {
            'branch': taxman.pk,
            'next': reverse('dashboard:index'),
        })
        taxman_response = self.client.get(reverse('dashboard:index'))

        self.assertContains(taxman_response, 'New client')
        self.assertContains(taxman_response, 'New engagement')
        self.assertContains(taxman_response, 'Payments &amp; receipts')
        self.assertContains(taxman_response, 'id="cashflow-mix-disclosure"')
        self.assertNotContains(taxman_response, 'id="branch-performance-disclosure"')
        self.assertNotContains(taxman_response, 'id="cashflow-mix-disclosure" open')

        self.client.post(reverse('dashboard:switch_branch'), {
            'branch': prime_focus.pk,
            'next': reverse('dashboard:index'),
        })
        prime_focus_response = self.client.get(reverse('dashboard:index'))

        self.assertContains(prime_focus_response, 'Daily entry')
        self.assertContains(prime_focus_response, 'End-of-day summary')
        self.assertContains(prime_focus_response, 'Account statement')

    def test_tax_specific_sidebar_items_are_hidden_in_external_workspaces(self):
        company = Company.objects.create(name='Navigation Co', slug='navigation')
        taxman = Branch.objects.create(company=company, name='TAXMAN')
        prime_focus = Branch.objects.create(
            company=company, name='PRIME FOCUS', external_reporting=True,
        )
        user = User.objects.create_user(
            username='navigation-admin', password='pass1234',
            role='admin', company=company,
        )
        self.client.force_login(user)

        self.client.post(reverse('dashboard:switch_branch'), {
            'branch': prime_focus.pk,
            'next': reverse('dashboard:index'),
        })
        response = self.client.get(reverse('dashboard:index'))

        self.assertTrue(response.context['external_reporting_workspace'])
        for route in (
            'services:catalogue',
            'compliance:list',
            'taxcalendar:list',
            'credentials:list',
        ):
            with self.subTest(route=route):
                self.assertNotContains(response, reverse(route))
        self.assertContains(response, reverse('services:list'))

        self.client.post(reverse('dashboard:switch_branch'), {
            'branch': taxman.pk,
            'next': reverse('dashboard:index'),
        })
        response = self.client.get(reverse('dashboard:index'))

        self.assertFalse(response.context['external_reporting_workspace'])
        for route in (
            'services:catalogue',
            'compliance:list',
            'taxcalendar:list',
            'credentials:list',
        ):
            with self.subTest(route=route):
                self.assertContains(response, reverse(route))

    def test_branch_user_cannot_switch_into_another_branch_workspace(self):
        company = Company.objects.create(name='Locked Workspace Co', slug='locked-workspace')
        assigned_branch = Branch.objects.create(company=company, name='TAXMAN')
        other_branch = Branch.objects.create(company=company, name='PRIME FOCUS')
        user = User.objects.create_user(
            username='workspace-staff', password='pass1234',
            role='tax_officer', company=company, branch=assigned_branch,
        )
        Client.objects.create(
            full_name='Assigned Client', phone_primary='+256700000023',
            branch=assigned_branch,
        )
        Client.objects.create(
            full_name='Other Branch Client', phone_primary='+256700000024',
            branch=other_branch,
        )
        self.client.force_login(user)

        response = self.client.post(reverse('dashboard:switch_branch'), {
            'branch': other_branch.pk,
            'next': reverse('clients:list'),
        })

        self.assertRedirects(response, reverse('dashboard:index'))
        self.assertNotIn('active_branch_id', self.client.session)
        response = self.client.get(reverse('clients:list'))
        visible_clients = list(response.context['clients'].object_list)
        self.assertEqual([client.full_name for client in visible_clients], ['Assigned Client'])

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

    def test_dashboard_includes_running_capital_summary(self):
        user = User.objects.create_user(
            username='capital-user',
            password='pass123',
            is_staff=True,
            is_active=True,
            is_active_staff=True,
        )
        self.client.force_login(user)

        response = self.client.get(reverse('dashboard:index'))

        self.assertEqual(response.status_code, 200)
        self.assertIn('running_capital', response.context)
        self.assertIn('summary_cards', response.context)
        self.assertTrue(response.context['summary_cards'])

    def test_running_capital_uses_entry_time_and_shows_latest_five_entries(self):
        user = User.objects.create_user(
            username='capital-entry-time-user',
            password='pass1234',
            is_staff=True,
            is_active=True,
            is_active_staff=True,
        )
        self.client.force_login(user)
        category = ExpenseCategory.objects.create(name='Entry time test')
        now = timezone.now()

        Expense.objects.create(
            expense_date=now.date() - timedelta(days=90),
            category=category,
            description='Recent entered expense',
            amount=Decimal('100'),
            created_by=user,
        )
        old_expense = Expense.objects.create(
            expense_date=now.date(),
            category=category,
            description='Old entered expense',
            amount=Decimal('500'),
            created_by=user,
        )
        Expense.objects.filter(pk=old_expense.pk).update(created_at=now - timedelta(days=40))

        for index in range(6):
            OtherIncome.objects.create(
                source_name=f'Income {index}',
                amount=Decimal('10'),
                income_date=now.date() - timedelta(days=30),
                recorded_by=user,
            )

        response = self.client.get(reverse('dashboard:index'))

        self.assertEqual(response.context['running_capital'], -40.0)
        recent = response.context['recent_cash_transactions']
        self.assertEqual(len(recent), 5)
        self.assertNotIn('Old entered expense', [item['title'] for item in recent])
        self.assertEqual(recent[0]['title'], 'Income 5')
