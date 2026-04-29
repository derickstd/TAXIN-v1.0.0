from django.core.management.base import BaseCommand
from core.automation import auto_generate_missing_invoices


class Command(BaseCommand):
    help = 'Generate invoices for job cards that are missing them'

    def handle(self, *args, **options):
        self.stdout.write('Checking for job cards without invoices...')
        created = auto_generate_missing_invoices()
        self.stdout.write(self.style.SUCCESS(f'✓ Generated {created} missing invoices'))
