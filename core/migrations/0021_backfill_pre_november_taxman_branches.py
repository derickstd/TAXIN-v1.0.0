from datetime import date

from django.db import migrations


CUTOFF_DATE = date(2026, 11, 1)


def _user_company_id(user):
    if not user:
        return None
    return user.company_id or (
        user.branch.company_id if user.branch_id else None
    )


def _client_company_id(client):
    if not client:
        return None
    return (
        _user_company_id(client.created_by)
        or _user_company_id(client.assigned_officer)
        or (client.branch.company_id if client.branch_id else None)
    )


def _record_company_id(record, actor_fields=(), client=None):
    for field in actor_fields:
        company_id = _user_company_id(getattr(record, field, None))
        if company_id:
            return company_id
    return _client_company_id(client)


def _taxman_branch_id(Branch, company_id, branches_by_company):
    if not company_id:
        return None
    if company_id not in branches_by_company:
        branches_by_company[company_id] = (
            Branch.objects.filter(company_id=company_id, name__iexact='TAXMAN')
            .values_list('pk', flat=True)
            .first()
        )
    return branches_by_company[company_id]


def _assign_missing_branches(
    Branch, model, records, company_for_record, branches_by_company,
):
    for record in records.iterator():
        branch_id = _taxman_branch_id(
            Branch, company_for_record(record), branches_by_company,
        )
        if branch_id:
            model.objects.filter(pk=record.pk, branch__isnull=True).update(
                branch_id=branch_id,
            )


def assign_pre_cutoff_records(apps, schema_editor):
    Branch = apps.get_model('core', 'Branch')
    branches_by_company = {}

    Client = apps.get_model('clients', 'Client')
    _assign_missing_branches(
        Branch,
        Client,
        Client.objects.filter(
            branch__isnull=True, date_registered__lt=CUTOFF_DATE,
        ).select_related(
            'created_by__company', 'created_by__branch',
            'assigned_officer__company', 'assigned_officer__branch',
        ),
        lambda client: _client_company_id(client),
        branches_by_company,
    )

    Invoice = apps.get_model('billing', 'Invoice')
    _assign_missing_branches(
        Branch,
        Invoice,
        Invoice.objects.filter(
            branch__isnull=True, date_issued__lt=CUTOFF_DATE,
        ).select_related(
            'created_by__company', 'created_by__branch',
            'client__created_by__company', 'client__created_by__branch',
            'client__assigned_officer__company', 'client__assigned_officer__branch',
            'client__branch__company',
        ),
        lambda invoice: _record_company_id(
            invoice, ('created_by',), invoice.client,
        ),
        branches_by_company,
    )

    Payment = apps.get_model('billing', 'Payment')
    _assign_missing_branches(
        Branch,
        Payment,
        Payment.objects.filter(
            branch__isnull=True, payment_date__lt=CUTOFF_DATE,
        ).select_related(
            'received_by__company', 'received_by__branch',
            'client__created_by__company', 'client__created_by__branch',
            'client__assigned_officer__company', 'client__assigned_officer__branch',
            'client__branch__company',
            'invoice__client__created_by__company',
            'invoice__client__created_by__branch',
            'invoice__client__assigned_officer__company',
            'invoice__client__assigned_officer__branch',
            'invoice__client__branch__company',
        ),
        lambda payment: _record_company_id(
            payment,
            ('received_by',),
            payment.client or (payment.invoice.client if payment.invoice_id else None),
        ),
        branches_by_company,
    )

    OtherIncome = apps.get_model('billing', 'OtherIncome')
    _assign_missing_branches(
        Branch,
        OtherIncome,
        OtherIncome.objects.filter(
            branch__isnull=True, income_date__lt=CUTOFF_DATE,
        ).select_related('recorded_by__company', 'recorded_by__branch'),
        lambda income: _record_company_id(income, ('recorded_by',)),
        branches_by_company,
    )

    JobCard = apps.get_model('services', 'JobCard')
    _assign_missing_branches(
        Branch,
        JobCard,
        JobCard.objects.filter(
            branch__isnull=True, created_at__date__lt=CUTOFF_DATE,
        ).select_related(
            'created_by__company', 'created_by__branch',
            'assigned_to__company', 'assigned_to__branch',
            'client__created_by__company', 'client__created_by__branch',
            'client__assigned_officer__company', 'client__assigned_officer__branch',
            'client__branch__company',
        ),
        lambda job: _record_company_id(
            job, ('created_by', 'assigned_to'), job.client,
        ),
        branches_by_company,
    )

    Expense = apps.get_model('expenses', 'Expense')
    _assign_missing_branches(
        Branch,
        Expense,
        Expense.objects.filter(
            branch__isnull=True, expense_date__lt=CUTOFF_DATE,
        ).select_related(
            'created_by__company', 'created_by__branch',
            'paid_by__company', 'paid_by__branch',
            'client__created_by__company', 'client__created_by__branch',
            'client__assigned_officer__company', 'client__assigned_officer__branch',
            'client__branch__company',
            'job_card__client__created_by__company',
            'job_card__client__created_by__branch',
            'job_card__client__assigned_officer__company',
            'job_card__client__assigned_officer__branch',
            'job_card__client__branch__company',
        ),
        lambda expense: _record_company_id(
            expense,
            ('created_by', 'paid_by'),
            expense.client or (
                expense.job_card.client if expense.job_card_id else None
            ),
        ),
        branches_by_company,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0013_branchdailytransaction_expense_category'),
        ('clients', '0006_backfill_client_branches'),
        ('core', '0020_branch_logo'),
        ('expenses', '0004_seed_drawing_expense_category'),
        ('services', '0008_alter_servicetype_category'),
    ]

    operations = [
        migrations.RunPython(assign_pre_cutoff_records, migrations.RunPython.noop),
    ]
