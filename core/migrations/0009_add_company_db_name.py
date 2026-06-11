from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_merge_20260611_0011'),
    ]

    operations = [
        migrations.AddField(
            model_name='company',
            name='db_name',
            field=models.CharField(blank=True, help_text='Optional database alias or filename for company-specific DB', max_length=255),
        ),
    ]
