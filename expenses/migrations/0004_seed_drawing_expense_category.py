from django.db import migrations


def add_drawing_category(apps, schema_editor):
    ExpenseCategory = apps.get_model('expenses', 'ExpenseCategory')
    if not ExpenseCategory.objects.filter(name__iexact='Drawing').exists():
        ExpenseCategory.objects.create(
            name='Drawing',
            description='Owner withdrawals and drawings',
        )


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0003_expense_branch'),
    ]

    operations = [
        migrations.RunPython(add_drawing_category, migrations.RunPython.noop),
    ]
