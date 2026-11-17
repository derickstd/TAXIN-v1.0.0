from .models import Branch


class BranchWorkspaceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.active_branch = None
        request.workspace_branches = Branch.objects.none()
        request.can_switch_branch = False

        user = request.user
        if user.is_authenticated:
            can_switch = user.is_superuser or (
                user.role in ('admin', 'ceo') and user.company_id
            )
            if can_switch:
                branches = Branch.objects.filter(is_active=True)
                if not user.is_superuser:
                    branches = branches.filter(company_id=user.company_id)
                request.workspace_branches = branches
                request.can_switch_branch = branches.exists()
                active_id = request.session.get('active_branch_id')
                if active_id:
                    request.active_branch = branches.filter(pk=active_id).first()
                    if request.active_branch is None:
                        request.session.pop('active_branch_id', None)
            else:
                request.session.pop('active_branch_id', None)
                if user.branch_id:
                    branch = Branch.objects.filter(
                        pk=user.branch_id, is_active=True,
                    )
                    if user.company_id:
                        branch = branch.filter(company_id=user.company_id)
                    request.active_branch = branch.first()
                if request.active_branch:
                    request.workspace_branches = Branch.objects.filter(
                        pk=request.active_branch.pk,
                    )

            user.active_branch_id = (
                request.active_branch.pk if request.active_branch else None
            )

        return self.get_response(request)
