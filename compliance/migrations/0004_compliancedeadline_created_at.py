from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('compliance', '0003_alter_compliancedeadline_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='compliancedeadline',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True),
        ),
    ]