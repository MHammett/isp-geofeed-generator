"""Policy-bound local publication and explicit conditional recovery."""
import json
import os
from pathlib import Path
import re
import secrets

from .client import GeofeedError
from .feed import digest
from .local_output import output_lock, read_output, change_description
from .overlap import REJECT, LONGEST_PREFIX
from .publish import atomic_write


def destination(path):
    path = Path(path)
    return path.parent.resolve() / path.name


def policy_path(path):
    return path.parent / ('.' + path.name + '.isp-geofeed-policy.json')


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode() + b'\n'


def manifest(data, kind):
    try:
        value = json.loads(data)
        if (set(value) != {'schema_version','format','overlap_policy','sha256','publication_id'}
                or type(value['schema_version']) is not int or value['schema_version'] != 2
                or value['format'] != kind or value['overlap_policy'] != LONGEST_PREFIX
                or not re.fullmatch(r'[0-9a-f]{64}', value['sha256'])
                or not re.fullmatch(r'[0-9a-f]{32}', value['publication_id'])):
            raise ValueError()
        return value
    except (TypeError, ValueError, KeyError):
        raise GeofeedError('Invalid local policy state; inspect before publishing') from None


def same_pair(path, before, metadata, max_bytes):
    current = read_output(path,max_bytes)
    if current != before:
        changed = change_description(before,current)
        raise GeofeedError(f'Destination bytes or policy changed; no overwrite attempted [feed changed: {changed}]')
    current = read_output(policy_path(path),4096)
    if current != metadata:
        changed = change_description(metadata,current)
        raise GeofeedError(f'Destination bytes or policy changed; no overwrite attempted [policy changed: {changed}]')


def backup_name(kind):
    return 'before.csv' if kind == 'csv' else 'before-records.json'


def validate_bytes(value, kind, policy):
    if not value:
        return
    if kind == 'csv':
        from .feed import parse_feed
        parse_feed(value,overlap_policy=policy)
    else:
        from .records import parse_records
        parse_records(value,overlap_policy=policy)


def publish_bound(path, value, state_dir, kind, validate, max_bytes):
    """Publish nested data and matching metadata; never silently repair a split pair."""
    path = destination(path)
    directory = Path(state_dir)
    with output_lock(path):
        before, metadata = read_output(path,max_bytes), read_output(policy_path(path),4096)
        old = manifest(metadata.data,kind) if metadata.identity is not None else None
        if old is not None and (before.identity is None or not before.data or old['sha256'] != digest(before.data)):
            raise GeofeedError('Local feed/policy pair is incomplete or mismatched; recovery needs attention')
        old_policy = LONGEST_PREFIX if old is not None else REJECT
        try:
            validate_bytes(before.data,kind,old_policy)
        except GeofeedError:
            if old is None:
                from .envelope import PREFIX
                marked=kind=='csv' and before.data.startswith(PREFIX)
                if kind=='records':
                    try:
                        doc=json.loads(before.data)
                        marked=isinstance(doc,dict) and doc.get('schema_version')==2 and doc.get('overlap_policy')==LONGEST_PREFIX
                    except (ValueError,TypeError):pass
                if marked:
                    raise GeofeedError('Nested local output has no matching policy file; recovery needs attention. '
                                       'Keep the schedule stopped and inspect recover-local with the original state directory and candidate hash') from None
            raise
        validate_bytes(value,kind,LONGEST_PREFIX)
        validate(before.data,value,old_policy)
        if before.data == value:
            if old is None:
                raise GeofeedError('Nested bytes have no bound local policy state; recovery needs attention')
            same_pair(path,before,metadata,max_bytes)
            return False
        next_doc={'schema_version':2,'format':kind,'overlap_policy':LONGEST_PREFIX,
                  'sha256':digest(value),'publication_id':secrets.token_hex(16)}
        next_bytes=encode(next_doc)
        prior={'sha256':digest(before.data),'manifest':old,'exists':before.identity is not None}
        journal={'schema_version':2,'format':kind,'destination':digest(os.path.normcase(str(path)).encode()),
                 'candidate_sha256':digest(value),'before':prior,'after':next_doc,'phase':'prepared'}
        atomic_write(directory/backup_name(kind),before.data)
        atomic_write(directory/'before.policy.json',encode(prior))
        atomic_write(directory/'local-transaction.json',encode(journal))
        phase='candidate replacement'
        try:
            atomic_write(path,value,0o644,before_replace=lambda:same_pair(path,before,metadata,max_bytes))
            phase='candidate verification'
            written=read_output(path,max_bytes)
            if written.data != value:
                raise GeofeedError('Local candidate read-back differs')
            phase='policy replacement'
            atomic_write(policy_path(path),next_bytes,before_replace=lambda:same_pair(path,written,metadata,max_bytes))
            phase='pair verification'
            committed=read_output(policy_path(path),4096)
            if committed.data != next_bytes:
                raise GeofeedError('Local policy read-back differs')
            same_pair(path,written,committed,max_bytes)
            phase='private transaction completion';journal['phase']='committed'
            atomic_write(directory/'local-transaction.json',encode(journal))
        except (OSError,GeofeedError) as exc:
            detail=str(exc) if isinstance(exc,GeofeedError) else type(exc).__name__
            raise GeofeedError(f'Local policy-bound publication failed during {phase} ({detail}); recovery needs attention. '
                               f'Candidate sha256={digest(value)}; no blind restore attempted') from None
        return True


