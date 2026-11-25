from django.db.models import QuerySet

from .models import Branch


def has_company_wide_branch_access(user):
    return user.is_superuser or user.role in ('admin', 'ceo')


def accessible_branches(user):
    active_branch_id = getattr(user, 'active_branch_id', None)
    if active_branch_id:
        branches = Branch.objects.filter(pk=active_branch_id, is_active=True)
        if user.company_id:
            branches = branches.filter(company_id=user.company_id)
        return branches
    if user.is_superuser:
        return Branch.objects.filter(is_active=True)
    if user.branch_id:
        branches = Branch.objects.filter(pk=user.branch_id, is_active=True)
        if user.company_id:
            branches = branches.filter(company_id=user.company_id)
        if has_company_wide_branch_access(user) and user.company_id:
            return Branch.objects.filter(company_id=user.company_id, is_active=True)
        return branches
    if not user.company_id:
        return Branch.objects.none()
    branches = Branch.objects.filter(company_id=user.company_id, is_active=True)
    if has_company_wide_branch_access(user):
        return branches
    return Branch.objects.none()


def scope_queryset(user, queryset: QuerySet, branch_path='branch'):
    active_branch_id = getattr(user, 'active_branch_id', None)
    if active_branch_id:
        return queryset.filter(**{f'{branch_path}__pk': active_branch_id})
    if user.is_superuser:
        return queryset
    if not user.company_id and not user.branch_id:
        return queryset if has_company_wide_branch_access(user) else queryset.none()
    if user.company_id and has_company_wide_branch_access(user):
        return queryset.filter(**{f'{branch_path}__company_id': user.company_id})
    branches = accessible_branches(user)
    return queryset.filter(**{f'{branch_path}__in': branches})


def get_entry_branch(user):
    active_branch_id = getattr(user, 'active_branch_id', None)
    if active_branch_id:
        active_branch = Branch.objects.filter(
            pk=active_branch_id, is_active=True,
        ).first()
        if active_branch and (
            user.is_superuser
            or not user.company_id
            or active_branch.company_id == user.company_id
        ):
            return active_branch
    if (
        user.branch_id and user.branch.is_active
        and (not user.company_id or user.branch.company_id == user.company_id)
    ):
        return user.branch
    if user.company_id and has_company_wide_branch_access(user):
        default_branch = user.company.default_branch
        if default_branch and default_branch.is_active:
            return default_branch
    return None
