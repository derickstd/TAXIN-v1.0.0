from django.core.management.base import BaseCommand
from core.models import Company, Branch

class Command(BaseCommand):
    help = 'Create a default "Main" branch for each existing Company if none exists'

    def handle(self, *args, **options):
        created = 0
        for company in Company.objects.all():
            if not company.branches.exists():
                Branch.objects.create(company=company, name='Main', slug=f'{company.slug}-main')
                created += 1
                self.stdout.write(self.style.SUCCESS(f'Created Main branch for {company.slug}'))
        if created == 0:
            self.stdout.write('No companies required branch creation.')
        else:
            self.stdout.write(self.style.SUCCESS(f'Created {created} branch(es).'))
