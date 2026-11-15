"""Required input union, scoped credentials and actual CLI failure controls."""
import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import yaml
from isp_geofeed_generator.cli import main, load_config
from isp_geofeed_generator.credentials import CredentialStore, InputCredentialStore
from isp_geofeed_generator.adapters import SOURCES, source_url
from isp_geofeed_generator.contracts import SourceAdapter
from isp_geofeed_generator.client import GeofeedError
from bogon_fixture import policy
from test_sources import page
from test_sonar_subnets import SUBNET, SITE


class API:
    """Documented synthetic Sonar and NetBox responses, including API failures."""
    def __init__(self):
        self.calls = []; self.failure = None
        self.subnet = dict(SUBNET)
        self.prefix = {'id': 101, 'prefix': '11.22.34.0/24', 'scope_type': 'dcim.site', 'scope_id': 11,
                       'status': {'value': 'active'}, 'vrf': None, 'tags': []}
        self.netbox_site = {'id': 11, 'name': 'Infrastructure facility', 'custom_fields': {
            'geofeed_country': 'US', 'geofeed_region': 'US-CA', 'geofeed_city': 'Infrastructure City'}}

    def request(self, url, **kwargs):
        self.calls.append((url, copy.deepcopy(kwargs)))
        if url.startswith('https://customers.example.net/'):
            assert kwargs['headers']['Authorization'] == 'Bearer customer-secret'
            query = kwargs['body']['query']
            root = next(root for root in ('subnets', 'network_sites') if ' { '+root+'(' in query)
            rows = [self.subnet] if root == 'subnets' else [SITE]
            return {'data': {root: {'entities': copy.deepcopy(rows), 'page_info': {'page': 1, 'total_pages': 1, 'total_count': len(rows)}}}}
        assert url.startswith('https://infra.example.net/'), url
        assert kwargs['headers']['Authorization'] == 'Token infra-secret'
        if self.failure == 'auth': raise GeofeedError('HTTP 403; no retry was made')
        if '/ipam/prefixes/' in url:
            if self.failure == 'empty': return page([])
            if self.failure == 'missing': return page([{**self.prefix, 'id': 999}])
            if self.failure == 'paging': return page([self.prefix], 2)
            return page([self.prefix])
        if '/ipam/ip-ranges/' in url: return page([])
        if '/dcim/sites/' in url: return page([self.netbox_site])
        raise AssertionError('Unexpected endpoint')


def config(root):
    return {'inputs': {
        'customers': {'url': 'https://customers.example.net',
                      'source': {'type': 'sonar', 'pool_ids': [], 'subnet_ids': ['101']},
                      'credentials': {'SONAR_API_TOKEN': 'env:EXT_CUSTOMER_SONAR'},
                      'pool_sites': {'subnet:101': '11'}},
        'infrastructure': {'url': 'https://infra.example.net',
                           'source': {'type': 'netbox', 'prefix_ids': ['101']},
                           'credentials': {'NETBOX_API_TOKEN': 'env:EXT_INFRA_NETBOX'}}},
        'allowed_prefixes': ['11.22.0.0/16', '2001:4860::/32', '4000::/3'],
        'state_dir': str(root/'state'), 'publish': {'type': 'file', 'path': str(root/'public.csv')}}


class InputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.config = config(self.root); self.path = self.root/'config.yaml'
        self.api = API()
        environment = {'EXT_CUSTOMER_SONAR': 'customer-secret', 'EXT_INFRA_NETBOX': 'infra-secret',
                       'SONAR_URL': 'https://wrong.example.net', 'NETBOX_URL': 'https://wrong.example.net',
                       'SONAR_API_TOKEN': 'wrong-secret', 'NETBOX_API_TOKEN': 'wrong-secret'}
        self.patchers = [patch.dict('os.environ', environment), patch('isp_geofeed_generator.client.JsonHTTP.request', side_effect=self.api.request),
                         patch('isp_geofeed_generator.cli.load_policy', side_effect=lambda c: policy())]
        for item in self.patchers: item.start(); self.addCleanup(item.stop)

    def run_cli(self, command, **extra):
        self.path.write_text(yaml.safe_dump(self.config), encoding='utf-8')
        error = io.StringIO(); output = io.StringIO()
        with contextlib.redirect_stderr(error), contextlib.redirect_stdout(output):
            result = main([command, '--config', str(self.path), *sum(([key, value] for key, value in extra.items()), [])])
        return result, error.getvalue(), output.getvalue()

    def test_union_publishes_sonar_and_netbox_with_independent_ids_and_locations(self):
        candidate = self.root/'candidate.csv'
        self.assertEqual(self.run_cli('generate', **{'--output': str(candidate)})[0], 0)
        self.assertEqual(self.run_cli('publish')[0], 0)
        data = (self.root/'public.csv').read_bytes()
        self.assertEqual(candidate.read_bytes(), data)
        self.assertIn(b'11.22.34.0/24,US,US-CA,Infrastructure City,', data)
        self.assertIn(b'2001:4860:1234::/48,US,US-IL,Example City,', data)
        self.assertNotIn(b'customers', data); self.assertNotIn(b'secret', data)
        saved = json.loads((self.root/'state/status.json').read_text())['data']
        self.assertEqual(set(saved['inputs']), {'customers', 'infrastructure'})
        self.assertEqual({row['input'] for row in saved['pools']}, {'customers', 'infrastructure'})
        self.assertEqual({row['site_id'] for row in saved['pools']}, {'11'})
        self.assertTrue(all(row['cidrs'] and row['source_record_id'] for row in saved['pools']))
        self.assertTrue(all(item['read_started_at'] <= item['read_completed_at'] for item in saved['inputs'].values()))
        self.assertFalse(json.loads(self.run_cli('publish')[2])['changed'])

    def test_discovery_keeps_separate_inventories_and_read_boundaries(self):
        code, error, output = self.run_cli('discover')
        self.assertEqual(code, 0, error)
        document = json.loads(output)
        self.assertEqual(set(document['inputs']), {'customers', 'infrastructure'})
        self.assertEqual(document['inputs']['customers']['snapshot']['pools'][0]['id'], 'subnet:101')
        self.assertEqual(document['inputs']['infrastructure']['snapshot']['pools'][0]['id'], 'prefix:101')
        self.assertNotIn('secret', output)

    def test_required_source_auth_paging_empty_missing_and_scope_failures_keep_prior_bytes(self):
        self.assertEqual(self.run_cli('publish')[0], 0)
        before = (self.root/'public.csv').read_bytes()
        for failure in ('auth', 'paging', 'empty', 'missing', 'scope'):
            with self.subTest(failure=failure):
                self.api.failure = failure
                self.api.prefix['scope_id'] = None if failure == 'scope' else 11
                code, error, _ = self.run_cli('publish')
                self.assertEqual(code, 1, error)
                self.assertIn('infrastructure', error)
                self.assertEqual((self.root/'public.csv').read_bytes(), before)
                self.assertFalse(json.loads((self.root/'state/status.json').read_text())['data']['healthy'])

    def test_duplicate_overlap_and_conflicting_locations_have_no_implicit_precedence(self):
        self.assertEqual(self.run_cli('publish')[0], 0)
        before = (self.root/'public.csv').read_bytes()
        for prefix in (SUBNET['subnet'], '2001:4860:1234::/49'):
            self.api.prefix['prefix'] = prefix
            code, error, _ = self.run_cli('publish')
            self.assertEqual(code, 1); self.assertIn('conflicting locations', error)
            self.assertIn('customers/subnet:101', error); self.assertIn('infrastructure/prefix:101', error)
            self.assertEqual((self.root/'public.csv').read_bytes(), before)
        self.api.netbox_site['custom_fields'].update(geofeed_region='US-IL', geofeed_city='Example City')
        code, error, _ = self.run_cli('publish')
        self.assertEqual(code, 1); self.assertIn('duplicate/overlapping coverage', error)

    def test_bogons_and_loss_of_one_source_address_family_are_guarded(self):
        self.assertEqual(self.run_cli('publish')[0], 0)
        before = (self.root/'public.csv').read_bytes()
        self.api.subnet['subnet'] = '4000::/48'
        self.assertIn('bogon', self.run_cli('publish')[1])
        self.assertEqual((self.root/'public.csv').read_bytes(), before)
        del self.config['inputs']['customers']
        code, error, _ = self.run_cli('publish')
        self.assertEqual(code, 1); self.assertIn('IPv6 feed removal', error)
        self.assertEqual((self.root/'public.csv').read_bytes(), before)

    def test_per_input_mappings_are_not_shared_or_taken_from_global_config(self):
        self.config['inputs']['infrastructure']['pool_sites'] = {'prefix:101': '11'}
        self.config['inputs']['infrastructure']['site_locations'] = {'11': {'city': 'Only Infrastructure'}}
        self.assertEqual(self.run_cli('publish')[0], 0)
        data = (self.root/'public.csv').read_text()
        self.assertIn('Example City', data); self.assertIn('Only Infrastructure', data)
        self.config['pool_sites'] = {'subnet:101': '11'}
        code, error, _ = self.run_cli('generate')
        self.assertEqual(code, 1); self.assertIn('inside each named input', error)

    def test_literal_missing_or_cross_name_credentials_do_not_fall_back(self):
        entry = self.config['inputs']['customers']
        for selectors in ({}, {'SONAR_API_TOKEN': 'literal-secret'}, {'SONAR_API_TOKEN': 'env:NETBOX_API_TOKEN'}):
            entry['credentials'] = selectors
            code, error, _ = self.run_cli('publish')
            self.assertEqual(code, 1); self.assertNotIn('literal-secret', error)
            self.assertFalse((self.root/'public.csv').exists())

    def test_secret_redaction_is_shared_across_sources_and_failure_status(self):
        def failing(url, **kwargs):
            if 'infra.example.net' in url: raise GeofeedError('customer-secret and infra-secret')
            return self.api.request(url, **kwargs)
        with patch('isp_geofeed_generator.client.JsonHTTP.request', side_effect=failing):
            code, error, _ = self.run_cli('publish')
        self.assertEqual(code, 1); self.assertIn('[REDACTED]', error)
        status = (self.root/'state/status.json').read_text()
        for secret in ('customer-secret', 'infra-secret'):
            self.assertNotIn(secret, error); self.assertNotIn(secret, status)

    def test_no_url_fallback_or_global_environment_mutation(self):
        del self.config['inputs']['customers']['url']
        code, error, _ = self.run_cli('publish')
        self.assertEqual(code, 1); self.assertFalse(self.api.calls)
        import os
        self.assertEqual(os.environ['SONAR_URL'], 'https://wrong.example.net')

    def test_unknown_optional_failure_and_mixed_source_settings_are_rejected(self):
        for changes in ({'source': {'type': 'sonar'}}, {'inputs': []}, {'inputs': {}}, {'inputs': {'bad/name': {}}}):
            old = self.config; self.config = {**old, **changes}
            self.assertEqual(self.run_cli('generate')[0], 1); self.config = old
        self.config['inputs']['customers']['optional'] = True
        self.assertEqual(self.run_cli('generate')[0], 1)

    def test_duplicate_yaml_input_and_source_policy_keys_cannot_drop_data(self):
        for text in ('inputs:\n  customers: {}\n  customers: {}\n', 'source: {type: sonar, pool_ids: [], pool_ids: ["101"]}\n'):
            self.path.write_text(text)
            with self.assertRaisesRegex(GeofeedError, 'Cannot read YAML'): load_config(self.path)

    def test_multiple_instances_of_same_adapter_use_separate_credentials_and_urls(self):
        parent = CredentialStore(environ={'EXT_FIRST': 'first-secret', 'EXT_SECOND': 'second-secret', 'SONAR_URL': 'https://wrong.example.net'})
        stores = [InputCredentialStore({'SONAR_API_TOKEN': 'env:EXT_'+name}, parent, url)
                  for name, url in (('FIRST', 'https://first.example.net'), ('SECOND', 'https://second.example.net'))]
        clients = [SOURCES['sonar'].create({'pool_ids': [], 'subnet_ids': ['101']}, store) for store in stores]
        self.assertEqual([c.url for c in clients], ['https://first.example.net/api/graphql', 'https://second.example.net/api/graphql'])
        self.assertEqual([c.headers['Authorization'] for c in clients], ['Bearer first-secret', 'Bearer second-secret'])
        self.assertEqual(parent.redact('first-secret second-secret'), '[REDACTED] [REDACTED]')

    def test_rich_output_fields_apply_to_every_input_without_invented_values(self):
        self.config['publish'] = {'type': 'json', 'path': str(self.root/'locations.json'),
                                  'location_fields': ['latitude', 'longitude'], 'allow_initial': True}
        for entry in self.config['inputs'].values():
            entry['site_locations'] = {'11': {'latitude': 41.9, 'longitude': -88.7}}
        self.assertEqual(self.run_cli('publish')[0], 0)
        before = (self.root/'locations.json').read_bytes()
        self.assertNotIn(b'city', before)
        self.assertEqual(len(json.loads(before)['records']), 2)
        del self.config['inputs']['infrastructure']['site_locations']['11']['longitude']
        code, error, _ = self.run_cli('publish')
        self.assertEqual(code, 1); self.assertIn('infrastructure', error)
        self.assertEqual((self.root/'locations.json').read_bytes(), before)

    def test_external_source_initial_gate_and_unexpected_failure_are_per_input(self):
        from test_feed import snapshot
        class Source:
            def snapshot(self): return snapshot()
            def for_publication(self, data): return data
        self.config['inputs'] = {'local': {'source': {'type': 'fixture'}, 'pool_sites': {'101': '11'}}}
        with patch.dict(SOURCES, fixture=SourceAdapter(lambda s, c: Source())):
            self.assertEqual(self.run_cli('generate')[0], 0)
            self.assertIn('Input local', self.run_cli('publish')[1])
            self.config['inputs']['local']['source']['allow_initial'] = True
            self.assertEqual(self.run_cli('publish')[0], 0)
        def broken(s, c): raise RuntimeError('private upstream body')
        with patch.dict(SOURCES, fixture=SourceAdapter(broken)):
            code, error, _ = self.run_cli('publish')
            self.assertEqual(code, 1); self.assertIn('not measured', error); self.assertNotIn('private', error)
