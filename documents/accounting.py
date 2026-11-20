from decimal import Decimal

from billing.models import (
    BranchDailySummary, BranchDailyTransaction, OtherIncome, Payment,
)
from expenses.models import Expense
from .models import BranchAccountTransfer, BranchBalanceSheetEntry


ZERO = Decimal('0')

_METHOD_ACCOUNTS = {
    'cash': 'cash_on_hand',
    'petty_cash': 'cash_on_hand',
    'mobile_money': 'mobile_money',
    'bank_transfer': 'bank_deposit',
    'bank': 'bank_deposit',
    'other': 'cash_on_hand',
}

_LEDGER_ACCOUNTS = {
    'cash': 'cash_on_hand',
    'petty_cash': 'cash_on_hand',
    'mobile_money': 'mobile_money',
    'bank_transfer': 'bank_deposit',
    'other': 'cash_on_hand',
}


def _record_movement(balances, account, direction, amount):
    account = _METHOD_ACCOUNTS.get(account, account)
    if account not in balances:
        return
    balances[account] += amount if direction == 'inflow' else -amount


def branch_cash_account_movements(branch, date_to, *, after_date=None):
    """Return recorded cash-equivalent movements by account for one branch."""
    balances = {
        'cash_on_hand': ZERO,
        'bank_deposit': ZERO,
        'mobile_money': ZERO,
    }
    summaries = list(BranchDailySummary.objects.filter(
        branch=branch, business_date__lte=date_to,
    ))
    summary_dates = {summary.business_date for summary in summaries}

    if branch.external_reporting:
        ledger_entries = list(BranchDailyTransaction.objects.filter(
            branch=branch, business_date__lte=date_to,
            **({f'business_date__gt': after_date} if after_date else {}),
        ))
        ledger_dates = set()
        for entry in ledger_entries:
            ledger_dates.add(entry.business_date)
            account = _LEDGER_ACCOUNTS.get(entry.account, 'cash_on_hand')
            _record_movement(
                balances, account, entry.direction, entry.amount,
            )
        for summary in summaries:
            if summary.business_date in ledger_dates:
                continue
            if after_date and summary.business_date <= after_date:
                continue
            balances['cash_on_hand'] += summary.cash_inflow - summary.cash_outflow
    else:
        for summary in summaries:
            if after_date and summary.business_date <= after_date:
                continue
            balances['cash_on_hand'] += summary.cash_inflow - summary.cash_outflow

        payments = Payment.objects.filter(
            branch=branch, payment_date__lte=date_to,
        ).exclude(payment_date__in=summary_dates)
        if after_date:
            payments = payments.filter(payment_date__gt=after_date)
        for payment in payments:
            _record_movement(
                balances, payment.method, 'inflow', payment.amount,
            )

        incomes = OtherIncome.objects.filter(
            branch=branch, income_date__lte=date_to,
        ).exclude(income_date__in=summary_dates)
        if after_date:
            incomes = incomes.filter(income_date__gt=after_date)
        for income in incomes:
            _record_movement(
                balances, income.collection_method, 'inflow', income.amount,
            )

        expenses = Expense.objects.filter(
            branch=branch, status='approved', expense_date__lte=date_to,
        ).exclude(expense_date__in=summary_dates)
        if after_date:
            expenses = expenses.filter(expense_date__gt=after_date)
        for expense in expenses:
            _record_movement(
                balances, expense.payment_method, 'outflow', expense.amount,
            )

    transfers = BranchAccountTransfer.objects.filter(
        branch=branch, transfer_date__lte=date_to,
    )
    if after_date:
        transfers = transfers.filter(transfer_date__gt=after_date)
    for transfer in transfers:
        source_account = _METHOD_ACCOUNTS.get(
            transfer.source_account, 'cash_on_hand',
        )
        destination_account = _METHOD_ACCOUNTS.get(
            transfer.destination_account, 'bank_deposit',
        )
        balances[source_account] -= transfer.amount
        balances[destination_account] += transfer.amount

    return balances


def branch_cash_account_balances(branch, date_to):
    """Calculate account balances, rolling forward the latest manual snapshots."""
    balances = branch_cash_account_movements(branch, date_to)
    snapshots = {}
    entries = BranchBalanceSheetEntry.objects.filter(
        branch=branch,
        category__in=('cash_on_hand', 'bank_deposit', 'mobile_money'),
        as_of_date__lte=date_to,
    ).order_by('-as_of_date', '-pk')
    for entry in entries:
        snapshots.setdefault(entry.category, entry)

    for account, snapshot in snapshots.items():
        movements = branch_cash_account_movements(
            branch, date_to, after_date=snapshot.as_of_date,
        )
        balances[account] = snapshot.amount + movements[account]
    return balances


def latest_balance_sheet_entries(branches, date_to):
    """Return the latest dated entry for each account across the given branches."""
    entries = BranchBalanceSheetEntry.objects.filter(
        branch__in=branches, as_of_date__lte=date_to,
    ).select_related('branch').order_by(
        'branch_id', 'category', 'account_name', '-as_of_date', '-pk',
    )
    latest = {}
    for entry in entries:
        latest.setdefault(
            (entry.branch_id, entry.category, entry.account_name), entry,
        )
    return list(latest.values())
