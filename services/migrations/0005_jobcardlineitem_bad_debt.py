from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('services', '0004_jobcard_branch'),
    ]

    operations = [
        migrations.AlterField(
            model_name='jobcardlineitem',
            name='status',
            field=models.CharField(
                choices=[
                    ('handled_paid', 'Handled & Paid'),
                    ('handled_not_paid', 'Handled — Awaiting Payment'),
                    ('bad_debt', 'Bad Debt — Over 12 Months'),
                    ('paid_not_handled', 'Paid — Not Yet Handled'),
                    ('not_handled', 'Not Yet Handled'),
                ],
                default='not_handled',
                max_length=20,
            ),
        ),
    ]