from django.db import migrations


def assign_clients_to_branches(apps, schema_editor):
    Client = apps.get_model('clients', 'Client')
    for client in Client.objects.filter(branch__isnull=True).select_related(
        'created_by__branch', 'created_by__company__default_branch',
    ).iterator():
        creator = client.created_by
        branch_id = None
        if creator:
            branch_id = creator.branch_id
            if not branch_id and creator.company_id:
                branch_id = creator.company.default_branch_id
        if branch_id:
            Client.objects.filter(pk=client.pk).update(branch_id=branch_id)


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0005_client_branch'),
        ('core', '0018_branch_external_reporting_user_branch'),
    ]

    operations = [
        migrations.RunPython(assign_clients_to_branches, migrations.RunPython.noop),
    ]
