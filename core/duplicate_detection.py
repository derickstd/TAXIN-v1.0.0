"""
Duplicate detection utilities for clients and transactions.
"""

from django.db.models import Q, F
try:
    from fuzzywuzzy import fuzz
except Exception:
    # Fallback if fuzzywuzzy is not installed
    import difflib

    class _SimpleFuzz:
        @staticmethod
        def token_set_ratio(a, b):
            if not a or not b:
                return 0
            a_tokens = set(a.lower().split())
            b_tokens = set(b.lower().split())
            if not a_tokens or not b_tokens:
                return 0
            inter = a_tokens & b_tokens
            union = a_tokens | b_tokens
            token_ratio = int(len(inter) / len(union) * 100)
            # Also combine with sequence matcher for some nuance
            seq = difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()
            return int((token_ratio + seq * 100) / 2)

    fuzz = _SimpleFuzz()
from clients.models import Client
from datetime import timedelta
from django.utils import timezone


def find_duplicate_clients(client=None, full_name=None, phone=None, whatsapp=None, tin=None, similarity_threshold=80):
    """
    Find potential duplicate clients based on similarity.
    
    Args:
        client: Client instance to find duplicates for (if None, use other params)
        full_name: Full name to match
        phone: Phone number to match
        whatsapp: WhatsApp number to match
        tin: TIN to match
        similarity_threshold: Similarity percentage threshold (0-100)
    
    Returns:
        List of tuples (similar_client, similarity_score, reason)
    """
    if client:
        full_name = client.full_name
        phone = client.phone_primary
        whatsapp = client.phone_whatsapp
        tin = client.tin
    
    if not any([full_name, phone, tin]):
        return []
    
    candidates = Client.objects.all()
    if client:
        candidates = candidates.exclude(pk=client.pk)
    
    duplicates = []
    
    for candidate in candidates:
        reasons = []
        scores = []
        
        # Check TIN match (exact or very similar)
        if tin and candidate.tin:
            if tin == candidate.tin:
                reasons.append(f"TIN match: {tin}")
                scores.append(100)
            else:
                name_sim = fuzz.token_set_ratio(tin, candidate.tin)
                if name_sim >= similarity_threshold:
                    reasons.append(f"TIN similar ({name_sim}%): {tin} vs {candidate.tin}")
                    scores.append(name_sim)
        
        # Check phone/WhatsApp match (exact)
        phone_numbers = set()
        if phone:
            phone_numbers.add(phone)
        if whatsapp:
            phone_numbers.add(whatsapp)

        for number in phone_numbers:
            if candidate.phone_primary == number or candidate.phone_whatsapp == number:
                reasons.append(f"Phone/WhatsApp match: {number}")
                scores.append(100)
                break

        # Check name similarity
        if full_name and candidate.full_name:
            name_sim = fuzz.token_set_ratio(full_name.lower(), candidate.full_name.lower())
            if name_sim >= similarity_threshold:
                reasons.append(f"Name similarity ({name_sim}%): {full_name}")
                scores.append(name_sim)
        
        # Also check trading name if available
        if hasattr(candidate, 'trading_name') and candidate.trading_name and full_name:
            trade_sim = fuzz.token_set_ratio(full_name.lower(), candidate.trading_name.lower())
            if trade_sim >= similarity_threshold:
                reasons.append(f"Trading name similarity ({trade_sim}%): {candidate.trading_name}")
                scores.append(trade_sim)
        
        if reasons:
            avg_score = sum(scores) / len(scores) if scores else 0
            duplicates.append((candidate, avg_score, " | ".join(reasons)))
    
    return sorted(duplicates, key=lambda x: x[1], reverse=True)


