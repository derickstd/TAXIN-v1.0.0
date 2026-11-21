from django.db.models import Q
from django.utils.text import slugify

from .models import Branch


def ensure_business_branches(company):
    taxman = company.branches.filter(name__iexact='TAXMAN').first()
    main_branch = company.branches.filter(name__iexact='Main').first()
    if not taxman and main_branch:
        main_branch.name = 'TAXMAN'
        main_branch.slug = f'{company.slug}-taxman'
        main_branch.external_reporting = False
        main_branch.is_active = True
        main_branch.save(update_fields=[
            'name', 'slug', 'external_reporting', 'is_active',
        ])
        taxman = main_branch
    if not taxman:
        taxman = Branch.objects.create(
            company=company,
            name='TAXMAN',
            slug=f'{company.slug}-taxman',
            external_reporting=False,
        )
    elif taxman.external_reporting or not taxman.is_active:
        taxman.external_reporting = False
        taxman.is_active = True
        taxman.save(update_fields=['external_reporting', 'is_active'])

    branches = []
    for name in ('PRIME FOCUS', 'ABA UGANDA'):
        branch = company.branches.filter(name__iexact=name).first()
        if not branch:
            branch = Branch.objects.create(
                company=company,
                name=name,
                slug=f'{company.slug}-{slugify(name)}',
                external_reporting=True,
            )
        if not branch.external_reporting or not branch.is_active:
            branch.external_reporting = True
            branch.is_active = True
            branch.save(update_fields=['external_reporting', 'is_active'])
        branches.append(branch)

    prime_focus, aba_uganda = branches
    if (
        not company.default_branch_id
        or company.default_branch_id == getattr(main_branch, 'pk', None)
    ):
        company.default_branch = taxman
        company.save(update_fields=['default_branch'])

    from services.models import ServiceType

    services = ServiceType.objects.filter(
        Q(branches__company=company) | Q(branches__isnull=True),
    ).distinct()
    for service in services:
        service.branches.add(taxman, prime_focus, aba_uganda)

    return taxman, prime_focus, aba_uganda
