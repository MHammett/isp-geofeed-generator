import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs
from isp_geofeed_generator.adapters import SOURCES
from isp_geofeed_generator.cli import main
from isp_geofeed_generator.client import GeofeedError, JsonHTTP
from isp_geofeed_generator.feed import build, parse_feed
from isp_geofeed_generator.powercode import Powercode
from isp_geofeed_generator.gaiia import Gaiia, SITES_QUERY, BLOCKS_QUERY, normalized_id
from test_sources import HTTP

LOCATION = {'country': 'US', 'region': 'US-IL', 'city': 'Example City'}


def connection(rows, count=None, cursor=None, more=False):
    return {'nodes': rows, 'totalCount': len(rows) if count is None else count,
            'pageInfo': {'hasNextPage': more, 'endCursor': cursor}}


def site(identifier='site-native-1', archived=None):
    return {'id': identifier, 'name': 'Example facility', 'archivedAt': archived,
            'address': {'id': 'address-native', 'country': 'US', 'region': 'IL', 'locality': 'Example City'}}


def block(identifier='block-native-1', owner='site-native-1', value='11.22.33.0/24'):
    return {'id': identifier, 'networkSiteId': owner, 'block': value}


def site_reply(rows): return {'data': {'networkSites': connection(rows)}}


def block_reply(rows, owner='site-native-1', archived=None, **kwargs):
    return {'data': {'networkSite': {'id': owner, 'archivedAt': archived, 'ipBlocks': connection(rows, **kwargs)}}}


class PowercodeTests(unittest.TestCase):
    def source(self, rows=None, settings=None):
        http = HTTP([{'statusCode': 0, 'ranges': rows if rows is not None else [
            {'addressRangeID': '89', 'name': 'private descriptive text', 'range': '11.22.33.2 - 11.22.33.126', 'freeIPs': 5}]}])
        return Powercode('https://billing.example.net:444', 'fake-api-key', settings or {'range_ids': ['89'], 'facility_ids': ['pop-1']}, http), http

    def test_documented_read_action_and_exact_coverage(self):
        source, http = self.source()
        candidate = source.for_publication(source.snapshot())
        csv, _ = build(candidate, {'allowed_prefixes': ['11.22.33.0/24'], 'pool_sites': {'range:89': 'pop-1'}, 'site_locations': {'pop-1': LOCATION}})
        nets = parse_feed(csv)
        self.assertEqual(sum(n.num_addresses for n in nets), 125)
        self.assertEqual(str(nets[0].network_address), '11.22.33.2')
        self.assertEqual(str(nets[-1].broadcast_address), '11.22.33.126')
        url, request = http.calls[0]
        self.assertEqual(url, 'https://billing.example.net:444/api/1/index.php')
        self.assertEqual(request['method'], 'POST')
        self.assertEqual(request['form'], {'apiKey': 'fake-api-key', 'action': 'readAddressRanges'})
        self.assertNotIn('fake-api-key', json.dumps(candidate))
        self.assertNotIn('private descriptive text', csv.decode())
        self.assertEqual(candidate['pools'][0]['parent_source'], 'derived_envelope')

    def test_no_native_site_is_invented_from_names(self):
        source, _ = self.source()
        snapshot = source.for_publication(source.snapshot())
        with self.assertRaisesRegex(GeofeedError, 'no pool_sites'):
            build(snapshot, {'allowed_prefixes': ['11.22.33.0/24']})

    def test_empty_failed_malformed_duplicate_and_reversed_reads_fail(self):
        replies = [{'statusCode': 1, 'message': 'private error body', 'ranges': []},
                   {'statusCode': True, 'ranges': []}, {'ranges': []}, {'statusCode': 0, 'ranges': []},
                   {'statusCode': 0, 'ranges': [{'addressRangeID': '1', 'range': 'private bad value'}]},
                   {'statusCode': 0, 'ranges': [{'addressRangeID': '1', 'range': '11.0.0.5-11.0.0.2'}]},
                   {'statusCode': 0, 'ranges': [{'addressRangeID': '1', 'range': '11.0.0.1-::1'}]},
                   {'statusCode': 0, 'ranges': [{'addressRangeID': '1', 'range': '11.0.0.1-11.0.0.2'}] * 2}]
        for reply in replies:
            with self.subTest(reply=reply), self.assertRaises(GeofeedError) as result:
                Powercode('https://example.net', 'key', http=HTTP([reply])).snapshot()
            self.assertNotIn('private', str(result.exception))

    def test_explicit_selection_missing_ids_and_bad_settings(self):
        for settings in ({}, {'range_ids': ['99']}):
            source, _ = self.source(settings=settings or {'facility_ids': []})
            with self.assertRaises(GeofeedError): source.for_publication(source.snapshot())
        for settings in ({'range_ids': ['1', '1']}, {'facility_ids': '../path'}, {'facility_ids': ['bad\nvalue']}):
            with self.assertRaises(GeofeedError): Powercode('https://example.net', 'key', settings)

    def test_ipv6_returned_range_can_be_converted_without_claiming_live_coverage(self):
        source, _ = self.source(rows=[{'addressRangeID': '89', 'range': '2001:4860:1234::2 - 2001:4860:1234::e'}])
        snapshot = source.for_publication(source.snapshot())
        csv, _ = build(snapshot, {'allowed_prefixes': ['2001:4860:1234::/48'], 'pool_sites': {'range:89': 'pop-1'}, 'site_locations': {'pop-1': LOCATION}})
        self.assertEqual(sum(n.num_addresses for n in parse_feed(csv)), 13)

    def test_form_transport_encodes_credentials_in_body_only(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size): return b'{"statusCode":0,"ranges":[]}'
        http = JsonHTTP()
        with patch.object(http.opener, 'open', return_value=Response()) as opened:
            http.request('https://example.net/api', form={'apiKey': 'key+&=value', 'action': 'readAddressRanges'}, method='POST')
        request = opened.call_args.args[0]
        self.assertEqual(parse_qs(request.data.decode())['apiKey'], ['key+&=value'])
        self.assertEqual(request.get_header('Content-type'), 'application/x-www-form-urlencoded')
        self.assertNotIn('key+', request.full_url)
        with self.assertRaises(GeofeedError): http.request('https://example.net', body={}, form={})


