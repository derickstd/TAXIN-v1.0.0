from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

from services.models import JobCard


class Command(BaseCommand):
    help = (
        'Find duplicate monthly jobs by client, period, and deadline rule. '
        'Use --apply to cancel safe unbilled duplicates.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Cancel duplicate jobs that have no invoice or payment.',
        )

    def handle(self, *args, **options):
        groups = defaultdict(list)
        jobs = JobCard.objects.filter(
            period_month__isnull=False,
            period_year__isnull=False,
        ).prefetch_related('line_items__service_type').select_related('invoice')

        for job in jobs:
            rules = {
                item.service_type.deadline_type
                for item in job.line_items.all()
                if item.service_type and item.service_type.deadline_type != 'none'
            }
            for rule in rules:
                groups[(job.client_id, job.period_year, job.period_month, rule)].append(job)

        duplicate_groups = [group for group in groups.values() if len({job.pk for job in group}) > 1]
        cancelled = 0
        skipped = 0

        for group in duplicate_groups:
            unique_jobs = {job.pk: job for job in group}.values()
            ordered = sorted(
                unique_jobs,
                key=lambda job: (
                    not bool(getattr(job, 'invoice', None) and job.invoice.payments.exists()),
                    job.status != 'completed',
                    not bool(getattr(job, 'invoice', None)),
                    not job.is_periodic,
                    job.created_at,
                    job.pk,
                ),
            )
            keeper = ordered[0]
            duplicates = ordered[1:]
            label = f'{keeper.client_id} / {keeper.period_month:02d}-{keeper.period_year}'
            self.stdout.write(
                f'{label} / {self._rule_for_group(keeper, group)}: '
                f'keep {keeper.job_number}, duplicates {", ".join(job.job_number for job in duplicates)}'
            )

            if not options['apply']:
                continue

            for duplicate in duplicates:
                has_invoice = hasattr(duplicate, 'invoice')
                has_payments = has_invoice and duplicate.invoice.payments.exists()
                if has_invoice or has_payments or duplicate.status == 'completed':
                    skipped += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f'  SKIP {duplicate.job_number}: linked invoice/payment or completed work'
                        )
                    )
                    continue
                with transaction.atomic():
                    JobCard.objects.filter(pk=duplicate.pk).update(status='cancelled')
                cancelled += 1

        if not duplicate_groups:
            self.stdout.write(self.style.SUCCESS('No duplicate monthly jobs found.'))
        elif options['apply']:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Consolidation complete: {cancelled} unbilled duplicates cancelled; '
                    f'{skipped} financially linked/completed duplicates require review.'
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f'Dry run only: {len(duplicate_groups)} duplicate groups found. '
                    'Re-run with --apply to cancel safe unbilled duplicates.'
                )
            )

    @staticmethod
    def _rule_for_group(job, group):
        rules = {
            item.service_type.deadline_type
            for item in job.line_items.all()
            if item.service_type and item.service_type.deadline_type != 'none'
        }
        return ','.join(sorted(rules)) or 'none'
