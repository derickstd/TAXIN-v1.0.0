from django.core.management.base import BaseCommand
from compliance.models import ComplianceObligation, ComplianceDeadline


class Command(BaseCommand):
    help = 'Check for clients with obligations but no compliance deadlines'

    def handle(self, *args, **options):
        obls = ComplianceObligation.objects.filter(is_active=True).select_related('client', 'service_type')
        
        self.stdout.write('Checking all active obligations...\n')
        
        missing = []
        for obl in obls:
            deadline_count = ComplianceDeadline.objects.filter(obligation=obl).count()
            status = '✓' if deadline_count > 0 else '✗'
            self.stdout.write(f'{status} {obl.client.client_id} - {obl.service_type.name} - Deadlines: {deadline_count}')
            
            if deadline_count == 0:
                missing.append(obl)
        
        self.stdout.write(f'\nTotal obligations: {obls.count()}')
        self.stdout.write(f'Missing deadlines: {len(missing)}')
        
        if missing:
            self.stdout.write(self.style.WARNING('\n⚠️  Clients with obligations but NO compliance deadlines:'))
            for o in missing:
                self.stdout.write(f'  - {o.client.client_id} ({o.client.get_display_name()}) - {o.service_type.name}')
            self.stdout.write(f'\nRun: python manage.py fix_compliance_deadlines')
        else:
            self.stdout.write(self.style.SUCCESS('\n✅ All obligations have compliance deadlines!'))
