from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from functools import wraps
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from .models import ModelVisibility, UserModelPermission


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
