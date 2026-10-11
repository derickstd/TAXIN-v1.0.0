# Monthly receivables API

The `GET /api/receivables-summary` endpoint returns a monthly receivables
summary for a company in the active database. Configure `RECEIVABLES_API_KEY`
in the server environment before using it; requests must send that value as a
bearer token.

```http
GET /api/receivables-summary?company=TAXMAN256&month=2026-10
Authorization: Bearer <RECEIVABLES_API_KEY>
```

Successful responses contain numeric amounts:

```json
{
  "company": "TAXMAN256",
  "month": "2026-10",
  "opening_receivables": 1200000,
  "work_billed_this_month": 2400000,
  "collected_this_month": 1800000,
  "closing_receivables": 1800000,
  "written_off_this_month": 0
}
```

Company is matched case-insensitively against an active company's slug.
Opening receivables are posted invoice balances before the month, less
payments dated before the month. Billed work is posted invoice value issued
during the month. Collections are payments dated during the month. Closing
receivables are opening receivables plus billed work, less collections and
write-offs.

Invoices do not currently have a dedicated write-off date or audit history.
Accordingly, `written_off_this_month` uses the `updated_at` date of invoices
whose current status is `written_off`; historical write-off totals may not be
reconstructable if an invoice's status was changed again later.

Errors use a consistent JSON envelope, with a stable machine-readable code,
a clear message, field-level details where relevant, and a request ID for
support investigations:

```json
{
  "error": {
    "code": "invalid_month",
    "message": "The 'month' parameter must use YYYY-MM format, for example 2026-10.",
    "details": {
      "field": "month",
      "provided": "2026-13",
      "expected_format": "YYYY-MM"
    }
  },
  "request_id": "..."
}
```

The same request ID is returned in the `X-Request-ID` response header. Missing
parameters or an invalid month return `400`, an unknown company returns `404`,
an invalid API key returns `401` with a `WWW-Authenticate: Bearer` header, an
unsupported method returns `405`, and an unset server key returns `503`.
Unexpected internal failures return a generic `500` response; full details
are logged server-side against the request ID and are not exposed to callers.

For Google Apps Script, store the key in Script Properties as
`RECEIVABLES_API_KEY` and call the endpoint with `UrlFetchApp.fetch`, passing
`Authorization: Bearer ` plus that property in the request headers. Avoid
putting the API key directly into a spreadsheet cell or formula.
