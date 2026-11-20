"""Offline consistency checks for version-1 RDAP capture evidence directories."""
from datetime import datetime, timezone
import ipaddress
import json
from pathlib import Path
import stat

from .client import GeofeedError
from .feed import digest
from .local_output import identity, read_output
from .rdap_bootstrap import plan_bootstrap, _timestamp
from .registry_check import _unique_json, _invalid_constant
from .registry_rdap import _finite_float, normalize_rdap

FILES = (('bootstrap.json',1_000_000),('request.json',32_000),('response.body',8_000_000),
         ('receipt.json',8_000),('validation.json',1_000))
REQUEST_KEYS = {'schema_version','intent_recorded_at','plan','rdap_language','automatic_retries','follow_redirects'}
RECEIPT_KEYS = {'schema_version','request_started_at','http_status','body_complete','response_observed_at',
    'rdap_media_type','identity_encoding','response_received_at','request_completed_at','read_error',
    'saved_body_file','saved_bytes','saved_sha256','lookup_url','validation'}


def _document(data, keys):
    value=json.loads(data,object_pairs_hook=_unique_json,parse_constant=_invalid_constant,parse_float=_finite_float)
    if (not isinstance(value,dict) or set(value)!=keys or type(value.get('schema_version')) is not int
            or value['schema_version']!=1):
        raise ValueError()
    return value


def _directory(path):
    info=path.lstat()
    if not stat.S_ISDIR(info.st_mode) or getattr(info,'st_file_attributes',0) & 0x400:
        raise ValueError()
    return identity(info)


def read_capture(path, remaining, *, now=None):
    """Return normalized records, metadata, body hash and all consumed evidence bytes."""
    current=datetime.now(timezone.utc) if now is None else now
    try:
        folder=Path(path);directory=_directory(folder)
        # A capture writer creates either a complete body or a partial file, never both.
        try: (folder/'response.partial').lstat()
        except FileNotFoundError: pass
        else: raise ValueError()
        snapshots={};used=0
        for name,limit in FILES:
            snapshot=read_output(folder/name,min(limit,max(0,remaining-used)))
            if snapshot.identity is None:raise ValueError()
            snapshots[name]=snapshot;used+=len(snapshot.data)
        request=_document(snapshots['request.json'].data,REQUEST_KEYS)
        receipt=_document(snapshots['receipt.json'].data,RECEIPT_KEYS)
        validation=_document(snapshots['validation.json'].data,{'schema_version','validation','reason'})
        if (request['automatic_retries'] is not False or request['follow_redirects'] is not False
                or type(receipt['http_status']) is not int or receipt['http_status']!=200
                or receipt['body_complete'] is not True or receipt['rdap_media_type'] is not True
                or receipt['identity_encoding'] is not True or receipt['read_error'] is not None
                or receipt['validation']!='not_measured' or receipt['saved_body_file']!='response.body'
                or validation['validation']!='accepted' or validation['reason'] is not None):
            raise ValueError()
        body=snapshots['response.body'].data
        if (type(receipt['saved_bytes']) is not int or receipt['saved_bytes']!=len(body)
                or receipt['saved_sha256']!=digest(body)):
            raise ValueError()
        plan=request['plan']
        if not isinstance(plan,dict):raise ValueError()
        plan_time=_timestamp(plan.get('observed_at'),current)
        expected=plan_bootstrap(snapshots['bootstrap.json'].data,plan.get('requested_prefix'),
                                plan.get('bootstrap_observed_at'),now=plan_time)
        if (json.dumps(plan,sort_keys=True)!=json.dumps(expected,sort_keys=True)
                or receipt['lookup_url']!=expected['rdap_lookup_url']):
            raise ValueError()
        times=[plan_time,_timestamp(request['intent_recorded_at'],current),
               _timestamp(receipt['request_started_at'],current),_timestamp(receipt['response_received_at'],current),
               _timestamp(receipt['request_completed_at'],current)]
        observed=_timestamp(receipt['response_observed_at'],current)
        if times!=sorted(times) or observed!=times[-1]:raise ValueError()
        normalized,metadata=normalize_rdap(body,receipt['response_observed_at'],rdap_language=request['rdap_language'])
        row=json.loads(normalized)['objects'][0]
        requested=ipaddress.ip_network(expected['requested_prefix'])
        start,end=ipaddress.ip_address(row['start']),ipaddress.ip_address(row['end'])
        if (requested.version!=start.version or int(requested.network_address)<int(start)
                or int(requested.broadcast_address)>int(end)):
            raise ValueError()
        # Check the same originals again; no mixed-generation directory is accepted.
        for name,limit in FILES:
            if read_output(folder/name,limit)!=snapshots[name]:raise ValueError()
        if _directory(folder)!=directory:raise ValueError()
        manifest={name:digest(snapshot.data) for name,snapshot in snapshots.items()}
        metadata.update(registry_source='operator_supplied_rdap_capture',
            snapshot_observed_at_source='capture_receipt_unverified',
            capture_integrity='internally_consistent',capture_authenticity='not_measured',
            capture_response_observed_at=receipt['response_observed_at'],
            capture_manifest_sha256=digest(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()),
            capture_evidence_bytes=used,capture_requested_prefix=expected['requested_prefix'],
            registry_authority='not_measured',bootstrap_authenticity='not_measured')
        return normalized,metadata,digest(body),used
    except (OSError,ValueError,TypeError,KeyError,UnicodeError,RecursionError):
        raise GeofeedError('RDAP capture needs complete, consistent version-1 evidence with an accepted response, matching hashes, dates, plan and whole query scope; values are not logged') from None
