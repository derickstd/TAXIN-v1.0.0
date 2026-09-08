import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import jwt
import requests
from django.conf import settings


SCOPE = 'https://www.googleapis.com/auth/spreadsheets'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
API_ROOT = 'https://sheets.googleapis.com/v4/spreadsheets'
HEADERS = [
    'System ID', 'Client ID', 'Client', 'Credential Type', 'Label',
    'Username', 'Password', 'Status', 'Expiry Date', 'Notes', 'Updated At',
]


def _config():
    path = Path(settings.GOOGLE_SERVICE_ACCOUNT_FILE)
    if not path.exists():
        raise RuntimeError('Google service-account file was not found.')
    data = json.loads(path.read_text(encoding='utf-8'))
    if not data.get('client_email') or not data.get('private_key'):
        raise RuntimeError('Google service-account file is incomplete.')
    if not settings.GOOGLE_SHEET_ID:
        raise RuntimeError('GOOGLE_SHEET_ID is not configured.')
    return data


def _access_token():
    account = _config()
    now = int(time.time())
    assertion = jwt.encode(
        {
            'iss': account['client_email'],
            'scope': SCOPE,
            'aud': TOKEN_URL,
            'iat': now,
            'exp': now + 3600,
        },
        account['private_key'],
        algorithm='RS256',
    )
    response = requests.post(
        TOKEN_URL,
        data={'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer', 'assertion': assertion},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()['access_token']


def _request(method, path, **kwargs):
    headers = kwargs.pop('headers', {})
    headers['Authorization'] = f'Bearer {_access_token()}'
    response = requests.request(method, f'{API_ROOT}/{settings.GOOGLE_SHEET_ID}{path}', headers=headers, timeout=30, **kwargs)
    response.raise_for_status()
    return response.json() if response.content else {}


def _sheet_title():
    metadata = _request('GET', '', params={'fields': 'sheets.properties'})
    sheets = metadata.get('sheets', [])
    target_gid = str(settings.GOOGLE_SHEET_GID or '')
    for sheet in sheets:
        properties = sheet.get('properties', {})
        if target_gid and str(properties.get('sheetId')) == target_gid:
            return properties['title']
    if sheets:
        return sheets[0]['properties']['title']
    raise RuntimeError('The Google Sheet has no worksheets.')


def _range(title, suffix):
    return f"'{title.replace(chr(39), chr(39) * 2)}'!{suffix}"


def read_rows():
    title = _sheet_title()
    result = _request('GET', '/values/' + quote(_range(title, 'A:K'), safe="'!"))
    values = result.get('values', [])
    if not values:
        return title, []
    headers = values[0]
    positions = {header.strip(): index for index, header in enumerate(headers)}
    return title, headers, [
        {header: row[index] if index < len(row) else '' for header, index in positions.items()}
        for row in values[1:]
    ]


def write_rows(rows):
    title = _sheet_title()
    values = [HEADERS] + rows
    encoded_range = quote(_range(title, 'A1:K'), safe="'!:")
    _request('POST', f'/values/{encoded_range}:clear', json={})
    return _request(
        'PUT',
        f'/values/{encoded_range}',
        params={'valueInputOption': 'USER_ENTERED'},
        json={'range': _range(title, f'A1:K{len(values)}'), 'majorDimension': 'ROWS', 'values': values},
    )


def credential_rows(credentials):
    rows = []
    for credential in credentials:
        rows.append([
            str(credential.pk),
            credential.client.client_id,
            credential.client.get_display_name(),
            credential.get_credential_type_display(),
            credential.label,
            credential.get_username(),
            credential.get_password(),
            credential.status,
            credential.expiry_date.isoformat() if credential.expiry_date else '',
            credential.get_notes(),
            credential.created_at.astimezone(timezone.utc).isoformat(),
        ])
    return rows


def parse_date(value):
    if not value:
        return None
    return datetime.strptime(value, '%Y-%m-%d').date()
