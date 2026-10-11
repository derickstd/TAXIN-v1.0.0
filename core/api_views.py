import calendar
import logging
import re
import secrets
from datetime import date
from decimal import Decimal
from uuid import uuid4

from django.conf import settings
from django.db import DatabaseError
from django.db.models import Sum
from django.http import JsonResponse

from billing.models import Invoice, Payment
from core.models import Company


logger = logging.getLogger(__name__)
MONTH_PATTERN = re.compile(r'^\d{4}-(0[1-9]|1[0-2])$')


def _api_error(request_id, status, code, message, details=None, headers=None):
    response = JsonResponse({
        'error': {
            'code': code,
            'message': message,
            'details': details or {},
        },
        'request_id': request_id,
    }, status=status)
    response['X-Request-ID'] = request_id
    for name, value in (headers or {}).items():
        response[name] = value
    return response


def _amount(queryset, field):
    return queryset.aggregate(total=Sum(field))['total'] or Decimal('0')


def receivables_summary(request):
    """Return an API-key-protected monthly receivables summary for one company."""
    request_id = uuid4().hex
    if request.method != 'GET':
        return _api_error(
            request_id,
            405,
            'method_not_allowed',
            'This endpoint only supports GET requests.',
            headers={'Allow': 'GET'},
        )

    configured_key = settings.RECEIVABLES_API_KEY
    if not configured_key:
        logger.error(
            'Receivables API key is not configured (request_id=%s).',
            request_id,
        )
        return _api_error(
            request_id,
            503,
            'service_unavailable',
            'The receivables service is temporarily unavailable. Please contact support.',
        )

    authorization = request.headers.get('Authorization', '')
    scheme, separator, supplied_key = authorization.partition(' ')
    if (
        not separator
        or scheme.lower() != 'bearer'
        or not secrets.compare_digest(supplied_key.strip(), configured_key)
    ):
        return _api_error(
            request_id,
            401,
            'authentication_required',
            'A valid bearer API key is required to access this endpoint.',
            headers={'WWW-Authenticate': 'Bearer'},
        )

    company_slug = request.GET.get('company', '').strip()
    month = request.GET.get('month', '').strip()
    if not company_slug or not month:
        missing_fields = [
            name for name, value in (('company', company_slug), ('month', month))
            if not value
        ]
        return _api_error(
            request_id,
            400,
            'missing_parameters',
            'Provide all required query parameters: company and month.',
            details={'missing_fields': missing_fields},
        )
    if not MONTH_PATTERN.fullmatch(month) or month.startswith('0000-'):
        return _api_error(
            request_id,
            400,
            'invalid_month',
            "The 'month' parameter must use YYYY-MM format, for example 2026-10.",
            details={
                'field': 'month',
                'provided': month,
                'expected_format': 'YYYY-MM',
            },
        )

    try:
        company = Company.objects.filter(
            slug__iexact=company_slug,
            active=True,
        ).first()
        if company is None:
            return _api_error(
                request_id,
                404,
                'company_not_found',
                'No active company matches the supplied company identifier.',
                details={'field': 'company', 'provided': company_slug},
            )

        year, month_number = (int(part) for part in month.split('-'))
        first_day = date(year, month_number, 1)
        last_day = first_day.replace(
            day=calendar.monthrange(year, month_number)[1]
        )

        posted_invoices = Invoice.objects.filter(
            document_type='invoice',
            date_issued__lte=last_day,
        ).exclude(status='draft')

        opening_invoices = posted_invoices.filter(date_issued__lt=first_day).exclude(
            status='written_off',
            updated_at__date__lt=first_day,
        )
        opening_receivables = _amount(opening_invoices, 'grand_total') - _amount(
            Payment.objects.filter(
                invoice__in=opening_invoices,
                payment_date__lt=first_day,
            ),
            'amount',
        )

        month_invoices = posted_invoices.filter(
            date_issued__gte=first_day,
            date_issued__lte=last_day,
        )
        work_billed = _amount(month_invoices, 'grand_total')

        month_payments = Payment.objects.filter(
            invoice__in=posted_invoices,
            payment_date__gte=first_day,
            payment_date__lte=last_day,
        )
        collected = _amount(month_payments, 'amount')

        written_off_invoices = posted_invoices.filter(
            status='written_off',
            updated_at__date__gte=first_day,
            updated_at__date__lte=last_day,
        )
        written_off = _amount(written_off_invoices, 'grand_total') - _amount(
            Payment.objects.filter(
                invoice__in=written_off_invoices,
                payment_date__lte=last_day,
            ),
            'amount',
        )

        closing_receivables = (
            opening_receivables + work_billed - collected - written_off
        )
        response = JsonResponse({
            'company': company_slug,
            'month': month,
            'opening_receivables': float(opening_receivables),
            'work_billed_this_month': float(work_billed),
            'collected_this_month': float(collected),
            'closing_receivables': float(closing_receivables),
            'written_off_this_month': float(written_off),
        })
        response['X-Request-ID'] = request_id
        return response
    except DatabaseError:
        logger.exception(
            'Database error while processing receivables summary (request_id=%s)',
            request_id,
        )
        return _api_error(
            request_id,
            503,
            'service_unavailable',
            'The receivables service is temporarily unavailable. Please retry shortly.',
        )
    except Exception:
        logger.exception(
            'Unexpected error while processing receivables summary (request_id=%s)',
            request_id,
        )
        return _api_error(
            request_id,
            500,
            'internal_server_error',
            'We could not complete your request. Please retry or contact support with the request ID.',
        )