def recover_bound(path, state_dir, kind, expected):
    """Restore only this transaction's exact baseline while it still owns the pair."""
    path=destination(path);directory=Path(state_dir)
    max_bytes=1_000_000 if kind=='csv' else 8_000_000
    if kind not in ('csv','records') or not isinstance(expected,str) or not re.fullmatch(r'[0-9a-f]{64}',expected):
        raise GeofeedError('Local recovery requires format and exact expected candidate SHA-256')
    with output_lock(path):
        try:
            journal=json.loads(read_output(directory/'local-transaction.json',8192).data)
            prior=json.loads(read_output(directory/'before.policy.json',4096).data)
            baseline=read_output(directory/backup_name(kind),max_bytes).data
            if (set(journal)!={'schema_version','format','destination','candidate_sha256','before','after','phase'}
                    or type(journal['schema_version']) is not int or journal['schema_version']!=2
                    or journal['format']!=kind or journal['destination']!=digest(os.path.normcase(str(path)).encode())
                    or journal['candidate_sha256']!=expected or journal['phase'] not in ('prepared','committed','recovering','recovered')
                    or prior!=journal['before'] or set(prior)!={'sha256','manifest','exists'}
                    or type(prior['exists']) is not bool or prior['sha256']!=digest(baseline)
                    or (not prior['exists'] and baseline)):
                raise ValueError()
            next_doc=manifest(encode(journal['after']),kind)
            if next_doc['sha256']!=expected:
                raise ValueError()
            old=manifest(encode(prior['manifest']),kind) if prior['manifest'] is not None else None
            if old is not None and (old['sha256']!=digest(baseline) or not baseline or not prior['exists']):
                raise ValueError()
            validate_bytes(baseline,kind,LONGEST_PREFIX if old is not None else REJECT)
        except (ValueError,KeyError,TypeError,GeofeedError):
            raise GeofeedError('Local recovery baseline or transaction is invalid; no write attempted') from None
        current,metadata=read_output(path,max_bytes),read_output(policy_path(path),4096)
        allowed=[encode(next_doc),encode(old) if old is not None else b'']
        if metadata.data not in allowed or (metadata.identity is not None and not metadata.data):
            raise GeofeedError('Local policy changed concurrently; refusing recovery')
        is_candidate=current.identity is not None and digest(current.data)==expected
        is_baseline=(current.data==baseline and (current.identity is not None)==prior['exists'])
        baseline_owned=is_baseline and (metadata.data==allowed[1] or journal['phase'] in ('recovering','recovered'))
        if not is_candidate and not baseline_owned:
            raise GeofeedError('Local bytes changed concurrently; refusing recovery')
        if journal['phase']=='recovered' and is_baseline and metadata.data==allowed[1]:
            same_pair(path,current,metadata,max_bytes)
            return {'changed':False,'recovered':True,'sha256':digest(baseline),'path':str(path)}
        journal['phase']='recovering';atomic_write(directory/'local-transaction.json',encode(journal))
        try:
            if not is_baseline:
                if prior['exists']:
                    atomic_write(path,baseline,0o644,before_replace=lambda:same_pair(path,current,metadata,max_bytes))
                else:
                    same_pair(path,current,metadata,max_bytes);path.unlink()
            restored=read_output(path,max_bytes)
            if restored.data!=baseline or (restored.identity is not None)!=prior['exists']:
                raise GeofeedError('Recovery byte verification differs')
            if old is not None:
                atomic_write(policy_path(path),encode(old),before_replace=lambda:same_pair(path,restored,metadata,max_bytes))
            elif metadata.identity is not None:
                same_pair(path,restored,metadata,max_bytes);policy_path(path).unlink()
            final=read_output(policy_path(path),4096)
            if final.data!=allowed[1] or (old is None and final.identity is not None):
                raise GeofeedError('Recovery policy verification differs')
            same_pair(path,restored,final,max_bytes)
            journal['phase']='recovered';atomic_write(directory/'local-transaction.json',encode(journal))
        except (OSError,GeofeedError):
            raise GeofeedError('Local recovery interrupted; keep schedule stopped and repeat the same recovery command after inspection') from None
        return {'changed':not is_baseline,'recovered':True,'sha256':digest(baseline),'path':str(path)}
