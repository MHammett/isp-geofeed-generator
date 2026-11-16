"""Pinned ISO membership data; no runtime network, aliases or fuzzy matching."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from .client import GeofeedError

DATA_HASHES = {
    'iso3166-1.json': 'f01b812b57fba9f31ff621bf33e7c7570a01964dbeb5be2167e94decf538c89f',
    'iso3166-2.json': '78c90ef7fc25b5c2631aac5f089bc9ff6ec22c025c05b6ddbc087a1f1be2e46a',
}


def load_tables(folder):
    try:
        documents = {}
        for name, expected in DATA_HASHES.items():
            with (Path(folder)/name).open('rb') as stream:
                data = stream.read(2_000_001)
            if len(data) > 2_000_000 or hashlib.sha256(data).hexdigest() != expected:
                raise ValueError()
            documents[name] = json.loads(data)
        countries = frozenset(row['alpha_2'] for row in documents['iso3166-1.json']['3166-1'])
        regions = frozenset(row['code'] for row in documents['iso3166-2.json']['3166-2'])
        if len(countries) != 249 or len(regions) != 5046 or any(code.split('-')[0] not in countries for code in regions):
            raise ValueError()
        return countries, regions
    except (OSError, ValueError, KeyError, TypeError):
        raise GeofeedError('ISO code data is missing or invalid; reinstall the reviewed package with its data files') from None


@lru_cache(maxsize=1)
def code_tables():
    return load_tables(Path(__file__).parent/'iso_data')


def valid_country(value):
    return value in code_tables()[0]


def valid_region(value):
    return value in code_tables()[1]
