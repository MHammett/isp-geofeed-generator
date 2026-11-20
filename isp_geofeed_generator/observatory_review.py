"""Bounded operator-entered notes, never an observatory API or health verdict."""
from datetime import date, datetime, timezone
import json
import re

from .client import GeofeedError
from .feed import digest
from .local_output import read_output
from .registry_check import _invalid_constant, _unique_json, feed_url

MAX_BYTES = 16_384
DATASETS = ('reference', 'retrieval', 'content', 'coverage')
STATES = ('finding', 'no_finding', 'not_measured')


def read_review(path, expected_url, *, now=None):
    """Validate manual notes without changing the local comparison or exit status."""
    current = now or datetime.now(timezone.utc)
    try:
        saved = read_output(path, MAX_BYTES)
        if saved.identity is None:
            raise ValueError()
        source = json.loads(saved.data, object_pairs_hook=_unique_json, parse_constant=_invalid_constant)
        if (not isinstance(source, dict)
                or set(source) != {'schema_version', 'source', 'feed_url', 'reviewed_at', 'datasets'}
                or type(source['schema_version']) is not int or source['schema_version'] != 1
                or source['source'] != 'geoflaw'
                or not feed_url(expected_url) or source['feed_url'] != expected_url):
            raise ValueError()
        stamp = source['reviewed_at']
        if (not isinstance(stamp, str) or not re.fullmatch(
                r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|\+00:00)', stamp)):
            raise ValueError()
        reviewed = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        if reviewed > current:
            raise ValueError()
        datasets = source['datasets']
        if not isinstance(datasets, dict) or set(datasets) != set(DATASETS):
            raise ValueError()
        result = {}
        for name, row in sorted(datasets.items()):
            if (not isinstance(row, dict) or set(row) != {'status', 'observed_on'}
                    or row['status'] not in STATES):
                raise ValueError()
            observed = row['observed_on']
            if row['status'] == 'not_measured':
                if observed is not None:
                    raise ValueError()
                age = None
            else:
                if not isinstance(observed, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', observed):
                    raise ValueError()
                day = date.fromisoformat(observed)
                if day > reviewed.date():
                    raise ValueError()
                age = (current.date() - day).days
            result[name] = {'status': row['status'], 'dataset_observed_on': observed,
                            'dataset_age_days': age}
        return {'source': 'geoflaw', 'source_url': 'https://geoflaw.cmand.org/',
                'input_kind': 'operator_entered_review', 'input_sha256': digest(saved.data),
                'reviewed_at': stamp, 'review_age_seconds': int((current - reviewed).total_seconds()),
                'datasets': result, 'review_authenticity': 'not_measured',
                'dataset_completeness': 'not_measured', 'current_public_feed': 'not_measured',
                'candidate_content_match': 'not_measured', 'registry_authority': 'not_measured',
                'provider_ingestion': 'not_measured', 'publication_gate': False}
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError, GeofeedError):
        raise GeofeedError('Observatory review needs a bounded regular file with the exact feed URL, '
                           'complete version-1 manual review fields and valid dated dataset states; '
                           'no partial report made') from None
