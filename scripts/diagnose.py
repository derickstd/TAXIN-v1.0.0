from core.models import Company, Tenant, AuditLog
print("=== Companies ===")
for c in Company.objects.all():
    print(f"  {c.slug}: {c.name} (owner={c.owner}, db_name={c.db_name})")
print("\n=== Tenants ===")
for t in Tenant.objects.all():
    print(f"  {t.company.slug}: status={t.status}, db_alias={t.db_alias}, last_error={t.last_error[:100] if t.last_error else 'None'}")
print("\n=== Recent Audit Logs ===")
for al in AuditLog.objects.order_by('-changed_at')[:10]:
    print(f"  {al.action} {al.model_name}#{al.object_id} by {al.changed_by}: {al.notes}")
