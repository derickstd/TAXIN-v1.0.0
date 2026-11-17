from decimal import Decimal

from django.db.models import Count, Sum

from billing.models import (
    BranchDailySummary, BranchDailyTransaction, OtherIncome, Payment,
)
from expenses.models import Expense
from .branch_access import accessible_branches


ZERO = Decimal('0')


def _sum(queryset, field):
    return queryset.aggregate(total=Sum(field))['total'] or ZERO


def branch_cash_summary(branch, date_from, date_to):
    if branch.external_reporting:
        summaries = list(BranchDailySummary.objects.filter(
            branch=branch, business_date__lte=date_to,
        ).order_by('business_date'))
        summaries_by_date = {summary.business_date: summary for summary in summaries}
        ledger_by_date = {}
        for item in BranchDailyTransaction.objects.filter(
            branch=branch, business_date__lte=date_to,
        ).values('business_date', 'direction', 'category').annotate(
            total=Sum('amount'), count=Count('pk'),
        ):
            day = ledger_by_date.setdefault(
                item['business_date'], {
                    'inflow': ZERO, 'outflow': ZERO,
                    'capital_injections': ZERO, 'drawings': ZERO, 'count': 0,
                },
            )
            key = 'inflow' if item['direction'] == 'inflow' else 'outflow'
            day[key] = item['total'] or ZERO
            if item['category'] == 'capital_injection':
                day['capital_injections'] += item['total'] or ZERO
            elif item['category'] == 'drawing':
                day['drawings'] += item['total'] or ZERO
            day['count'] += item['count']

        period_dates = set(summaries_by_date).union(ledger_by_date)
        period_dates = {
            day for day in period_dates if date_from <= day <= date_to
        }
        inflow = ZERO
        outflow = ZERO
        capital_injections = ZERO
        drawings = ZERO
        entry_count = 0
        for day in period_dates:
            if day in ledger_by_date:
                inflow += ledger_by_date[day]['inflow']
                outflow += ledger_by_date[day]['outflow']
                capital_injections += ledger_by_date[day]['capital_injections']
                drawings += ledger_by_date[day]['drawings']
                entry_count += ledger_by_date[day]['count']
            elif day in summaries_by_date:
                inflow += summaries_by_date[day].cash_inflow
                outflow += summaries_by_date[day].cash_outflow
                entry_count += 1

        earlier = BranchDailySummary.objects.filter(
            branch=branch, business_date__lt=date_from,
        ).order_by('-business_date').first()
        first_in_period = next(
            (
                summary for summary in summaries
                if date_from <= summary.business_date <= date_to
            ),
            None,
        )
        latest = BranchDailySummary.objects.filter(
            branch=branch, business_date__lte=date_to,
        ).order_by('-business_date').first()
        opening = (
            earlier.closing_balance + _sum(
                BranchDailyTransaction.objects.filter(
                    branch=branch,
                    business_date__gt=earlier.business_date,
                    business_date__lt=date_from,
                    direction='inflow',
                ),
                'amount',
            ) - _sum(
                BranchDailyTransaction.objects.filter(
                    branch=branch,
                    business_date__gt=earlier.business_date,
                    business_date__lt=date_from,
                    direction='outflow',
                ),
                'amount',
            ) if earlier
            else first_in_period.opening_balance
            if first_in_period and first_in_period.business_date == date_from
            else _sum(
                BranchDailyTransaction.objects.filter(
                    branch=branch, business_date__lt=date_from,
                    direction='inflow',
                ),
                'amount',
            ) - _sum(
                BranchDailyTransaction.objects.filter(
                    branch=branch, business_date__lt=date_from,
                    direction='outflow',
                ),
                'amount',
            )
        )
        later_ledger = (
            BranchDailyTransaction.objects.filter(
                branch=branch,
                business_date__gt=latest.business_date,
                business_date__lte=date_to,
            ) if latest else BranchDailyTransaction.objects.filter(
                branch=branch, business_date__lte=date_to,
            )
        )
        later_inflow = _sum(later_ledger.filter(direction='inflow'), 'amount')
        later_outflow = _sum(later_ledger.filter(direction='outflow'), 'amount')
        result = {
            'branch': branch,
            'name': branch.name,
            'external_reporting': True,
            'customer_receipts': inflow - capital_injections,
            'other_receipts': ZERO,
            'capital_injections': capital_injections,
            'drawings': drawings,
            'operating_inflow': inflow - capital_injections,
            'operating_outflow': outflow - drawings,
            'operating_profit': inflow - capital_injections - outflow + drawings,
            'inflow': inflow,
            'outflow': outflow,
            'net_cash_flow': inflow - outflow,
            'opening_cash': opening,
            'closing_cash': (
                (latest.closing_balance if latest else opening)
                + later_inflow - later_outflow
            ),
            'entry_count': entry_count,
            'reconciliation_difference': sum(
                (
                    summary.closing_balance - (
                        summary.opening_balance
                        + ledger_by_date[summary.business_date]['inflow']
                        - ledger_by_date[summary.business_date]['outflow']
                    ) if summary.business_date in ledger_by_date
                    else summary.reconciliation_difference
                    for summary in summaries
                    if date_from <= summary.business_date <= date_to
                ),
                ZERO,
            ),
        }
        return result

    summaries = BranchDailySummary.objects.filter(branch=branch)
    summary_dates = summaries.values_list('business_date', flat=True)
    payments = Payment.objects.filter(branch=branch)
    other_income = OtherIncome.objects.filter(branch=branch)
    expenses = Expense.objects.filter(branch=branch, status='approved')
    period_payments = payments.filter(
        payment_date__range=(date_from, date_to),
    ).exclude(payment_date__in=summary_dates)
    period_income = other_income.filter(
        income_date__range=(date_from, date_to),
    ).exclude(income_date__in=summary_dates)
    period_expenses = expenses.filter(
        expense_date__range=(date_from, date_to),
    ).exclude(expense_date__in=summary_dates)
    period_summaries = summaries.filter(business_date__range=(date_from, date_to))
    customer_receipts = _sum(period_payments, 'amount')
    period_capital_injections = _sum(
        period_income.filter(category='capital_injection'), 'amount',
    )
    other_receipts = _sum(
        period_income.exclude(category='capital_injection'), 'amount',
    )
    outflow = _sum(period_expenses, 'amount')
    period_drawings = _sum(
        period_expenses.filter(category__name__iexact='Drawing'), 'amount',
    )
    previous_summary = summaries.filter(
        business_date__lt=date_from,
    ).order_by('-business_date').first()
    historical_payments = payments.filter(payment_date__lt=date_from)
    historical_income = other_income.filter(income_date__lt=date_from)
    historical_expenses = expenses.filter(expense_date__lt=date_from)
    if previous_summary:
        historical_payments = historical_payments.filter(
            payment_date__gt=previous_summary.business_date,
        )
        historical_income = historical_income.filter(
            income_date__gt=previous_summary.business_date,
        )
        historical_expenses = historical_expenses.filter(
            expense_date__gt=previous_summary.business_date,
        )
    opening = (
        (previous_summary.closing_balance if previous_summary else ZERO)
        + _sum(historical_payments.exclude(payment_date__in=summary_dates), 'amount')
        + _sum(historical_income.exclude(income_date__in=summary_dates), 'amount')
        - _sum(historical_expenses.exclude(expense_date__in=summary_dates), 'amount')
    )
    first_summary = period_summaries.order_by('business_date').first()
    if not previous_summary and first_summary and first_summary.business_date == date_from:
        opening = first_summary.opening_balance
    summarized_inflow = _sum(period_summaries, 'cash_inflow')
    summarized_outflow = _sum(period_summaries, 'cash_outflow')
    summarized_drawings = _sum(
        expenses.filter(
            category__name__iexact='Drawing',
            expense_date__in=period_summaries.values('business_date'),
        ),
        'amount',
    )
    summarized_capital_injections = _sum(
        other_income.filter(
            category='capital_injection',
            income_date__in=period_summaries.values('business_date'),
        ),
        'amount',
    )
    customer_receipts += summarized_inflow - summarized_capital_injections
    capital_injections = period_capital_injections + summarized_capital_injections
    drawings = period_drawings + summarized_drawings
    inflow = customer_receipts + other_receipts + capital_injections
    outflow += summarized_outflow
    latest_summary = summaries.filter(
        business_date__lte=date_to,
    ).order_by('-business_date').first()
    if latest_summary:
        later_payments = payments.filter(
            payment_date__gt=latest_summary.business_date,
            payment_date__lte=date_to,
        ).exclude(payment_date__in=summary_dates)
        later_income = other_income.filter(
            income_date__gt=latest_summary.business_date,
            income_date__lte=date_to,
        ).exclude(income_date__in=summary_dates)
        later_expenses = expenses.filter(
            expense_date__gt=latest_summary.business_date,
            expense_date__lte=date_to,
        ).exclude(expense_date__in=summary_dates)
        closing = (
            latest_summary.closing_balance
            + _sum(later_payments, 'amount')
            + _sum(later_income, 'amount')
            - _sum(later_expenses, 'amount')
        )
    else:
        closing = opening + inflow - outflow
    return {
        'branch': branch,
        'name': branch.name,
        'external_reporting': False,
        'customer_receipts': customer_receipts,
        'other_receipts': other_receipts,
        'capital_injections': capital_injections,
        'drawings': drawings,
        'operating_inflow': customer_receipts + other_receipts,
        'operating_outflow': outflow - drawings,
        'operating_profit': customer_receipts + other_receipts - outflow + drawings,
        'inflow': inflow,
        'outflow': outflow,
        'net_cash_flow': inflow - outflow,
        'opening_cash': opening,
        'closing_cash': closing,
        'entry_count': (
            period_payments.count() + period_income.count()
            + period_expenses.count() + period_summaries.count()
        ),
        'reconciliation_difference': sum(
            (summary.reconciliation_difference for summary in period_summaries), ZERO,
        ),
    }


def branch_comparison_for_user(user, date_from, date_to):
    branches = accessible_branches(user).order_by('name')
    return [branch_cash_summary(branch, date_from, date_to) for branch in branches]


def company_branches_for_user(user):
    return accessible_branches(user)
