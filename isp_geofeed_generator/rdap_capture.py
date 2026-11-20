"""One public RDAP GET, preserved before validation; no referrals or publication."""
from datetime import datetime, timezone
import http.client
import ipaddress
import json
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, HTTPSHandler, build_opener

from . import __version__
from ._capture_directory import create_directory, write_new
from .client import GeofeedError, NoRedirects
from .feed import digest
from .local_output import read_output
from .rdap_bootstrap import MAX_BYTES as BOOTSTRAP_BYTES, plan_bootstrap
from .rdap_language import language_tag
from .registry_rdap import normalize_rdap

MAX_BYTES = 8_000_000
SOCKET_TIMEOUT = 20
READ_BUDGET = 30


def utc():
    return datetime.now(timezone.utc).isoformat()


def opener():
    return build_opener(ProxyHandler({}), NoRedirects(), HTTPSHandler(context=ssl.create_default_context()))


def _exchange(url):
    body, response, error = bytearray(), None, None
    result = {'request_started_at': utc(), 'http_status': None, 'body_complete': False,
              'response_observed_at': None, 'rdap_media_type': False, 'identity_encoding': False}
    started = time.monotonic()
    try:
        request = Request(url, method='GET', headers={'Accept': 'application/rdap+json',
            'Accept-Encoding': 'identity', 'Connection': 'close',
            'User-Agent': 'isp-geofeed-generator/' + __version__})
        try:
            response = opener().open(request, timeout=SOCKET_TIMEOUT)
        except HTTPError as exc:
            response = exc  # Save this one response; never follow or retry it.
        result['response_received_at'] = utc()
        result['http_status'] = response.getcode()
        result['rdap_media_type'] = response.headers.get('Content-Type', '').split(';', 1)[0].strip().lower() == 'application/rdap+json'
        result['identity_encoding'] = response.headers.get('Content-Encoding', '').strip().lower() in ('', 'identity')
        lengths = response.headers.get_all('Content-Length', [])
        length = None
        if lengths:
            if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit() or len(lengths[0]) > 10:
                error = 'invalid_content_length'
            else:
                length = int(lengths[0])
        while True:
            if time.monotonic() - started >= READ_BUDGET:
                error = 'read_budget'; break
            part = response.read1(min(65536, MAX_BYTES + 1 - len(body)))
            if not part:
                result['body_complete'] = True; break
            body.extend(part)
            if len(body) > MAX_BYTES:
                error = 'body_limit'; break
        if length is not None and length != len(body):
            result['body_complete'] = False
            error = error or 'incomplete_body'
        if time.monotonic() - started >= READ_BUDGET:
            error = error or 'read_budget'
    except http.client.IncompleteRead as exc:
        body.extend(exc.partial[:max(0, MAX_BYTES + 1 - len(body))])
        error = 'incomplete_body'
    except (URLError, OSError, http.client.HTTPException, ValueError):
        error = 'transport_failure'
    finally:
        if response is not None:
            try: response.close()
            except OSError: error = error or 'transport_failure'
    result['request_completed_at'] = utc()
    if result['body_complete']:
        result['response_observed_at'] = result['request_completed_at']
    result['read_error'] = error
    return bytes(body[:MAX_BYTES]), result


def capture(path, prefix, observed_at, destination, *, rdap_language=None):
    if rdap_language is not None: language_tag(rdap_language)
    bootstrap = read_output(path, BOOTSTRAP_BYTES)
    if bootstrap.identity is None:
        raise GeofeedError('RDAP capture needs an existing bounded regular bootstrap file')
    plan = plan_bootstrap(bootstrap.data, prefix, observed_at)
    folder = create_directory(destination)
    def save(name, value):
        data = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=True, indent=2).encode()
        try:
            write_new(folder/name, data)
        except OSError:
            raise GeofeedError('Capture storage failed; retained evidence may be incomplete, no request was retried and no existing file was overwritten') from None
    save('bootstrap.json', bootstrap.data)
    save('request.json', {'schema_version': 1, 'intent_recorded_at': utc(), 'plan': plan,
                          'rdap_language': rdap_language, 'automatic_retries': False, 'follow_redirects': False})
    body, receipt = _exchange(plan['rdap_lookup_url'])
    name = 'response.body' if receipt['body_complete'] else 'response.partial'
    receipt.update({'schema_version': 1, 'saved_body_file': name, 'saved_bytes': len(body),
                    'saved_sha256': digest(body), 'lookup_url': plan['rdap_lookup_url'],
                    'validation': 'not_measured'})
    save(name, body)
    save('receipt.json', receipt)  # Immutable HTTP observation, before any JSON parsing.
    reason = None
    if receipt['read_error'] or not receipt['body_complete']:
        reason = 'incomplete_or_failed_read'
    elif receipt['http_status'] != 200:
        reason = 'http_status_refused'
    elif not receipt['rdap_media_type'] or not receipt['identity_encoding']:
        reason = 'unsupported_media_or_encoding'
    metadata, scope = {}, None
    if reason is None:
        try:
            normalized, metadata = normalize_rdap(body, receipt['response_observed_at'], rdap_language=rdap_language)
            scope = json.loads(normalized)['objects'][0]
            requested = ipaddress.ip_network(plan['requested_prefix'])
            start, end = ipaddress.ip_address(scope['start']), ipaddress.ip_address(scope['end'])
            if (requested.version != start.version or int(requested.network_address) < int(start)
                    or int(requested.broadcast_address) > int(end)):
                reason = 'requested_scope_not_covered'
        except GeofeedError:
            reason = 'unsupported_rdap_response'
    validation = {'schema_version': 1, 'validation': 'refused' if reason else 'accepted', 'reason': reason}
    save('validation.json', validation)
    if reason:
        raise GeofeedError('RDAP capture refused (' + reason + '); evidence retained, no links followed and no comparison or publication made')
    return {'capture_only': True, 'support_level': 'initial', 'requested_prefix': plan['requested_prefix'],
            'address_family': plan['address_family'], 'lookup_url': plan['rdap_lookup_url'],
            'response_observed_at': receipt['response_observed_at'], 'response_sha256': digest(body),
            'response_bytes': len(body), 'rdap_validation': 'accepted',
            'returned_scope': {'start': scope['start'], 'end': scope['end']}, **metadata,
            'registry_source': 'captured_rdap', 'registry_authority': 'not_measured',
            'bootstrap_sha256': plan['bootstrap_sha256'], 'bootstrap_authenticity': 'not_measured',
            'feed_comparison': 'not_measured', 'ownership_validation': 'not_measured',
            'current_allocation_validation': 'not_measured', 'signature_validation': 'not_measured',
            'public_retrieval': 'not_measured', 'provider_ingestion': 'not_measured'}
