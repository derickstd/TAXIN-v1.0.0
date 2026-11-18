from collections import Counter

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.branch_setup import ensure_business_branches
from core.models import Company
from core.reference_data import EXPENSE_CATEGORIES, SERVICE_TYPES
from expenses.models import ExpenseCategory
from services.models import ServiceType


class Command(BaseCommand):
    help = (
        'Safely create the standard expense categories, services, and '
        'TAXMAN branches without demo users or transactions.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--company-slug',
            help='Company slug to seed; required when the database has multiple companies.',
        )
        parser.add_argument(
            '--assign-admin',
            help='Optionally assign an existing admin, CEO, or superuser to the company and TAXMAN branch.',
        )

    def handle(self, *args, **options):
        company = self._get_company(options['company_slug'])
        self._validate_existing_branches(company)
        admin_user = self._get_admin_user(options['assign_admin'], company)

        with transaction.atomic():
            taxman, prime_focus, aba_uganda = ensure_business_branches(company)
            categories_created = self._seed_expense_categories()
            services_created = self._seed_services(taxman, prime_focus)
            if admin_user:
                admin_user.company = company
                if not admin_user.branch_id:
                    admin_user.branch = taxman
                admin_user.save(update_fields=['company', 'branch'])

        self.stdout.write(self.style.SUCCESS(
            f'Seeded reference data for {company.name}: '
            f'{categories_created} expense categories added, '
            f'{services_created} services added, and branches TAXMAN, '
            'PRIME FOCUS, and ABA UGANDA are ready.'
        ))

    def _get_company(self, company_slug):
        if company_slug:
            try:
                return Company.objects.get(slug=company_slug)
            except Company.DoesNotExist as exc:
                raise CommandError(
                    f'No company found with slug {company_slug!r}.',
                ) from exc

        companies = list(Company.objects.order_by('pk')[:2])
        if len(companies) == 1:
            return companies[0]
        if not companies:
            raise CommandError(
                'No company exists yet. Create the company before seeding.',
            )
        raise CommandError(
            'Multiple companies exist; specify the target with --company-slug.',
        )

    def _validate_existing_branches(self, company):
        names = [
            name.casefold()
            for name in company.branches.values_list('name', flat=True)
        ]
        allowed = {'taxman', 'prime focus', 'aba uganda'}
        if 'taxman' not in names:
            allowed.add('main')
        unexpected = sorted(set(names) - allowed)
        duplicates = sorted(
            name for name, count in Counter(names).items()
            if count > 1
        )
        if unexpected or duplicates:
            details = []
            if unexpected:
                details.append('unexpected branches: ' + ', '.join(unexpected))
            if duplicates:
                details.append('duplicate branch names: ' + ', '.join(duplicates))
            raise CommandError(
                f'No data was seeded for {company.name}; '
                + '; '.join(details)
                + '. Review existing branches first.',
            )

    def _get_admin_user(self, username, company):
        if not username:
            return None

        User = get_user_model()
        try:
            user = User.objects.select_related('branch').get(username=username)
        except User.DoesNotExist as exc:
            raise CommandError(
                f'No user found with username {username!r}.',
            ) from exc

        if not (user.is_superuser or user.role in ('admin', 'ceo')):
            raise CommandError(
                f'User {username!r} is not a company admin, CEO, or superuser.',
            )
        if user.company_id and user.company_id != company.pk:
            raise CommandError(
                f'User {username!r} already belongs to another company.',
            )
        if user.branch_id and user.branch.company_id != company.pk:
            raise CommandError(
                f'User {username!r} is assigned to a branch in another company.',
            )
        return user

    def _seed_expense_categories(self):
        names = [*EXPENSE_CATEGORIES, 'Drawing']
        created = 0
        for name in names:
            if ExpenseCategory.objects.filter(name__iexact=name).exists():
                continue
            description = (
                'Owner withdrawals and drawings' if name == 'Drawing' else ''
            )
            ExpenseCategory.objects.create(name=name, description=description)
            created += 1
        return created

    def _seed_services(self, taxman, prime_focus):
        created = 0
        for defaults in SERVICE_TYPES:
            matches = list(
                ServiceType.objects.filter(
                    name__iexact=defaults['name'],
                ).order_by('pk')[:2]
            )
            if len(matches) > 1:
                raise CommandError(
                    f"Duplicate service names found for {defaults['name']!r}; "
                    'no duplicate service was created.',
                )
            if matches:
                service = matches[0]
            else:
                service = ServiceType.objects.create(**defaults)
                created += 1
            service.branches.add(taxman, prime_focus)
        return created
