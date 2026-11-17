from core.models import Company, Branch, AuditLog

company = Company.objects.order_by('pk').first()
print("=== Company ===")
print(f"  {company.name} ({company.slug})" if company else "  Not configured")
print("\n=== Branches ===")
if company:
    for branch in company.branches.order_by('name'):
        print(f"  {branch.name}: {'active' if branch.is_active else 'inactive'}")
print("\n=== Recent Audit Logs ===")
for audit_log in AuditLog.objects.order_by('-changed_at')[:10]:
    print(
        f"  {audit_log.action} {audit_log.model_name}#{audit_log.object_id} "
        f"by {audit_log.changed_by}: {audit_log.notes}"
    )
