from django.core.management.base import BaseCommand
from django.utils import timezone
from core.reporting import calculate_monthly_trends
from core.models import Company

class Command(BaseCommand):
    help = 'Calculate and cache monthly trend data for all companies (previous month)'

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, help='Year for trends (defaults to previous month)')
        parser.add_argument('--month', type=int, help='Month (1-12) for trends (defaults to previous month)')

    def handle(self, *args, **options):
        today = timezone.now().date()
        if options.get('year') and options.get('month'):
            year = options['year']
            month = options['month']
        else:
            # default to previous month
            if today.month == 1:
                month = 12
                year = today.year - 1
            else:
                month = today.month - 1
                year = today.year

        self.stdout.write(f'Calculating monthly trends for {year}-{month:02d}...')
        companies = Company.objects.all()
        count = 0
        for c in companies:
            calculate_monthly_trends(c, year, month)
            count += 1
        self.stdout.write(self.style.SUCCESS(f'Calculated trends for {count} companies.'))
