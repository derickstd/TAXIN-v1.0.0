"""Audit events for important business and authentication activity."""

from django.contrib.auth.signals import user_logged_in
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .models import AuditLog


AUDITED_MODELS = {
    'clients.Client': ('client', 'created_by'),
    'expenses.Expense': ('expense', 'created_by'),
    'billing.Payment': ('payment', 'received_by'),
    'billing.Invoice': ('invoice', 'created_by'),
    'billing.OtherIncome': ('other_income', 'recorded_by'),
    'services.JobCard': ('job_card', 'created_by'),
    'compliance.ComplianceDeadline': ('compliance_deadline', 'filed_by'),
}


def _model_key(instance):
    return f'{instance._meta.app_label}.{instance.__class__.__name__}'


def _actor(instance, user_field):
    return getattr(instance, user_field, None)


def _json_value(value):
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    if hasattr(value, 'pk'):
        return str(value.pk)
    return str(value)


def _audit(instance, action, *, user=None, notes=''):
    model_name, user_field = AUDITED_MODELS[_model_key(instance)]
    changed_by = user or _actor(instance, user_field)
    old_values = getattr(instance, '_audit_old_values', {})
    new_values = {}
    if action != 'DELETE':
        for field in instance._meta.concrete_fields:
            if field.name in ('id', 'created_at', 'updated_at'):
                continue
            new_values[field.name] = _json_value(getattr(instance, field.name, None))
    changed_fields = {
        field: {'from': old_values.get(field), 'to': new_values.get(field)}
        for field in set(old_values) | set(new_values)
        if old_values.get(field) != new_values.get(field)
    }
    AuditLog.objects.create(
        model_name=model_name,
        object_id=str(instance.pk),
        action=action,
        changed_fields=changed_fields,
        changed_by=changed_by,
        notes=notes or f'{model_name.replace("_", " ").title()} {action.lower()}',
    )


@receiver(post_save)
def audit_business_model_save(sender, instance, created, **kwargs):
    if _model_key(instance) not in AUDITED_MODELS:
        return
    action = 'CREATE' if created else 'UPDATE'
    _audit(instance, action)


@receiver(pre_save)
def capture_audit_changes(sender, instance, **kwargs):
    if _model_key(instance) not in AUDITED_MODELS or not instance.pk:
        return
    try:
        previous = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        return
    instance._audit_old_values = {}
    for field in instance._meta.concrete_fields:
        if field.name in ('id', 'created_at', 'updated_at'):
            continue
        instance._audit_old_values[field.name] = _json_value(getattr(previous, field.name, None))


@receiver(post_delete)
def audit_business_model_delete(sender, instance, **kwargs):
    if _model_key(instance) not in AUDITED_MODELS:
        return
    _audit(instance, 'DELETE')


@receiver(user_logged_in)
def audit_login(sender, request, user, **kwargs):
    AuditLog.objects.create(
        model_name='login',
        object_id=str(user.pk),
        action='CREATE',
        changed_fields={},
        changed_by=user,
        ip_address=request.META.get('REMOTE_ADDR') if request else None,
        notes=f'User {user.username} logged in',
    )