from django.core.management.base import BaseCommand
from compliance.models import ComplianceDeadline
from django.utils import timezone

class Command(BaseCommand):
    help = 'Reset all compliance deadlines to pending (upcoming) on the first day of each month.'

    def handle(self, *args, **options):
        today = timezone.now().date()
        if today.day == 1:
            updated = ComplianceDeadline.objects.exclude(status='upcoming').update(status='upcoming')
            self.stdout.write(self.style.SUCCESS(f'Reset {updated} compliance deadlines to upcoming.'))
        else:
            self.stdout.write(self.style.WARNING('Today is not the first day of the month. No deadlines reset.'))
