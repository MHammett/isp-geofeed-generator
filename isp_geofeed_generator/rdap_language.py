"""Exact declared-language selection, with no locale, prefix or URL fallback."""
import re

from .client import GeofeedError

MAX_TAG = 32
MAX_LANGUAGES = 20
_COMMON_TAG = re.compile(r'[a-z]{2,8}(?:-[a-z]{4})?(?:-(?:[a-z]{2}|[0-9]{3}))?', re.ASCII | re.IGNORECASE)


def language_tag(value):
    """A bounded BCP 47 subset, not registration or canonical-alias validation."""
    if not isinstance(value, str) or len(value) > MAX_TAG or _COMMON_TAG.fullmatch(value) is None:
        raise GeofeedError('RDAP language selection supports language[-Script][-REGION] tags only; unsupported or malformed tags are refused without fallback')
    return value.lower()


def select_language(links, requested):
    """All links have already passed common URL/context/media validation."""
    requested = language_tag(requested)
    seen, matches = set(), []
    for link in links:
        labels = link.get('hreflang')
        if isinstance(labels, str):
            labels = [labels]
        if not isinstance(labels, list) or not 1 <= len(labels) <= MAX_LANGUAGES:
            raise GeofeedError('RDAP language selection needs supported hreflang labels on every geofeed link; no comparison made')
        tags = [language_tag(label) for label in labels]
        if len(set(tags)) != len(tags) or seen.intersection(tags):
            raise GeofeedError('RDAP language labels are ambiguous or repeated; no comparison made')
        seen.update(tags)
        if requested in tags:
            matches.append(link)
    if not links:
        return None
    if len(matches) != 1:
        raise GeofeedError('RDAP has no unique exact match for the requested language; no fallback or comparison made')
    return matches[0]['href']
