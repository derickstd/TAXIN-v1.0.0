"""
Auto-generated migration for new transaction and reporting models.
"""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
        ('clients', '0003_communicationlog'),
    ]

    operations = [
        
        migrations.CreateModel(
            name='TransactionEditLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('transaction_type', models.CharField(choices=[('invoice', 'Invoice'), ('job_card', 'Job Card'), ('compliance_deadline', 'Compliance Deadline'), ('payment', 'Payment')], max_length=30)),
                ('transaction_id', models.IntegerField()),
                ('transaction_code', models.CharField(blank=True, max_length=50)),
                ('old_values', models.JSONField(default=dict)),
                ('new_values', models.JSONField(default=dict)),
                ('reason', models.TextField(blank=True)),
                ('edited_at', models.DateTimeField(auto_now_add=True)),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='transaction_edits', to='clients.client')),
                ('edited_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='transaction_edits', to='core.user')),
            ],
            options={
                'ordering': ['-edited_at'],
            },
        ),
        
        migrations.CreateModel(
            name='ReportingSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200)),
                ('report_types', models.JSONField(default=list, help_text='List of report types to generate')),
                ('frequency', models.CharField(choices=[('daily', 'Daily'), ('weekly', 'Weekly (Monday)'), ('biweekly', 'Bi-weekly'), ('monthly', 'Monthly (1st of month)'), ('quarterly', 'Quarterly')], default='monthly', max_length=20)),
                ('email_recipients', models.JSONField(default=list, help_text='List of emails to send reports to')),
                ('outstanding_threshold', models.DecimalField(decimal_places=2, default=500000, help_text='Alert if outstanding exceeds this amount', max_digits=15)),
                ('overdue_days_threshold', models.IntegerField(default=30, help_text='Alert if invoices overdue more than this many days')),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('company', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reporting_settings', to='core.company')),
            ],
            options={
                'verbose_name_plural': 'Reporting Settings',
                'ordering': ['name'],
            },
        ),
        
        migrations.CreateModel(
            name='DuplicateClientSuggestion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('similarity_score', models.IntegerField(help_text='Similarity percentage (0-100)')),
                ('match_reasons', models.TextField(help_text='Reasons for duplicate suggestion')),
                ('status', models.CharField(choices=[('pending', 'Pending Review'), ('confirmed', 'Confirmed Duplicate'), ('false_positive', 'False Positive'), ('merged', 'Merged'), ('dismissed', 'Dismissed')], default='pending', max_length=20)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('duplicate_client', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='duplicate_suggestions_as_duplicate', to='clients.client')),
                ('primary_client', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='duplicate_suggestions_as_primary', to='clients.client')),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reviewed_duplicates', to='core.user')),
            ],
            options={
                'ordering': ['-similarity_score', '-created_at'],
                'unique_together': {('primary_client', 'duplicate_client')},
            },
        ),
        
        migrations.CreateModel(
            name='DuplicateTransactionAlert',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('transaction_type', models.CharField(choices=[('invoice', 'Invoice'), ('job_card', 'Job Card'), ('compliance_deadline', 'Compliance Deadline')], max_length=30)),
                ('transaction_id', models.IntegerField()),
                ('potential_duplicates', models.JSONField(default=list, help_text='List of similar transaction IDs')),
                ('reason', models.TextField()),
                ('status', models.CharField(choices=[('pending', 'Pending Review'), ('confirmed', 'Confirmed Duplicate'), ('legitimate', 'Legitimate Transaction'), ('resolved', 'Resolved')], default='pending', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='duplicate_transaction_alerts', to='clients.client')),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='core.user')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        
        migrations.CreateModel(
            name='MonthlyTrendData',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('year', models.IntegerField()),
                ('month', models.IntegerField()),
                ('total_invoiced', models.DecimalField(decimal_places=2, default=0, max_digits=15)),
                ('total_collected', models.DecimalField(decimal_places=2, default=0, max_digits=15)),
                ('total_expenses', models.DecimalField(decimal_places=2, default=0, max_digits=15)),
                ('jobs_created', models.IntegerField(default=0)),
                ('jobs_completed', models.IntegerField(default=0)),
                ('invoices_created', models.IntegerField(default=0)),
                ('new_clients', models.IntegerField(default=0)),
                ('net_profit', models.DecimalField(decimal_places=2, default=0, max_digits=15)),
                ('collection_rate', models.DecimalField(decimal_places=2, default=0, help_text='Percentage', max_digits=5)),
                ('last_updated', models.DateTimeField(auto_now=True)),
                ('company', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='monthly_trends', to='core.company')),
            ],
            options={
                'ordering': ['-year', '-month'],
                'unique_together': {('company', 'year', 'month')},
            },
        ),
        
        migrations.AddIndex(
            model_name='transactioneditlog',
            index=models.Index(fields=['transaction_type', 'transaction_id'], name='core_transa_transac_idx'),
        ),
        migrations.AddIndex(
            model_name='transactioneditlog',
            index=models.Index(fields=['client', 'edited_at'], name='core_transa_client__idx'),
        ),
        migrations.AddIndex(
            model_name='monthlytrenddata',
            index=models.Index(fields=['company', 'year', 'month'], name='core_monthly_company_idx'),
        ),
    ]
