"""Version-2 WordPress policy negotiation, ownership and conditional recovery."""
from dataclasses import dataclass
import json
from pathlib import Path
import re
import secrets

from .client import GeofeedError
from .feed import change_guard,digest,parse_feed
from .overlap import REJECT,LONGEST_PREFIX,validate_policy


class PolicyMismatch(GeofeedError):
    """A strict legacy preflight needs explicit policy negotiation."""


@dataclass(frozen=True)
class Snapshot:
    csv: bytes
    policy: str
    required: str
    previous: bytes
    previous_policy: str
    publication_id: str | None


def read_state(client):
    try:
        value=client.http.request(client.base.removesuffix('/v1')+'/v2/state',headers=client.headers)
    except GeofeedError as exc:
        if re.match(r'HTTP 404\b',str(exc)):
            raise GeofeedError('WordPress lacks version-2 policy state; upgrade the plugin before nested publication') from None
        if re.match(r'HTTP (401|403)\b',str(exc)):
            raise GeofeedError('WordPress policy state access refused; check application password, role, Authorization forwarding and HTTPS recognition') from None
        raise
    try:
        if (not isinstance(value,dict) or type(value.get('protocol_version')) is not int or value['protocol_version']!=2
                or not isinstance(value.get('supported_overlap_policies'),list)
                or len(value['supported_overlap_policies'])!=2
                or set(value['supported_overlap_policies'])!={REJECT,LONGEST_PREFIX}):raise ValueError()
        policy=validate_policy(value['overlap_policy']);required=validate_policy(value['required_overlap_policy'])
        previous_policy=validate_policy(value['previous_overlap_policy'])
        csv=value['csv'].encode('utf-8');previous=value['previous_csv'].encode('utf-8')
        if value['sha256']!=digest(csv):raise ValueError()
        identity=value['publication_id']
        if identity is not None and (not isinstance(identity,str) or not re.fullmatch(r'[0-9a-f]{32}',identity)):raise ValueError()
        if policy==LONGEST_PREFIX and identity is None:raise ValueError()
        if csv:parse_feed(csv,overlap_policy=policy)
        if previous:parse_feed(previous,overlap_policy=previous_policy)
        return Snapshot(csv,policy,required,previous,previous_policy,identity)
    except (KeyError,TypeError,ValueError,AttributeError,GeofeedError):
        raise GeofeedError('WordPress version-2 policy state is invalid') from None


def replace(client,csv,policy,expected,publication_id,operation='publish'):
    body={'protocol_version':2,'csv':csv.decode('utf-8'),'overlap_policy':policy,'operation':operation,
          'expected_sha256':digest(expected.csv),'expected_overlap_policy':expected.policy,
          'expected_required_overlap_policy':expected.required,'expected_publication_id':expected.publication_id,
          'publication_id':publication_id}
    try:
        value=client.http.request(client.base.removesuffix('/v1')+'/v2/feed',headers=client.headers,body=body,
                                  method='PUT' if csv else 'DELETE')
    except GeofeedError as exc:
        if re.match(r'HTTP 413\b',str(exc)):
            raise GeofeedError('WordPress upload refused (HTTP 413). Check request-body limits; no retry was made') from None
        if re.match(r'HTTP 503\b',str(exc)):
            raise GeofeedError('WordPress write unavailable (HTTP 503). Check server/database logs and max_allowed_packet; no retry was made') from None
        raise
    if (not isinstance(value,dict) or type(value.get('protocol_version')) is not int or value['protocol_version']!=2
            or value.get('sha256')!=digest(csv) or value.get('overlap_policy')!=policy
            or value.get('publication_id')!=publication_id):
        raise GeofeedError('WordPress did not confirm exact candidate bytes, policy and publication ID')


def matches(snapshot,csv,policy,identity):
    return snapshot.csv==csv and snapshot.policy==policy and snapshot.publication_id==identity


