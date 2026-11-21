from decimal import Decimal
from io import StringIO

from django.core.management import call_command, CommandError
from django.test import TestCase

from billing.models import Invoice, Payment
from clients.models import Client
from core.models import Branch, Company, User
from core.reference_data import EXPENSE_CATEGORIES, SERVICE_TYPES
from expenses.models import ExpenseCategory
from services.models import ServiceType


class SeedReferenceDataCommandTests(TestCase):
    def test_command_seeds_only_reference_data_and_is_idempotent(self):
        company = Company.objects.create(name='TAXMAN', slug='taxman')
        main_branch = Branch.objects.create(
            company=company, name='Main', slug='taxman-main',
        )
        company.default_branch = main_branch
        company.save(update_fields=['default_branch'])
        ExpenseCategory.objects.create(name='office rent')
        vat_service = ServiceType.objects.create(
            name='VAT Return',
            category='ura_filing',
            default_price=Decimal('123456'),
        )
        existing_service = ServiceType.objects.create(
            name='Custom Service',
            category='miscellaneous',
        )
        existing_service.branches.add(main_branch)

        call_command(
            'seed_reference_data', company_slug=company.slug, stdout=StringIO(),
        )

        branches = {
            branch.name: branch
            for branch in company.branches.all()
        }
        self.assertEqual(set(branches), {'TAXMAN', 'PRIME FOCUS', 'ABA UGANDA'})
        self.assertEqual(branches['TAXMAN'].pk, main_branch.pk)
        self.assertFalse(branches['TAXMAN'].external_reporting)
        self.assertTrue(branches['PRIME FOCUS'].external_reporting)
        self.assertTrue(branches['ABA UGANDA'].external_reporting)
        self.assertEqual(company.default_branch_id, branches['TAXMAN'].pk)
        self.assertEqual(
            ExpenseCategory.objects.count(),
            len(EXPENSE_CATEGORIES) + 1,
        )
        self.assertEqual(ServiceType.objects.count(), len(SERVICE_TYPES) + 1)
        self.assertEqual(vat_service.default_price, Decimal('123456'))
        self.assertCountEqual(
            vat_service.branches.values_list('name', flat=True),
            ['TAXMAN', 'PRIME FOCUS', 'ABA UGANDA'],
        )
        self.assertCountEqual(
            existing_service.branches.values_list('name', flat=True),
            ['TAXMAN', 'PRIME FOCUS', 'ABA UGANDA'],
        )
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(Client.objects.count(), 0)
        self.assertEqual(Invoice.objects.count(), 0)
        self.assertEqual(Payment.objects.count(), 0)

        call_command(
            'seed_reference_data', company_slug=company.slug, stdout=StringIO(),
        )
        self.assertEqual(company.branches.count(), 3)
        self.assertEqual(
            ExpenseCategory.objects.count(),
            len(EXPENSE_CATEGORIES) + 1,
        )
        self.assertEqual(ServiceType.objects.count(), len(SERVICE_TYPES) + 1)

    def test_command_refuses_unexpected_branches_without_seeding(self):
        company = Company.objects.create(name='TAXMAN', slug='taxman')
        Branch.objects.create(
            company=company, name='Legacy North', slug='legacy-north',
        )
        category_count = ExpenseCategory.objects.count()
        service_count = ServiceType.objects.count()

        with self.assertRaises(CommandError):
            call_command(
                'seed_reference_data',
                company_slug=company.slug,
                stdout=StringIO(),
            )

        self.assertEqual(company.branches.count(), 1)
        self.assertEqual(ExpenseCategory.objects.count(), category_count)
        self.assertEqual(ServiceType.objects.count(), service_count)

    def test_command_can_assign_an_explicit_admin_to_the_seeded_company(self):
        company = Company.objects.create(name='TAXMAN', slug='taxman')
        admin = User.objects.create_user(
            username='taxman-admin',
            password='test-password',
            role='admin',
        )

        call_command(
            'seed_reference_data',
            company_slug=company.slug,
            assign_admin=admin.username,
            stdout=StringIO(),
        )

        admin.refresh_from_db()
        self.assertEqual(admin.company_id, company.pk)
        self.assertEqual(admin.branch.name, 'TAXMAN')