def check_duplicate_transaction(client, service_type=None, job_card=None, period_year=None, 
                                period_month=None, deadline_type=None, within_days=7):
    """
    Check if a similar transaction already exists for the client.
    
    Args:
        client: Client instance
        service_type: ServiceType for compliance/job
        job_card: JobCard instance (alternative to service_type)
        period_year: Year of the period
        period_month: Month of the period
        deadline_type: Type of deadline (for compliance)
        within_days: Check transactions within this many days
    
    Returns:
        List of existing similar transactions
    """
    from compliance.models import ComplianceDeadline
    from services.models import JobCard
    from billing.models import Invoice
    
    existing = []
    now = timezone.now().date()
    date_threshold = now - timedelta(days=within_days)
    
    # Check for similar compliance deadlines
    if service_type or deadline_type:
        # ComplianceDeadline does not have a `created_at` field — use `due_date`
        # to find recent or upcoming deadlines instead.
        deadlines = ComplianceDeadline.objects.filter(
            obligation__client=client,
            due_date__gte=date_threshold
        ).select_related('obligation__service_type')
        
        if service_type:
            deadlines = deadlines.filter(obligation__service_type=service_type)
        
        if period_year and period_month:
            deadlines = deadlines.filter(
                obligation__client=client,
                period_label__icontains=f"{period_year}"
            )
        
        for deadline in deadlines[:5]:
            existing.append({
                'type': 'compliance_deadline',
                'object': deadline,
                'description': f"{deadline.obligation.service_type.name} - {deadline.period_label}",
                'due_date': deadline.due_date,
                'status': deadline.status
            })
    
    # Check for similar job cards
    if job_card or (period_year and period_month):
        jobs = JobCard.objects.filter(
            client=client,
            created_at__gte=date_threshold
        )
        
        if job_card:
            jobs = jobs.exclude(pk=job_card.pk)
        
        if period_year and period_month:
            jobs = jobs.filter(period_year=period_year, period_month=period_month)
        
        for job in jobs[:5]:
            existing.append({
                'type': 'job_card',
                'object': job,
                'description': f"{job.job_number} - {job.get_period_label()}",
                'created_at': job.created_at,
                'status': job.status
            })
    
    # Check for similar invoices attached to job cards for the same period
    if period_year:
        invoices = Invoice.objects.filter(
            client=client,
            job_card__isnull=False,
            created_at__gte=date_threshold,
        )
        if period_month:
            invoices = invoices.filter(job_card__period_year=period_year, job_card__period_month=period_month)
        else:
            invoices = invoices.filter(job_card__period_year=period_year)
        if service_type:
            invoices = invoices.filter(job_card__line_items__service_type=service_type)

        for invoice in invoices.distinct()[:3]:
            existing.append({
                'type': 'invoice',
                'object': invoice,
                'description': f"{invoice.invoice_number} - {invoice.document_type}",
                'date': invoice.date_issued,
                'amount': invoice.grand_total
            })
    
    return existing


def merge_clients(primary_client, duplicate_client, merge_data=None):
    """
    Merge a duplicate client into the primary client.
    
    Args:
        primary_client: The client to keep
        duplicate_client: The client to merge into primary
        merge_data: Dict with merge options (keep_phone, keep_email, keep_address, etc.)
    
    Returns:
        Tuple of (success, message, affected_count)
    """
    from django.db import transaction
    from clients.models import WalkInIntake, CommunicationLog
    
    if not merge_data:
        merge_data = {}
    
    try:
        with transaction.atomic():
            # Update related records
            models_to_update = [
                ('job_cards', 'client'),
                ('invoices', 'client'),
                ('obligations', 'client'),
                ('communications', 'client'),
                ('walkin_intakes', 'client'),
                ('subscriptions', 'client'),
            ]
            
            affected_count = 0
            for relation_name, field_name in models_to_update:
                if hasattr(duplicate_client, relation_name):
                    manager = getattr(duplicate_client, relation_name)
                    count = manager.update(**{field_name: primary_client})
                    affected_count += count
            
            # Optionally merge contact information
            if merge_data.get('keep_phone_from_duplicate'):
                primary_client.phone_primary = duplicate_client.phone_primary
            
            if merge_data.get('keep_email_from_duplicate'):
                primary_client.email = duplicate_client.email
            
            if merge_data.get('keep_address_from_duplicate'):
                primary_client.physical_address = duplicate_client.physical_address
            
            if merge_data.get('keep_trading_name_from_duplicate'):
                primary_client.trading_name = duplicate_client.trading_name
            
            primary_client.notes = f"{primary_client.notes}\n[Merged from {duplicate_client.client_id}]\n{duplicate_client.notes}".strip()
            primary_client.save()
            
            # Mark duplicate as merged (instead of deleting)
            duplicate_client.status = 'merged'
            duplicate_client.notes = f"Merged into {primary_client.client_id} on {timezone.now().date()}"
            duplicate_client.save()
            
            return True, f"Successfully merged {duplicate_client.client_id} into {primary_client.client_id}. Updated {affected_count} related records.", affected_count
    
    except Exception as e:
        return False, f"Error merging clients: {str(e)}", 0