def restore(client,before,current):
    identity=secrets.token_hex(16)
    try:
        client.replace_policy(before.csv,before.policy,current,identity,'restore')
    except GeofeedError:
        # A lost restore reply can also have committed. Inspect once; do not retry.
        observed=client.policy_state()
        if not matches(observed,before.csv,before.policy,identity):raise
    if client.read_public(overlap_policy=before.policy)!=before.csv:
        raise GeofeedError('Restored WordPress public bytes differ')
    restored=client.policy_state()
    if (not matches(restored,before.csv,before.policy,identity) or restored.previous!=current.csv
            or restored.previous_policy!=current.policy):
        raise GeofeedError('Restored WordPress policy state differs')


def publish(client,csv,state_dir,max_removed_fraction,max_relocated_fraction,*,desired=LONGEST_PREFIX):
    from .publish import atomic_write
    if not callable(getattr(client,'policy_state',None)):
        raise GeofeedError('Selected WordPress client lacks the version-2 policy protocol')
    before=client.policy_state()
    validate_policy(desired)
    if before.required!=desired:
        raise GeofeedError(f'WordPress supports policy negotiation but is configured for {before.required}; configure the paired staging policy before requesting {desired}')
    change_guard(before.csv,csv,max_removed_fraction,max_relocated_fraction=max_relocated_fraction,
                 overlap_policy=desired,old_overlap_policy=before.policy)
    if client.read_public(overlap_policy=before.policy)!=before.csv:
        raise GeofeedError('WordPress stored/public bytes differ; no policy write attempted')
    if before.csv==csv and before.policy==desired:
        if client.policy_state()!=before:raise GeofeedError('WordPress feed or policy changed during unchanged verification; no write attempted')
        return {'changed':False,'sha256':digest(csv),'url':client.public_url,'overlap_policy':desired,
                'verification':'authenticated-and-public-policy','recovery_backup_changed':False}
    directory=Path(state_dir);candidate_id=secrets.token_hex(16)
    metadata={'schema_version':2,'url':client.public_url,'candidate_sha256':digest(csv),'candidate_publication_id':candidate_id,
              'candidate_policy':desired,
              'before_sha256':digest(before.csv),'before_policy':before.policy,'before_publication_id':before.publication_id,
              'before_required_policy':before.required}
    atomic_write(directory/'before.csv',before.csv)
    atomic_write(directory/'before-policy.json',json.dumps(metadata,sort_keys=True).encode())
    try:
        client.replace_policy(csv,desired,before,candidate_id)
        if client.read_public(overlap_policy=desired)!=csv:raise GeofeedError('Public read-back differs from generated feed')
        observed=client.policy_state()
        if (not matches(observed,csv,desired,candidate_id) or observed.required!=before.required
                or observed.previous!=before.csv or observed.previous_policy!=before.policy):
            raise GeofeedError('WordPress policy, history or publisher changed after public read-back')
    except GeofeedError as exc:
        try:
            observed=client.policy_state()
            if matches(observed,csv,desired,candidate_id):
                if observed.previous!=before.csv or observed.previous_policy!=before.policy:
                    raise GeofeedError('WordPress recovery baseline changed; refusing restore')
                restore(client,before,observed)
            elif matches(observed,before.csv,before.policy,before.publication_id):
                if client.read_public(overlap_policy=before.policy)!=before.csv:raise GeofeedError('Previous public delivery could not be verified')
            else:raise GeofeedError('Another WordPress publisher owns the feed; refusing restore')
        except GeofeedError as recovery:
            raise GeofeedError(f'Publish failed: {exc}. Recovery needs attention: {recovery}') from None
        raise GeofeedError(f'Publish failed: {exc}. Previous feed and policy retained/restored') from None
    atomic_write(directory/'last-good.csv',csv)
    return {'changed':True,'sha256':digest(csv),'url':client.public_url,'overlap_policy':desired,
            'verification':'authenticated-and-public-policy','recovery_backup_changed':True}


def recover(client,state_dir,expected_hash):
    from .local_output import read_output
    directory=Path(state_dir)
    try:
        value=json.loads(read_output(directory/'before-policy.json',8192).data)
        csv=read_output(directory/'before.csv',1_000_000).data
        if (set(value)!={'schema_version','url','candidate_sha256','candidate_publication_id','candidate_policy','before_sha256',
                        'before_policy','before_publication_id','before_required_policy'}
                or type(value['schema_version']) is not int or value['schema_version']!=2
                or value['url']!=client.public_url or value['candidate_sha256']!=expected_hash
                or value['before_sha256']!=digest(csv)
                or not re.fullmatch(r'[0-9a-f]{32}',value['candidate_publication_id'])):raise ValueError()
        policy=validate_policy(value['before_policy']);required=validate_policy(value['before_required_policy'])
        candidate_policy=validate_policy(value['candidate_policy'])
        old_id=value['before_publication_id']
        if old_id is not None and (not isinstance(old_id,str) or not re.fullmatch(r'[0-9a-f]{32}',old_id)):raise ValueError()
        if csv:parse_feed(csv,overlap_policy=policy)
        before=Snapshot(csv,policy,required,b'',REJECT,value['before_publication_id'])
    except (ValueError,TypeError,KeyError,GeofeedError):
        raise GeofeedError('WordPress private recovery baseline is invalid; no write attempted') from None
    current=client.policy_state()
    if (digest(current.csv)!=expected_hash or current.policy!=candidate_policy
            or current.publication_id!=value['candidate_publication_id']
            or current.previous!=csv or current.previous_policy!=policy):
        raise GeofeedError('WordPress candidate or recovery baseline changed; refusing restore')
    restore(client,before,current)
    return {'recovered':True,'sha256':digest(csv),'url':client.public_url,'overlap_policy':policy}


def configure(client,desired,expected_hash):
    """Administrator-only CAS policy switch, preserving current data and history."""
    validate_policy(desired)
    before=client.policy_state()
    if digest(before.csv)!=expected_hash:raise GeofeedError('Policy configuration hash does not match current feed; no write attempted')
    if client.read_public(overlap_policy=before.policy)!=before.csv:
        raise GeofeedError('Policy configuration requires matching stored/public bytes; no write attempted')
    if before.required==desired and before.publication_id is not None:
        if client.policy_state()!=before:raise GeofeedError('Policy changed during unchanged configuration verification; no write attempted')
        return {'configured_policy':True,'changed':False,'required_overlap_policy':desired,'sha256':digest(before.csv),'url':client.public_url}
    identity=secrets.token_hex(16)
    try:
        client.configure_policy(desired,before,identity)
    except GeofeedError as exc:
        observed=client.policy_state()
        if not matches(observed,before.csv,before.policy,identity) or observed.required!=desired:
            raise GeofeedError(f'Policy configuration failed or changed concurrently ({exc}); state inspected, no retry was made') from None
    after=client.policy_state()
    if (not matches(after,before.csv,before.policy,identity) or after.required!=desired
            or after.previous!=before.previous or after.previous_policy!=before.previous_policy
            or client.read_public(overlap_policy=before.policy)!=before.csv):
        raise GeofeedError('Policy configuration read-back differs; inspect before continuing')
    return {'configured_policy':True,'changed':True,'required_overlap_policy':desired,'sha256':digest(before.csv),'url':client.public_url}


def configure_request(client,policy,expected,identity):
    body={'protocol_version':2,'required_overlap_policy':policy,'expected_sha256':digest(expected.csv),
          'expected_overlap_policy':expected.policy,'expected_required_overlap_policy':expected.required,
          'expected_publication_id':expected.publication_id,'publication_id':identity}
    try:
        value=client.http.request(client.base.removesuffix('/v1')+'/v2/policy',headers=client.headers,body=body,method='PUT')
    except GeofeedError as exc:
        if re.match(r'HTTP (401|403)\b',str(exc)):
            raise GeofeedError('WordPress policy administration refused; use the separate administrator account with manage_options over HTTPS') from None
        raise
    if (not isinstance(value,dict) or type(value.get('protocol_version')) is not int or value['protocol_version']!=2
            or value.get('sha256')!=digest(expected.csv) or value.get('required_overlap_policy')!=policy
            or value.get('publication_id')!=identity):
        raise GeofeedError('WordPress did not confirm the exact policy switch; inspect state before retrying')
