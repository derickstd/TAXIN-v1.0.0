from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0016_systemmodulevisibility_company_and_more')]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='role',
            field=models.CharField(
                choices=[
                    ('receptionist', 'Receptionist'),
                    ('tax_officer', 'Tax Officer'),
                    ('senior_officer', 'Senior Officer'),
                    ('manager', 'Manager'),
                    ('ceo', 'CEO'),
                    ('admin', 'Admin'),
                ],
                default='tax_officer',
                max_length=20,
            ),
        ),
    ]