class GaiiaTests(unittest.TestCase):
    def source(self, replies=None, settings=None):
        http = HTTP(replies or [site_reply([site()]), block_reply([block()])])
        return Gaiia('https://api.gaiia.com/api/v1', 'fake-gaiia-key', settings or {'site_ids': ['site-native-1']}, http), http

    def test_native_site_block_and_structured_address(self):
        source, http = self.source()
        snapshot = source.for_publication(source.snapshot())
        csv, _ = build(snapshot, {'allowed_prefixes': ['11.22.33.0/24']})
        self.assertEqual(csv, b'11.22.33.0/24,US,US-IL,Example City,\n')
        self.assertEqual(snapshot['pools'][0]['source_id'], 'block-native-1')
        self.assertEqual(snapshot['pools'][0]['site_id'], normalized_id('site', 'site-native-1'))
        for _, request in http.calls:
            self.assertEqual(request['headers']['X-Gaiia-Api-Key'], 'fake-gaiia-key')
            self.assertEqual(request['method'], 'POST')
            self.assertNotIn('line1', request['body']['query'])
            self.assertNotIn('postalCode', request['body']['query'])
            self.assertNotIn('mutation', request['body']['query'])
        self.assertNotIn('fake-gaiia-key', json.dumps(snapshot))

    def test_sites_and_each_blocks_connection_are_paged(self):
        first_site = {'data': {'networkSites': connection([site()], 2, 'site-cursor', True)}}
        last_site = {'data': {'networkSites': connection([site('site-native-2')], 2)}}
        replies = [first_site, last_site,
                   block_reply([block()], count=2, cursor='block-cursor', more=True),
                   block_reply([block('block-2', value='11.22.34.0/24')], count=2),
                   block_reply([block('block-3', owner='site-native-2', value='2001:4860:1234::/48')], owner='site-native-2')]
        source, http = self.source(replies, {'site_ids': ['site-native-1', 'site-native-2']})
        snapshot = source.for_publication(source.snapshot())
        csv, _ = build(snapshot, {'allowed_prefixes': ['11.22.0.0/16', '2001:4860:1234::/48']})
        self.assertEqual(len(csv.splitlines()), 3)
        variables = [call[1]['body']['variables'] for call in http.calls]
        self.assertEqual(variables[1]['after'], 'site-cursor')
        self.assertEqual(variables[3]['after'], 'block-cursor')
        self.assertIsNone(variables[4]['after'])

    def test_graphql_partial_errors_null_owner_and_malformed_cidr_fail(self):
        for replies in ([{'data': {'networkSites': connection([site()])}, 'errors': [{'message': 'private payload'}]}],
                        [site_reply([site()]), {'data': {'networkSite': None}}],
                        [site_reply([site()]), block_reply([block(value='11.22.33.1/24')])],
                        [site_reply([site()]), block_reply([block(owner='other-site')])]):
            source, _ = self.source(replies)
            with self.assertRaises(GeofeedError) as result: source.snapshot()
            self.assertNotIn('private payload', str(result.exception))

    def test_pagination_rejects_truncation_count_drift_duplicates_and_bad_cursors(self):
        fixtures = [
            [connection([{'id': '1'}], 2)],
            [connection([{'id': '1'}], 2, 'c', True), connection([{'id': '2'}], 3)],
            [connection([{'id': '1'}], 2, 'c', True), connection([{'id': '1'}], 2)],
            [connection([{'id': '1'}], 3, 'c', True), connection([{'id': '2'}], 3, 'c', True)],
            [connection([], 2, 'c', True)],
            [connection([{'id': '1'}], 1, 'c', True)],
            [{'nodes': [], 'totalCount': True, 'pageInfo': {'hasNextPage': False, 'endCursor': None}}],
        ]
        source, _ = self.source()
        for replies in fixtures:
            queue = list(replies)
            with self.subTest(replies=replies), self.assertRaises(GeofeedError): source.pages(lambda cursor: queue.pop(0), 'test connection')

    def test_explicit_selection_and_archive_rules(self):
        source = Gaiia('https://example.net', 'key', {}, HTTP([site_reply([site()]), block_reply([block()])]))
        with self.assertRaisesRegex(GeofeedError, 'Set source'): source.for_publication(source.snapshot())
        source, _ = self.source(settings={'block_ids': ['block-native-1']})
        self.assertEqual(len(source.for_publication(source.snapshot())['pools']), 1)
        for settings in ({'site_ids': ['missing']}, {'block_ids': ['missing']}):
            source, _ = self.source(settings=settings)
            with self.assertRaisesRegex(GeofeedError, 'missing or archived'): source.for_publication(source.snapshot())
        archived = '2026-01-01T00:00:00Z'
        source, _ = self.source([site_reply([site(archived=archived)]), block_reply([block()], archived=archived)])
        with self.assertRaisesRegex(GeofeedError, 'archived'): source.for_publication(source.snapshot())

    def test_conflicting_blocks_and_archive_change_fail(self):
        replies = [site_reply([site(), site('site-native-2')]), block_reply([block()]), block_reply([block(owner='site-native-2')], owner='site-native-2')]
        for case in (replies, [site_reply([site()]), block_reply([block()], archived='changed')]):
            source, _ = self.source(case)
            with self.assertRaises(GeofeedError): source.snapshot()

    def test_empty_site_inventory_and_selected_site_without_blocks_fail(self):
        source, _ = self.source([site_reply([])])
        with self.assertRaisesRegex(GeofeedError, 'not measured'): source.snapshot()
        source, _ = self.source([site_reply([site(), site('site-native-2')]), block_reply([]), block_reply([block(owner='site-native-2')], owner='site-native-2')])
        with self.assertRaisesRegex(GeofeedError, 'no IP blocks'): source.for_publication(source.snapshot())

    def test_unstructured_geography_needs_an_explicit_override(self):
        value = site(); value['address']['region'] = 'Illinois'
        source, _ = self.source([site_reply([value]), block_reply([block()])])
        snapshot = source.for_publication(source.snapshot())
        with self.assertRaisesRegex(GeofeedError, 'subdivision'): build(snapshot, {'allowed_prefixes': ['11.22.33.0/24']})
        csv, _ = build(snapshot, {'allowed_prefixes': ['11.22.33.0/24'], 'site_locations': {normalized_id('site', value['id']): LOCATION}})
        self.assertIn(b',US,US-IL,', csv)


