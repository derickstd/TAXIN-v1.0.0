from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from functools import wraps
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from .models import ModelVisibility, UserModelPermission, SystemModuleVisibility

SYSTEM_MODULE_DEFINITIONS = (
    ('dashboard', 'Dashboard', 'Show the main dashboard area in the navigation.'),
    ('clients', 'Clients', 'Display client management in the sidebar.'),
    ('engagements', 'Engagements', 'Display engagements and job cards in the sidebar.'),
    ('compliance', 'Compliance', 'Display compliance and tax calendar modules.'),
    ('finance', 'Finance', 'Display invoices, payments, and expense screens.'),
    ('insights', 'Insights', 'Display reports, documents, and notifications.'),
    ('account', 'Account', 'Display the account section and personal settings.'),
)


def ensure_module_visibility_defaults(company=None):
    """Create any missing module visibility entries with safe defaults for a tenant/company."""
    for key, label, description in SYSTEM_MODULE_DEFINITIONS:
        lookup = {'key': key}
        if company is None:
            lookup['company__isnull'] = True
        else:
            lookup['company'] = company
        SystemModuleVisibility.objects.get_or_create(
            **lookup,
            defaults={'label': label, 'description': description, 'enabled': True},
        )


def get_module_visibility_map(company=None):
    """Return a dictionary of module visibility entries keyed by module name for a tenant/company."""
    ensure_module_visibility_defaults(company=company)
    if company is None:
        modules = list(SystemModuleVisibility.objects.filter(company__isnull=True, key__in=[k for k, _, _ in SYSTEM_MODULE_DEFINITIONS]).order_by('order', 'label'))
    else:
        modules = list(SystemModuleVisibility.objects.filter(company=company, key__in=[k for k, _, _ in SYSTEM_MODULE_DEFINITIONS]).order_by('order', 'label'))
    module_map = {module.key: module for module in modules}
    if company is not None:
        fallback_modules = list(SystemModuleVisibility.objects.filter(company__isnull=True, key__in=[k for k, _, _ in SYSTEM_MODULE_DEFINITIONS]).order_by('order', 'label'))
        for module in fallback_modules:
            module_map.setdefault(module.key, module)
    for key, label, description in SYSTEM_MODULE_DEFINITIONS:
        if key not in module_map:
            module = SystemModuleVisibility.objects.create(key=key, company=company, label=label, description=description, enabled=True)
            module_map[key] = module
    return module_map


def is_module_enabled(key, company=None):
    """Return True if the given system module is enabled for a tenant/company."""
    module = get_module_visibility_map(company=company).get(key)
    return True if module is None else bool(module.enabled)


def paginate_queryset(request, queryset, per_page=25, page_param='page'):
    """Return a Django Paginator page object for the given request and queryset.

    Usage:
        page_obj = paginate_queryset(request, qs, per_page=25)
        return render(..., {'objects': page_obj})

    The returned page object is iterable (it yields page items) and also
    exposes `.has_next`, `.has_previous`, `.number`, `.paginator.num_pages`, etc.
    """
    page = request.GET.get(page_param, 1)
    paginator = Paginator(queryset, per_page)
    try:
        page_obj = paginator.page(page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)
    return page_obj


def is_model_visible(model_or_instance):
    """Return True if the given model class or instance is enabled per admin toggles.

    If no ModelVisibility row exists for the model, visibility defaults to True.
    """
    if not model_or_instance:
        return True
    model_cls = model_or_instance if isinstance(model_or_instance, type) else type(model_or_instance)
    ct = ContentType.objects.get_for_model(model_cls)
    try:
        return ct.visibility.enabled
    except ModelVisibility.DoesNotExist:
        return True


def require_model_visible(model_or_instance):
    """Decorator for views that should only be accessible when a model is enabled.

    Usage:
        @require_model_visible(MyModel)
        def my_view(request):
            ...
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not is_model_visible(model_or_instance):
                from django.http import Http404
                raise Http404()
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator


def user_can_view_model(user, model_or_instance):
    """Return True if the given user is allowed to view the model/instances.

    Priority:
    - Superusers: always True
    - UserModelPermission entry for (user, model): use its `can_view`
    - Global ModelVisibility: must be enabled
    - Default: True
    """
    if user is None:
        return False
    if getattr(user, 'is_superuser', False):
        return True
    model_cls = model_or_instance if isinstance(model_or_instance, type) else type(model_or_instance)
    ct = ContentType.objects.get_for_model(model_cls)
    try:
        ump = UserModelPermission.objects.get(user=user, content_type=ct)
        return bool(ump.can_view)
    except UserModelPermission.DoesNotExist:
        try:
            return ct.visibility.enabled
        except ModelVisibility.DoesNotExist:
            return True


def user_can_edit_model(user, model_or_instance):
    """Return True if the given user is allowed to edit the model/instances.

    Priority similar to `user_can_view_model`, but falls back to `user.is_staff`.
    """
    if user is None:
        return False
    if getattr(user, 'is_superuser', False):
        return True
    model_cls = model_or_instance if isinstance(model_or_instance, type) else type(model_or_instance)
    ct = ContentType.objects.get_for_model(model_cls)
    try:
        ump = UserModelPermission.objects.get(user=user, content_type=ct)
        return bool(ump.can_edit)
    except UserModelPermission.DoesNotExist:
        # Default to staff users being allowed to edit when no explicit entry exists
        return bool(getattr(user, 'is_staff', False))


def require_user_model_permission(model_or_instance, perm='view'):
    """Decorator to require a per-user model permission.

    `perm` may be 'view' or 'edit'. Raises PermissionDenied on failure.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            user = getattr(request, 'user', None)
            allowed = user_can_view_model(user, model_or_instance) if perm == 'view' else user_can_edit_model(user, model_or_instance)
            if not allowed:
                raise PermissionDenied()
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator
