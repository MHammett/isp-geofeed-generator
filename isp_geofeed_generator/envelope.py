"""Policy marker for nested CSV. Old strict clients refuse the comment line."""
import hashlib
import re
from .client import GeofeedError
from .overlap import REJECT, LONGEST_PREFIX, validate_policy

PREFIX = b'# isp-geofeed-generator v2 overlap_policy=longest_prefix body_sha256='


def wrap_csv(body):
    return PREFIX + hashlib.sha256(body).hexdigest().encode('ascii') + b'\r\n' + body


def csv_body(value, policy):
    validate_policy(policy)
    if policy == REJECT:
        return value
    header, separator, body = value.partition(b'\r\n')
    if (not separator or not header.startswith(PREFIX)
            or not re.fullmatch(rb'[0-9a-f]{64}', header[len(PREFIX):])
            or header[len(PREFIX):].decode() != hashlib.sha256(body).hexdigest()
            or not body.endswith(b'\r\n') or b'\n' in body.replace(b'\r\n', b'')):
        raise GeofeedError('Nested CSV policy marker is missing or does not match its exact body')
    return body
