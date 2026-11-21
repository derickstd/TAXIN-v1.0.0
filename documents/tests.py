from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from billing.models import (
    BranchDailySummary, BranchDailyTransaction, Invoice, OtherIncome, Payment,
)
from clients.models import Client
from core.models import Branch, Company, User
from expenses.models import Expense, ExpenseCategory
from documents.forms import BranchDailySummaryForm
from documents.models import BranchAccountTransfer, BranchBalanceSheetEntry
from services.models import JobCard, JobCardLineItem, ServiceType


class DocumentReportsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='reporttester',
            password='pass1234',
            role='admin',
        )
        self.client.force_login(self.user)
        self.client_obj = Client.objects.create(
            full_name='Reporting Client',
            phone_primary='+256700000010',
            created_by=self.user,
        )

    def test_monthly_report_uses_payment_date_for_collections(self):
        # Use a far-future month to avoid polluted test database values.
        invoice_old = Invoice.objects.create(
            client=self.client_obj,
            due_date=date(2099, 3, 1),
            subtotal=Decimal('1000'),
            vat_total=Decimal('0'),
            grand_total=Decimal('1000'),
            date_issued=date(2099, 1, 10),
            status='sent',
            created_by=self.user,
        )
        pay_old = Payment.objects.create(
            invoice=invoice_old,
            amount=Decimal('500'),
            received_by=self.user,
        )
        Payment.objects.filter(pk=pay_old.pk).update(payment_date=date(2099, 2, 10))

        invoice_current = Invoice.objects.create(
            client=self.client_obj,
            due_date=date(2099, 3, 1),
            subtotal=Decimal('2000'),
            vat_total=Decimal('0'),
            grand_total=Decimal('2000'),
            status='sent',
            created_by=self.user,
        )
        Invoice.objects.filter(pk=invoice_current.pk).update(date_issued=date(2099, 2, 5))
        invoice_current.refresh_from_db()
        pay_current = Payment.objects.create(
            invoice=invoice_current,
            amount=Decimal('2500'),
            received_by=self.user,
        )
        Payment.objects.filter(pk=pay_current.pk).update(payment_date=date(2099, 2, 15))

        response = self.client.get(reverse('documents:monthly_report'), {
            'month': '2',
            'year': '2099',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_invoiced'], Decimal('2000'))
        self.assertEqual(response.context['total_collected'], Decimal('3000'))

    def test_audit_books_uses_payment_date_for_yearly_collections(self):
        invoice_current = Invoice.objects.create(
            client=self.client_obj,
            due_date=date(2025, 3, 1),
            subtotal=Decimal('2000'),
            vat_total=Decimal('0'),
            grand_total=Decimal('2000'),
            status='sent',
            created_by=self.user,
        )
        Invoice.objects.filter(pk=invoice_current.pk).update(date_issued=date(2025, 2, 5))
        invoice_current.refresh_from_db()

        invoice_old = Invoice.objects.create(
            client=self.client_obj,
            due_date=date(2024, 2, 1),
            subtotal=Decimal('1000'),
            vat_total=Decimal('0'),
            grand_total=Decimal('1000'),
            status='sent',
            created_by=self.user,
        )
        Invoice.objects.filter(pk=invoice_old.pk).update(date_issued=date(2024, 1, 10))
        invoice_old.refresh_from_db()

        pay_current = Payment.objects.create(
            invoice=invoice_current,
            amount=Decimal('2000'),
            received_by=self.user,
        )
        Payment.objects.filter(pk=pay_current.pk).update(payment_date=date(2025, 2, 15))

        pay_old = Payment.objects.create(
            invoice=invoice_old,
            amount=Decimal('500'),
            received_by=self.user,
        )
        Payment.objects.filter(pk=pay_old.pk).update(payment_date=date(2025, 2, 18))

        response = self.client.get(reverse('documents:audit_books'), {
            'year': '2025',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_revenue'], Decimal('2000'))
        self.assertEqual(response.context['total_collected'], Decimal('2500'))

    def test_financial_reports_reconcile_cash_and_show_receivables(self):
        Payment.objects.create(
            client=self.client_obj,
            amount=Decimal('1000'),
            payment_date=date(2099, 1, 15),
            received_by=self.user,
        )
        OtherIncome.objects.create(
            source_name='Opening period grant',
            amount=Decimal('100'),
            income_date=date(2099, 1, 20),
            recorded_by=self.user,
        )
        Expense.objects.create(
            expense_date=date(2099, 1, 25),
            description='Prior period expense',
            amount=Decimal('50'),
            status='approved',
            paid_by=self.user,
            created_by=self.user,
            approved_by=self.user,
        )

        invoice = Invoice.objects.create(
            client=self.client_obj,
            due_date=date(2099, 3, 1),
            subtotal=Decimal('1000'),
            vat_total=Decimal('0'),
            grand_total=Decimal('1000'),
            status='sent',
            created_by=self.user,
        )
        Invoice.objects.filter(pk=invoice.pk).update(date_issued=date(2099, 2, 5))
        invoice.refresh_from_db()
        Payment.objects.create(
            invoice=invoice,
            amount=Decimal('300'),
            payment_date=date(2099, 2, 15),
            received_by=self.user,
        )
        OtherIncome.objects.create(
            source_name='Current period interest',
            amount=Decimal('70'),
            income_date=date(2099, 2, 18),
            recorded_by=self.user,
        )
        Expense.objects.create(
            expense_date=date(2099, 2, 20),
            description='Current period expense',
            amount=Decimal('125'),
            status='approved',
            paid_by=self.user,
            created_by=self.user,
            approved_by=self.user,
        )
        Expense.objects.create(
            expense_date=date(2099, 2, 22),
            description='Pending expense',
            amount=Decimal('500'),
            status='submitted',
            paid_by=self.user,
            created_by=self.user,
        )

        response = self.client.get(reverse('documents:financial_reports'), {
            'from': '2099-02-01',
            'to': '2099-02-28',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['opening_cash'], Decimal('1050'))
        self.assertEqual(response.context['customer_receipts'], Decimal('300'))
        self.assertEqual(response.context['other_receipts'], Decimal('70'))
        self.assertEqual(response.context['cash_outflow'], Decimal('125'))
        self.assertEqual(response.context['net_cash_flow'], Decimal('245'))
        self.assertEqual(response.context['closing_cash'], Decimal('1295'))
        self.assertEqual(response.context['accounts_receivable'], Decimal('700'))
        self.assertEqual(response.context['tracked_assets'], Decimal('1995'))
        self.assertEqual(response.context['transactions'].paginator.count, 3)
        self.assertContains(response, 'Cash Flow Statement')
        self.assertNotContains(response, 'Balance Sheet Snapshot')
        self.assertContains(response, reverse('documents:balance_sheet_report'))

    def test_cash_flow_and_balance_sheet_are_separate_reports(self):
        cash_flow = self.client.get(reverse('documents:financial_reports'), {
            'period': 'this_week',
        })
        balance_sheet = self.client.get(reverse('documents:balance_sheet_report'), {
            'period': 'this_week',
        })

        self.assertEqual(cash_flow.status_code, 200)
        self.assertEqual(balance_sheet.status_code, 200)
        self.assertEqual(balance_sheet.context['report_view'], 'balance_sheet')
        self.assertContains(cash_flow, 'Cash Accountability')
        self.assertNotContains(cash_flow, 'Balance Sheet Snapshot')
        self.assertContains(balance_sheet, 'Balance Sheet Snapshot')
        self.assertContains(balance_sheet, 'Total tracked assets')
        self.assertNotContains(balance_sheet, 'Cash Accountability')

    def test_financial_reports_reject_reversed_date_range(self):
        response = self.client.get(reverse('documents:financial_reports'), {
            'from': '2099-02-28',
            'to': '2099-02-01',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'The start date must be on or before the end date.')

    def test_capital_injections_and_drawings_are_separate_from_operating_profit(self):
        company = Company.objects.create(name='Capital Report Co', slug='capital-report')
        internal_branch = Branch.objects.create(company=company, name='TAXMAN')
        external_branch = Branch.objects.create(
            company=company, name='ABA UGANDA', external_reporting=True,
        )
        self.user.company = company
        self.user.branch = internal_branch
        self.user.save(update_fields=['company', 'branch'])
        today = timezone.localdate()
        drawing_category, _ = ExpenseCategory.objects.get_or_create(name='Drawing')
        OtherIncome.objects.create(
            source_name='Capital injection', category='capital_injection',
            amount=Decimal('1000'), income_date=today,
            recorded_by=self.user, branch=internal_branch,
        )
        Expense.objects.create(
            expense_date=today, category=drawing_category,
            description='Owner withdrawal', amount=Decimal('200'),
            status='approved', paid_by=self.user, created_by=self.user,
            approved_by=self.user, branch=internal_branch,
        )
        for branch, direction, category, amount in (
            (external_branch, 'inflow', 'capital_injection', '500'),
            (external_branch, 'outflow', 'drawing', '50'),
        ):
            BranchDailyTransaction.objects.create(
                branch=branch, business_date=today, direction=direction,
                category=category, description='Capital activity',
                amount=Decimal(amount), entered_by=self.user,
            )

        response = self.client.get(reverse('documents:financial_reports'), {
            'period': 'this_month',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['capital_injection_total'], Decimal('1500'))
        self.assertEqual(response.context['drawing_total'], Decimal('250'))
        self.assertEqual(response.context['capital_net_total'], Decimal('1250'))
        self.assertEqual(response.context['cash_inflow'], Decimal('1500'))
        self.assertEqual(response.context['cash_outflow'], Decimal('250'))
        comparison = {
            row['branch'].pk: row for row in response.context['branch_comparison']
        }
        self.assertEqual(comparison[internal_branch.pk]['operating_inflow'], Decimal('0'))
        self.assertEqual(comparison[internal_branch.pk]['operating_profit'], Decimal('0'))
        self.assertEqual(comparison[external_branch.pk]['operating_inflow'], Decimal('0'))
        self.assertEqual(comparison[external_branch.pk]['operating_profit'], Decimal('0'))

        injection_rows = self.client.get(
            reverse('documents:financial_reports'),
            {'period': 'this_month', 'record_type': 'capital_injection'},
        )
        drawing_rows = self.client.get(
            reverse('documents:financial_reports'),
            {'period': 'this_month', 'record_type': 'drawing'},
        )
        self.assertEqual(len(list(injection_rows.context['transactions'])), 2)
        self.assertEqual(len(list(drawing_rows.context['transactions'])), 2)

    def test_financial_report_filters_service_category_method_and_record_type(self):
        today = timezone.localdate()
        filing_service = ServiceType.objects.create(
            name='URA Filing Report Test', category='ura_filing',
        )
        advisory_service = ServiceType.objects.create(
            name='Advisory Report Test', category='advisory',
        )
        Payment.objects.create(
            client=self.client_obj, service_type=filing_service,
            amount=Decimal('100'), payment_date=today, received_by=self.user,
        )
        Payment.objects.create(
            client=self.client_obj, service_type=advisory_service,
            amount=Decimal('75'), payment_date=today, received_by=self.user,
        )
        Payment.objects.create(
            client=self.client_obj, amount=Decimal('20'),
            payment_date=today, received_by=self.user,
        )
        category = ExpenseCategory.objects.create(name='Report Filter Expense')
        Expense.objects.create(
            expense_date=today, category=category, description='Filtered expense',
            amount=Decimal('30'), payment_method='mobile_money',
            status='approved', paid_by=self.user, created_by=self.user,
            approved_by=self.user,
        )
        Expense.objects.create(
            expense_date=today, description='Uncategorized expense',
            amount=Decimal('10'), payment_method='cash',
            status='approved', paid_by=self.user, created_by=self.user,
            approved_by=self.user,
        )

        service_response = self.client.get(reverse('documents:financial_reports'), {
            'period': 'this_week',
            'service': filing_service.pk,
        })

        self.assertEqual(service_response.status_code, 200)
        self.assertEqual(service_response.context['period'], 'this_week')
        self.assertEqual(
            service_response.context['date_from'],
            today - timezone.timedelta(days=today.weekday()),
        )
        self.assertEqual(service_response.context['date_to'], today)
        self.assertEqual(
            service_response.context['period_options'],
            [('this_week', 'This week'), ('this_month', 'This month')],
        )
        self.assertEqual(service_response.context['cash_inflow'], Decimal('195'))
        self.assertEqual(service_response.context['cash_outflow'], Decimal('40'))
        service_rows = list(service_response.context['transactions'])
        self.assertEqual(len(service_rows), 1)
        self.assertEqual(service_rows[0]['service_names'], [filing_service.name])
        self.assertContains(
            service_response,
            '<label class="form-label" for="report-period">Reporting period</label>',
        )

        expense_response = self.client.get(reverse('documents:financial_reports'), {
            'period': 'this_week',
            'category': f'expense:{category.pk}',
            'record_type': 'expense',
            'method': 'mobile_money',
        })

        self.assertEqual(expense_response.status_code, 200)
        self.assertEqual(expense_response.context['cash_inflow'], Decimal('195'))
        self.assertEqual(expense_response.context['cash_outflow'], Decimal('40'))
        expense_rows = list(expense_response.context['transactions'])
        self.assertEqual(len(expense_rows), 1)
        self.assertEqual(expense_rows[0]['type_key'], 'expense')
        self.assertEqual(expense_rows[0]['outflow'], Decimal('30'))

        uncategorized_payment_response = self.client.get(
            reverse('documents:financial_reports'),
            {'period': 'this_week', 'category': 'payment:uncategorized'},
        )
        uncategorized_expense_response = self.client.get(
            reverse('documents:financial_reports'),
            {'period': 'this_week', 'category': 'expense:uncategorized'},
        )

        self.assertEqual(
            len(list(uncategorized_payment_response.context['transactions'])), 1,
        )
        self.assertEqual(
            list(uncategorized_payment_response.context['transactions'])[0]['type_key'],
            'payment',
        )
        self.assertEqual(
            len(list(uncategorized_expense_response.context['transactions'])), 1,
        )
        self.assertEqual(
            list(uncategorized_expense_response.context['transactions'])[0]['type_key'],
            'expense',
        )

    def test_financial_report_pagination_preserves_active_filters(self):
        today = timezone.localdate()
        service = ServiceType.objects.create(
            name='Pagination Report Test', category='ura_filing',
        )
        Payment.objects.bulk_create([
            Payment(
                client=self.client_obj, service_type=service,
                amount=Decimal('1'), payment_date=today, received_by=self.user,
            )
            for _ in range(51)
        ])

        response = self.client.get(reverse('documents:financial_reports'), {
            'period': 'this_week',
            'service': service.pk,
        })

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['transactions'].has_next())
        self.assertEqual(
            response.context['filter_query'],
            f'period=this_week&service={service.pk}',
        )


class ExternalBranchReportTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Branch Report Co', slug='branch-report')
        self.branch = Branch.objects.create(
            company=self.company, name='PRIME FOCUS', external_reporting=True,
        )
        self.other_branch = Branch.objects.create(
            company=self.company, name='ABA UGANDA', external_reporting=True,
        )
        self.manager = User.objects.create_user(
            username='prime_manager', password='pass1234', role='manager',
            company=self.company, branch=self.branch,
        )
        self.client.force_login(self.manager)
        BranchDailySummary.objects.create(
            branch=self.branch, business_date=date(2099, 1, 3),
            opening_balance=Decimal('800'), cash_inflow=Decimal('100'),
            cash_outflow=Decimal('50'), closing_balance=Decimal('850'),
            submitted_by=self.manager,
        )
        BranchDailySummary.objects.create(
            branch=self.branch, business_date=date(2099, 1, 4),
            opening_balance=Decimal('850'), cash_inflow=Decimal('200'),
            cash_outflow=Decimal('30'), closing_balance=Decimal('1020'),
            submitted_by=self.manager,
        )
        BranchDailySummary.objects.create(
            branch=self.other_branch, business_date=date(2099, 1, 4),
            opening_balance=Decimal('0'), cash_inflow=Decimal('999'),
            cash_outflow=Decimal('0'), closing_balance=Decimal('999'),
            submitted_by=self.manager,
        )

    def test_external_daily_summaries_roll_up_for_assigned_branch_only(self):
        response = self.client.get(reverse('documents:financial_reports'), {
            'from': '2099-01-03',
            'to': '2099-01-04',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['cash_inflow'], Decimal('300'))
        self.assertEqual(response.context['cash_outflow'], Decimal('80'))
        self.assertEqual(response.context['opening_cash'], Decimal('800'))
        self.assertEqual(response.context['closing_cash'], Decimal('1020'))
        self.assertEqual(
            [row['branch'].pk for row in response.context['branch_comparison']],
            [self.branch.pk],
        )
        self.assertEqual(response.context['selected_branch'], self.branch)
        self.assertEqual(response.context['transactions'].paginator.count, 2)

    def test_daily_summary_form_defaults_to_users_only_external_branch(self):
        form = BranchDailySummaryForm(
            branches=Branch.objects.filter(pk=self.branch.pk),
        )

        self.assertEqual(form['branch'].value(), self.branch.pk)

    def test_daily_entry_form_opens_as_modal_from_branch_page(self):
        response = self.client.get(reverse('documents:branch_daily_summaries'))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['open_summary_modal'])
        self.assertEqual(response.context['form']['branch'].value(), self.branch.pk)
        self.assertContains(response, 'id="branchEntryModal"')
        self.assertContains(response, 'Branch reports')
        self.assertContains(response, 'Transaction ledger')
        self.assertContains(response, 'Bank deposit')

        response = self.client.get(
            reverse('documents:branch_daily_summaries'),
            {'open': 'summary'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['open_summary_modal'])
        self.assertContains(response, 'class="modal-overlay open"')
        self.assertContains(response, "searchParams.delete('open')")

    def test_external_daily_summary_prefills_balances_and_ledger_totals(self):
        business_date = timezone.localdate()
        previous_summary_date = business_date - timezone.timedelta(days=2)
        BranchDailySummary.objects.create(
            branch=self.branch, business_date=previous_summary_date,
            opening_balance=Decimal('900'), cash_inflow=Decimal('100'),
            cash_outflow=Decimal('0'), closing_balance=Decimal('1000'),
            submitted_by=self.manager,
        )
        for entry_date, direction, category, amount in (
            (business_date - timezone.timedelta(days=1), 'inflow', 'service_receipt', '300'),
            (business_date - timezone.timedelta(days=1), 'outflow', 'operating_expense', '50'),
            (business_date, 'inflow', 'service_receipt', '150'),
            (business_date, 'outflow', 'operating_expense', '20'),
        ):
            BranchDailyTransaction.objects.create(
                branch=self.branch, business_date=entry_date,
                direction=direction, category=category,
                description='Daily summary prefill test', account='cash',
                amount=Decimal(amount), entered_by=self.manager,
            )

        response = self.client.get(reverse('documents:branch_daily_summaries'), {
            'branch': self.branch.pk,
            'date': business_date.isoformat(),
            'open': 'summary',
        })

        self.assertEqual(response.status_code, 200)
        form = response.context['form']
        self.assertEqual(form['opening_balance'].value(), Decimal('1250'))
        self.assertEqual(form['cash_inflow'].value(), Decimal('150'))
        self.assertEqual(form['cash_outflow'].value(), Decimal('20'))
        self.assertEqual(form['closing_balance'].value(), Decimal('1380'))
        self.assertContains(response, 'updateClosingBalance')

    def test_external_opening_balance_includes_ledger_history_without_prior_summary(self):
        business_date = timezone.localdate()
        for direction, category, amount in (
            ('inflow', 'service_receipt', '400'),
            ('outflow', 'operating_expense', '100'),
        ):
            BranchDailyTransaction.objects.create(
                branch=self.branch,
                business_date=business_date - timezone.timedelta(days=1),
                direction=direction, category=category,
                description='Prior ledger balance', account='cash',
                amount=Decimal(amount), entered_by=self.manager,
            )

        response = self.client.get(reverse('documents:branch_daily_summaries'), {
            'branch': self.branch.pk,
            'date': business_date.isoformat(),
            'open': 'summary',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context['form']['opening_balance'].value(),
            Decimal('300'),
        )

    def test_invalid_daily_entry_keeps_modal_open(self):
        response = self.client.post(reverse('documents:branch_daily_summaries'), {
            'branch': self.branch.pk,
            'business_date': '2099-01-01',
            'opening_balance': '0',
            'cash_inflow': '0',
            'cash_outflow': '0',
            'closing_balance': '0',
            'notes': '',
        })

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['open_summary_modal'])
        self.assertContains(response, 'A daily summary cannot be dated in the future.')

    def test_manager_cannot_select_another_branch_report(self):
        response = self.client.get(reverse('documents:financial_reports'), {
            'branch': self.other_branch.pk,
        })

        self.assertEqual(response.status_code, 404)
        ledger_response = self.client.get(reverse('documents:branch_daily_ledger'), {
            'branch': self.other_branch.pk,
        })
        self.assertEqual(ledger_response.status_code, 404)

    def test_daily_ledger_records_external_transactions_and_blocks_duplicate_references(self):
        business_date = timezone.localdate()
        url = reverse('documents:branch_daily_ledger')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['form']['branch'].value(), self.branch.pk)
        self.assertContains(response, 'Daily Transaction Ledger')
        self.assertContains(response, 'class="form-control"')
        self.assertContains(response, 'What was received or paid?')
        self.assertContains(response, 'Record money in or out for the selected branch.')
        self.assertContains(response, 'ledgerCategoryDirections')
        ledger_html = response.content.decode()
        filter_card_start = ledger_html.index('<section class="card-box mb-3">')
        filter_card_end = ledger_html.index('</section>', filter_card_start)
        add_transaction_position = ledger_html.index('id="openLedgerEntryModal"')
        self.assertLess(filter_card_start, add_transaction_position)
        self.assertLess(add_transaction_position, filter_card_end)
        self.assertNotIn('page-header-actions', ledger_html)

        payload = {
            'branch': self.branch.pk,
            'business_date': business_date.isoformat(),
            'direction': 'inflow',
            'category': 'service_receipt',
            'description': 'Tax service payment',
            'account': 'cash',
            'amount': '125000',
            'reference': 'PF-1001',
        }
        response = self.client.post(url, payload)
        self.assertRedirects(
            response,
            f'{url}?branch={self.branch.pk}&date={business_date.isoformat()}',
        )
        self.assertEqual(BranchDailyTransaction.objects.count(), 1)

        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertEqual(BranchDailyTransaction.objects.count(), 1)

    def test_expense_shortcut_prefills_external_branch_outflow(self):
        response = self.client.get(reverse('documents:branch_daily_expense'), {
            'branch': self.branch.pk,
            'open': 'transaction',
        })

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['open_transaction_modal'])
        self.assertTrue(response.context['expense_only'])
        self.assertEqual(response.context['form']['branch'].value(), self.branch.pk)
        self.assertEqual(response.context['form']['direction'].value(), 'outflow')
        self.assertEqual(response.context['form']['category'].value(), 'operating_expense')
        self.assertContains(
            response,
            f'{reverse("documents:branch_daily_expense")}?branch={self.branch.pk}&amp;open=transaction',
        )
        self.assertNotContains(response, 'Service / customer receipt')
        self.assertContains(response, 'Record money out only')

    def test_expense_only_ledger_rejects_money_in(self):
        response = self.client.post(reverse('documents:branch_daily_expense'), {
            'branch': self.branch.pk,
            'business_date': timezone.localdate().isoformat(),
            'direction': 'inflow',
            'category': 'service_receipt',
            'description': 'Should not be recorded as an expense',
            'account': 'cash',
            'amount': '100',
        })

        self.assertEqual(response.status_code, 200)
        self.assertIn('Expense entries must record money out.', response.context['form']['direction'].errors)
        self.assertFalse(BranchDailyTransaction.objects.exists())

    def test_daily_ledger_uses_detail_totals_in_cash_flow_without_double_counting_summary(self):
        business_date = timezone.localdate()
        BranchDailySummary.objects.create(
            branch=self.branch, business_date=business_date,
            opening_balance=Decimal('1000'), cash_inflow=Decimal('999'),
            cash_outflow=Decimal('700'), closing_balance=Decimal('1299'),
            submitted_by=self.manager,
        )
        BranchDailyTransaction.objects.create(
            branch=self.branch, business_date=business_date,
            direction='inflow', category='service_receipt',
            description='Service fee', account='cash',
            amount=Decimal('300'), entered_by=self.manager,
        )
        BranchDailyTransaction.objects.create(
            branch=self.branch, business_date=business_date,
            direction='outflow', category='operating_expense',
            description='Office supplies', account='mobile_money',
            amount=Decimal('50'), entered_by=self.manager,
        )

        response = self.client.get(reverse('documents:financial_reports'), {
            'from': business_date.isoformat(),
            'to': business_date.isoformat(),
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['cash_inflow'], Decimal('300'))
        self.assertEqual(response.context['cash_outflow'], Decimal('50'))
        self.assertEqual(response.context['branch_comparison'][0]['closing_cash'], Decimal('1299'))
        self.assertEqual(response.context['transactions'].paginator.count, 2)

    def test_daily_ledger_rejects_category_direction_mismatch(self):
        response = self.client.post(reverse('documents:branch_daily_ledger'), {
            'branch': self.branch.pk,
            'business_date': timezone.localdate().isoformat(),
            'direction': 'inflow',
            'category': 'operating_expense',
            'description': 'Incorrectly classified',
            'account': 'cash',
            'amount': '100',
            'reference': '',
        })

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertFalse(BranchDailyTransaction.objects.exists())

    def test_reviewed_summary_locks_new_ledger_transactions(self):
        business_date = timezone.localdate()
        BranchDailySummary.objects.create(
            branch=self.branch, business_date=business_date,
            opening_balance=Decimal('0'), cash_inflow=Decimal('0'),
            cash_outflow=Decimal('0'), closing_balance=Decimal('0'),
            submitted_by=self.manager, reviewed_by=self.manager,
            reviewed_at=timezone.now(),
        )
        response = self.client.post(reverse('documents:branch_daily_ledger'), {
            'branch': self.branch.pk,
            'business_date': business_date.isoformat(),
            'direction': 'inflow',
            'category': 'service_receipt',
            'description': 'Late entry',
            'account': 'cash',
            'amount': '100',
            'reference': 'LATE-1',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'reviewed and locked')
        self.assertFalse(BranchDailyTransaction.objects.exists())

    def test_summary_cannot_be_reviewed_until_ledger_totals_match(self):
        business_date = timezone.localdate()
        summary = BranchDailySummary.objects.create(
            branch=self.branch, business_date=business_date,
            opening_balance=Decimal('100'), cash_inflow=Decimal('200'),
            cash_outflow=Decimal('0'), closing_balance=Decimal('300'),
            submitted_by=self.manager,
        )
        BranchDailyTransaction.objects.create(
            branch=self.branch, business_date=business_date,
            direction='inflow', category='service_receipt',
            description='Service fee', account='cash',
            amount=Decimal('150'), entered_by=self.manager,
        )
        review_url = reverse(
            'documents:review_branch_daily_summary', args=[summary.pk],
        )

        self.client.post(review_url)
        summary.refresh_from_db()
        self.assertIsNone(summary.reviewed_at)

        BranchDailySummary.objects.filter(pk=summary.pk).update(
            cash_inflow=Decimal('150'),
        )
        self.client.post(review_url)
        summary.refresh_from_db()
        self.assertIsNotNone(summary.reviewed_at)


class InternalBranchDailySummaryTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='TAXMAN Co', slug='taxman-co')
        self.branch = Branch.objects.create(
            company=self.company, name='TAXMAN', external_reporting=False,
        )
        self.manager = User.objects.create_user(
            username='taxman_manager', password='pass1234', role='manager',
            company=self.company, branch=self.branch,
        )
        self.client.force_login(self.manager)

    def test_internal_daily_summary_prefills_from_prior_balance_and_system_transactions(self):
        business_date = timezone.localdate()
        previous_summary_date = business_date - timezone.timedelta(days=2)
        BranchDailySummary.objects.create(
            branch=self.branch, business_date=previous_summary_date,
            opening_balance=Decimal('900'), cash_inflow=Decimal('100'),
            cash_outflow=Decimal('0'), closing_balance=Decimal('1000'),
            submitted_by=self.manager,
        )
        Payment.objects.create(
            amount=Decimal('300'), payment_date=business_date - timezone.timedelta(days=1),
            received_by=self.manager, branch=self.branch,
        )
        OtherIncome.objects.create(
            source_name='Previous day income', amount=Decimal('100'),
            income_date=business_date - timezone.timedelta(days=1),
            recorded_by=self.manager, branch=self.branch,
        )
        Expense.objects.create(
            expense_date=business_date - timezone.timedelta(days=1),
            description='Previous day expense', amount=Decimal('50'),
            status='approved', paid_by=self.manager, created_by=self.manager,
            branch=self.branch,
        )
        Payment.objects.create(
            amount=Decimal('400'), payment_date=business_date,
            received_by=self.manager, branch=self.branch,
        )
        OtherIncome.objects.create(
            source_name='Today income', amount=Decimal('20'),
            income_date=business_date, recorded_by=self.manager,
            branch=self.branch,
        )
        Expense.objects.create(
            expense_date=business_date, description='Today expense',
            amount=Decimal('70'), status='approved', paid_by=self.manager,
            created_by=self.manager, branch=self.branch,
        )

        response = self.client.get(reverse('documents:branch_daily_summaries'), {
            'branch': self.branch.pk,
            'date': business_date.isoformat(),
            'open': 'summary',
        })

        self.assertEqual(response.status_code, 200)
        form = response.context['form']
        self.assertEqual(form['opening_balance'].value(), Decimal('1350'))
        self.assertEqual(form['cash_inflow'].value(), Decimal('420'))
        self.assertEqual(form['cash_outflow'].value(), Decimal('70'))
        self.assertEqual(form['closing_balance'].value(), Decimal('1700'))

    def test_daily_ledger_shows_taxman_system_recorded_payments(self):
        business_date = timezone.localdate()
        Payment.objects.create(
            amount=Decimal('500'), payment_date=business_date,
            received_by=self.manager, branch=self.branch,
        )

        response = self.client.get(reverse('documents:branch_daily_ledger'), {
            'branch': self.branch.pk,
            'date': business_date.isoformat(),
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Customer payment')
        self.assertContains(response, 'Direct payment')
        self.assertEqual(response.context['total_inflow'], Decimal('500'))

    def test_expense_form_submission_appears_pending_then_updates_ledger_on_approval(self):
        business_date = timezone.localdate()
        category = ExpenseCategory.objects.create(name='Ledger Approval Test')
        create_response = self.client.post(reverse('expenses:create'), {
            'expense_date': business_date.isoformat(),
            'category': category.pk,
            'description': 'Branch electricity',
            'amount': '25000',
            'payment_method': 'cash',
        })

        self.assertEqual(create_response.status_code, 302)
        expense = Expense.objects.get(description='Branch electricity')
        self.assertEqual(expense.branch, self.branch)
        ledger_url = reverse('documents:branch_daily_ledger')
        ledger_response = self.client.get(ledger_url, {
            'branch': self.branch.pk,
            'date': business_date.isoformat(),
        })

        self.assertEqual(ledger_response.status_code, 200)
        self.assertEqual(ledger_response.context['transactions'].paginator.count, 1)
        self.assertEqual(ledger_response.context['transactions'][0]['type'], 'Pending expense')
        self.assertEqual(ledger_response.context['total_outflow'], Decimal('0'))

        self.client.post(reverse('expenses:approve', args=[expense.pk]))
        ledger_response = self.client.get(ledger_url, {
            'branch': self.branch.pk,
            'date': business_date.isoformat(),
        })

        self.assertEqual(ledger_response.context['transactions'].paginator.count, 1)
        self.assertEqual(ledger_response.context['transactions'][0]['type'], 'Approved expense')
        self.assertEqual(ledger_response.context['total_outflow'], Decimal('25000'))

    def test_daily_entry_includes_taxman_and_replaces_same_day_transactions_in_reports(self):
        entry_response = self.client.get(reverse('documents:branch_daily_summaries'))
        self.assertEqual(entry_response.status_code, 200)
        self.assertEqual(entry_response.context['form']['branch'].value(), self.branch.pk)
        self.assertContains(entry_response, 'TAXMAN')

        business_date = timezone.localdate()
        Payment.objects.create(
            amount=Decimal('999'), payment_date=business_date,
            received_by=self.manager, branch=self.branch,
        )
        save_response = self.client.post(reverse('documents:branch_daily_summaries'), {
            'branch': self.branch.pk,
            'business_date': business_date.isoformat(),
            'opening_balance': '1000',
            'cash_inflow': '400',
            'cash_outflow': '100',
            'closing_balance': '1300',
            'notes': '',
        })
        self.assertEqual(save_response.status_code, 302)

        response = self.client.get(reverse('documents:financial_reports'), {
            'from': business_date.isoformat(),
            'to': business_date.isoformat(),
            'branch': self.branch.pk,
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['customer_receipts'], Decimal('400'))
        self.assertEqual(response.context['cash_outflow'], Decimal('100'))
        self.assertEqual(response.context['opening_cash'], Decimal('1000'))
        self.assertEqual(response.context['closing_cash'], Decimal('1300'))
        self.assertEqual(response.context['transactions'].paginator.count, 1)


class BranchAccountingReportTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name='Branch Accounting Co', slug='branch-accounting',
        )
        self.branch = Branch.objects.create(
            company=self.company, name='TAXMAN',
        )
        self.external_branch = Branch.objects.create(
            company=self.company, name='ABA UGANDA', external_reporting=True,
        )
        self.user = User.objects.create_user(
            username='accounting_manager', password='pass1234',
            role='manager', company=self.company, branch=self.branch,
        )
        self.client.force_login(self.user)
        self.client_obj = Client.objects.create(
            full_name='Balance Sheet Client',
            phone_primary='+256700000090',
            branch=self.branch,
            created_by=self.user,
        )

    def test_detailed_balance_sheet_uses_receivables_wip_and_manual_balances(self):
        today = timezone.localdate()
        invoice = Invoice.objects.create(
            client=self.client_obj,
            branch=self.branch,
            due_date=today + timezone.timedelta(days=14),
            subtotal=Decimal('1000'),
            grand_total=Decimal('1000'),
            status='sent',
            created_by=self.user,
        )
        Payment.objects.create(
            invoice=invoice, amount=Decimal('200'), payment_date=today,
            method='cash', received_by=self.user, branch=self.branch,
        )
        job = JobCard.objects.create(
            client=self.client_obj, branch=self.branch, status='in_progress',
            created_by=self.user,
        )
        JobCardLineItem.objects.create(
            job_card=job, negotiated_price=Decimal('500'),
            vat_amount=Decimal('0'), status='not_handled',
        )
        BranchBalanceSheetEntry.objects.create(
            branch=self.branch, account_name='Cash at hand',
            category='cash_on_hand', amount=Decimal('5000'),
            as_of_date=today, entered_by=self.user,
        )
        BranchBalanceSheetEntry.objects.create(
            branch=self.branch, account_name='Main supplier',
            category='creditor', amount=Decimal('100'),
            as_of_date=today, entered_by=self.user,
        )
        BranchBalanceSheetEntry.objects.create(
            branch=self.branch, account_name='Opening capital',
            category='owner_capital', amount=Decimal('2000'),
            as_of_date=today, entered_by=self.user,
        )

        response = self.client.get(reverse('documents:balance_sheet_report'), {
            'branch': self.branch.pk,
            'from': today.isoformat(),
            'to': today.isoformat(),
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['accounts_receivable'], Decimal('800'))
        self.assertEqual(response.context['work_in_progress'], Decimal('500'))
        self.assertEqual(response.context['total_assets'], Decimal('6300'))
        self.assertEqual(response.context['total_liabilities'], Decimal('100'))
        self.assertEqual(response.context['total_equity'], Decimal('2200'))
        self.assertEqual(response.context['balance_difference'], Decimal('4000'))
        self.assertContains(response, 'contract-value estimate')
        self.assertContains(response, 'Main supplier')

        save_response = self.client.post(
            reverse('documents:balance_sheet_report'), {
                'branch': self.branch.pk,
                'as_of_date': today.isoformat(),
                'category': 'fixed_asset',
                'account_name': 'Office equipment',
                'amount': '750',
                'notes': 'Dated opening balance',
            },
        )
        self.assertEqual(save_response.status_code, 302)
        self.assertTrue(BranchBalanceSheetEntry.objects.filter(
            branch=self.branch, account_name='Office equipment',
            category='fixed_asset', amount=Decimal('750'),
        ).exists())

    def test_account_statement_and_transfer_keep_bank_deposits_out_of_expenses(self):
        today = timezone.localdate()
        Payment.objects.create(
            amount=Decimal('150'), payment_date=today, method='cash',
            received_by=self.user, branch=self.branch,
        )
        transfer = self.client.post(
            reverse('documents:branch_account_transfer'), {
                'branch': self.branch.pk,
                'transfer_date': today.isoformat(),
                'source_account': 'cash',
                'destination_account': 'bank',
                'amount': '50',
                'description': 'Daily banking',
                'reference': 'BANK-001',
            },
        )

        self.assertEqual(transfer.status_code, 302)
        statement = self.client.get(reverse('documents:branch_account_statement'), {
            'branch': self.branch.pk,
            'from': today.isoformat(),
            'to': today.isoformat(),
        })
        balance_sheet = self.client.get(reverse('documents:balance_sheet_report'), {
            'branch': self.branch.pk,
            'from': today.isoformat(),
            'to': today.isoformat(),
        })
        ledger = self.client.get(reverse('documents:branch_daily_ledger'), {
            'branch': self.branch.pk,
            'date': today.isoformat(),
        })

        self.assertEqual(statement.status_code, 200)
        self.assertContains(statement, 'floatingAccountTransferButton')
        self.assertContains(statement, 'aria-label="Record a payment"')
        self.assertContains(statement, 'aria-label="Record Bank Transfer"')
        self.assertContains(statement, "overlay.classList.add('open')")
        self.assertNotContains(statement, '<span>Record Payment</span>')
        self.assertNotContains(statement, '<span>Record Expense</span>')
        self.assertNotContains(statement, '<span>Bank transfer</span>')
        self.assertEqual(statement.context['total_inflow'], Decimal('200'))
        self.assertEqual(statement.context['total_outflow'], Decimal('50'))
        self.assertContains(statement, 'Daily banking')
        self.assertEqual(
            balance_sheet.context['cash_account_totals']['cash_on_hand'],
            Decimal('100'),
        )
        self.assertEqual(
            balance_sheet.context['cash_account_totals']['bank_deposit'],
            Decimal('50'),
        )
        self.assertEqual(ledger.context['total_inflow'], Decimal('150'))
        self.assertEqual(ledger.context['total_outflow'], Decimal('0'))
        self.assertContains(ledger, 'Bank deposit transfer')
        transfer_rows = [
            row for row in ledger.context['transactions']
            if row['type'] == 'Bank deposit transfer'
        ]
        self.assertEqual(len(transfer_rows), 2)
        self.assertEqual(
            sum(row['inflow'] for row in transfer_rows),
            Decimal('50'),
        )
        self.assertEqual(
            sum(row['outflow'] for row in transfer_rows),
            Decimal('50'),
        )
        self.assertFalse(Expense.objects.exists())

    def test_account_transfer_records_bank_charges_as_expense(self):
        today = timezone.localdate()
        url = f"{reverse('documents:branch_account_transfer')}?popover=1"
        response = self.client.post(
            url,
            {
                'branch': self.branch.pk,
                'transfer_date': today.isoformat(),
                'source_account': 'cash',
                'destination_account': 'bank',
                'amount': '50000',
                'bank_charges': '1250.50',
                'description': 'Daily banking',
                'reference': 'BANK-FEE-001',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            {
                'message': (
                    'Bank deposit recorded. Bank charges of UGX 1,250.50 '
                    'were recorded as an expense.'
                ),
            },
        )
        transfer = BranchAccountTransfer.objects.get(reference='BANK-FEE-001')
        charge = Expense.objects.get(reference='BANK-FEE-001')
        self.assertEqual(transfer.amount, Decimal('50000'))
        self.assertEqual(charge.category.name, 'Bank Charges')
        self.assertEqual(charge.amount, Decimal('1250.50'))
        self.assertEqual(charge.branch, self.branch)
        self.assertEqual(charge.expense_date, today)
        self.assertEqual(charge.payment_method, 'bank_transfer')
        self.assertEqual(charge.paid_by, self.user)
        self.assertEqual(charge.created_by, self.user)
        self.assertEqual(charge.status, 'submitted')
        self.assertIn('BANK-FEE-001', charge.description)

    def test_account_transfer_popover_loads_validates_and_records(self):
        today = timezone.localdate()
        url = f"{reverse('documents:branch_account_transfer')}?popover=1"
        form_response = self.client.get(url, {'branch': self.branch.pk})

        self.assertEqual(form_response.status_code, 200)
        self.assertContains(form_response, 'Record Bank Transfer')
        self.assertContains(form_response, 'data-branch-transfer-form')
        self.assertContains(form_response, 'name="bank_charges"')
        self.assertEqual(form_response.context['selected_branch'], self.branch)

        invalid_response = self.client.post(
            url, {
                'branch': self.branch.pk,
                'transfer_date': today.isoformat(),
                'source_account': 'cash',
                'destination_account': 'bank',
                'amount': '',
                'description': 'Daily banking',
                'reference': '',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(invalid_response.status_code, 400)
        self.assertContains(invalid_response, 'data-branch-transfer-form', status_code=400)

        same_account_response = self.client.post(
            url, {
                'branch': self.branch.pk,
                'transfer_date': today.isoformat(),
                'source_account': 'cash',
                'destination_account': 'cash',
                'amount': '25',
                'description': 'Invalid transfer',
                'reference': '',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(same_account_response.status_code, 400)
        self.assertContains(
            same_account_response,
            'Choose an account different from the source account.',
            status_code=400,
        )

        save_response = self.client.post(
            url, {
                'branch': self.branch.pk,
                'transfer_date': today.isoformat(),
                'source_account': 'cash',
                'destination_account': 'bank',
                'amount': '25',
                'bank_charges': '0',
                'description': 'Daily banking',
                'reference': 'BANK-POPOVER-001',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(save_response.status_code, 200)
        self.assertEqual(
            save_response.json()['message'],
            'Bank deposit recorded.',
        )
        self.assertTrue(BranchAccountTransfer.objects.filter(
            branch=self.branch, reference='BANK-POPOVER-001',
            amount=Decimal('25'),
        ).exists())
        self.assertFalse(Expense.objects.exists())

    def test_bank_statement_and_cash_flow_show_both_sides_of_transfers(self):
        today = timezone.localdate()
        for source, destination, amount, reference in (
            ('cash', 'bank', '50', 'BANK-IN-001'),
            ('bank', 'cash', '20', 'BANK-OUT-001'),
        ):
            response = self.client.post(
                reverse('documents:branch_account_transfer'),
                {
                    'branch': self.branch.pk,
                    'transfer_date': today.isoformat(),
                    'source_account': source,
                    'destination_account': destination,
                    'amount': amount,
                    'description': 'Test account movement',
                    'reference': reference,
                },
            )
            self.assertEqual(response.status_code, 302)

        Payment.objects.create(
            amount=Decimal('30'), payment_date=today, method='bank_transfer',
            received_by=self.user, branch=self.branch,
        )
        Payment.objects.create(
            amount=Decimal('150'), payment_date=today, method='cash',
            received_by=self.user, branch=self.branch,
        )
        Expense.objects.create(
            expense_date=today,
            description='Bank-paid expense',
            amount=Decimal('10'),
            status='approved',
            payment_method='bank_transfer',
            paid_by=self.user,
            created_by=self.user,
            approved_by=self.user,
            branch=self.branch,
        )

        params = {
            'branch': self.branch.pk,
            'from': today.isoformat(),
            'to': today.isoformat(),
        }
        bank_statement = self.client.get(
            reverse('documents:branch_bank_statement'), params,
        )
        cash_flow = self.client.get(
            reverse('documents:financial_reports'),
            {**params, 'record_type': 'transfer'},
        )
        ledger = self.client.get(
            reverse('documents:branch_daily_ledger'),
            {'branch': self.branch.pk, 'date': today.isoformat()},
        )
        balance_sheet = self.client.get(
            reverse('documents:balance_sheet_report'), params,
        )

        self.assertEqual(bank_statement.status_code, 200)
        self.assertEqual(bank_statement.context['total_inflow'], Decimal('80'))
        self.assertEqual(bank_statement.context['total_outflow'], Decimal('30'))
        self.assertContains(bank_statement, 'Bank Statement')
        self.assertContains(bank_statement, 'Bank-paid expense')
        self.assertEqual(cash_flow.context['transactions'].paginator.count, 4)
        self.assertEqual(cash_flow.context['cash_inflow'], Decimal('180'))
        self.assertEqual(cash_flow.context['cash_outflow'], Decimal('10'))
        self.assertEqual(
            sum(row['inflow'] for row in cash_flow.context['transactions']),
            Decimal('70'),
        )
        ledger_transfers = [
            row for row in ledger.context['transactions']
            if row['type'] in (
                'Bank deposit transfer', 'Bank withdrawal transfer',
            )
        ]
        self.assertEqual(len(ledger_transfers), 4)
        self.assertEqual(
            sum(row['inflow'] for row in ledger_transfers),
            Decimal('70'),
        )
        self.assertEqual(
            sum(row['outflow'] for row in ledger_transfers),
            Decimal('70'),
        )
        self.assertEqual(
            sum(row['outflow'] for row in cash_flow.context['transactions']),
            Decimal('70'),
        )
        self.assertEqual(
            balance_sheet.context['cash_account_totals']['cash_on_hand'],
            Decimal('120'),
        )
        self.assertEqual(
            balance_sheet.context['cash_account_totals']['bank_deposit'],
            Decimal('50'),
        )

    def test_branch_navigation_shows_relevant_modules_for_each_workspace(self):
        self.user.branch = self.external_branch
        self.user.save(update_fields=['branch'])
        external_response = self.client.get(
            reverse('documents:branch_account_statement'),
        )

        self.assertEqual(external_response.status_code, 200)
        self.assertContains(external_response, 'Daily Summaries')
        self.assertContains(external_response, 'Engagements')
        self.assertContains(external_response, 'Compliance')
        self.assertNotContains(external_response, 'Monthly Report')
        self.assertNotContains(external_response, '>Expenses</span>')

        self.user.branch = self.branch
        self.user.save(update_fields=['branch'])
        internal_response = self.client.get(
            reverse('documents:branch_account_statement'),
        )
        self.assertContains(internal_response, 'Monthly Report')
        self.assertContains(internal_response, '>Expenses</span>')
        self.assertNotContains(internal_response, 'Daily Summaries')