class InitialSupportTests(unittest.TestCase):
    def test_gaiia_coordinates_are_requested_only_when_enabled(self):
        for enabled in (False, True):
            value = site(); value['address'].update(latitude=41.9, longitude=-88.7)
            http = HTTP([site_reply([value]), block_reply([block()])])
            source = Gaiia('https://example.net', 'key', {'site_ids': ['site-native-1'], 'include_coordinates': enabled}, http)
            result = source.snapshot()
            self.assertEqual('latitude' in http.calls[0][1]['body']['query'], enabled)
            self.assertEqual('latitude' in result['sites'][0]['addresses'][0], enabled)

    def test_initial_publication_needs_opt_in_and_does_not_touch_old_feed(self):
        for kind in ('powercode', 'gaiia'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp); cfg = directory/'config.yaml'; target = directory/'public.csv'
                target.write_bytes(b'unchanged feed sentinel')
                if kind == 'powercode':
                    source, _ = PowercodeTests().source()
                    settings = 'range_ids: ["89"], facility_ids: [pop-1]'
                    extra = 'pool_sites: {"range:89": pop-1}\nsite_locations: {pop-1: {country: US, region: US-IL, city: Example City}}\n'
                else:
                    source, _ = GaiiaTests().source()
                    settings = 'site_ids: [site-native-1]'; extra = ''
                content = f'source: {{type: {kind}, {settings}}}\nstate_dir: {directory.as_posix()}/state\nallowed_prefixes: [11.22.33.0/24]\npublish: {{type: file, path: {target.as_posix()}}}\n'+extra
                cfg.write_text(content)
                adapter = type(SOURCES[kind])(lambda s, c: source, initial=True, settings=SOURCES[kind].settings)
                with patch.dict(SOURCES, {kind: adapter}), contextlib.redirect_stderr(io.StringIO()) as output:
                    self.assertEqual(main(['publish', '--config', str(cfg)]), 1)
                self.assertIn('Initial adapter', output.getvalue())
                self.assertEqual(target.read_bytes(), b'unchanged feed sentinel')
