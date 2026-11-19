import contextlib
import io
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import yaml

from isp_geofeed_generator.adapters import SOURCES
from isp_geofeed_generator.client import GeofeedError
from isp_geofeed_generator.cli import main
from isp_geofeed_generator.credentials import CredentialStore, InputCredentialStore
from isp_geofeed_generator.feed import build, parse_feed
from isp_geofeed_generator.openwisp import OpenWISP, validate_settings
from bogon_fixture import policy
from test_sources import HTTP

ORG = 'ab000000-0000-4000-8000-000000000001'
V4 = 'ab000000-0000-4000-8000-000000000004'
V6 = 'ab000000-0000-4000-8000-000000000006'
OTHER = 'ab000000-0000-4000-8000-000000000002'
PREFIXES = ['11.22.33.0/24', '2001:4860:1234::/126']
LOCATION = {'country': 'US', 'region': 'US-IL', 'city': 'Reviewed City'}


def row(identifier=V4, prefix=PREFIXES[0]):
    return {'id': identifier, 'organization': ORG, 'subnet': prefix,
            'name': 'PRIVATE name', 'description': 'PRIVATE description',
            'master_subnet': OTHER, 'custom_secret': 'PRIVATE secret',
            'links': [{'href': 'https://foreign.example/PRIVATE'}]}


def settings(ids=None):
    return {'organization_id': ORG, 'subnet_ids': [V4, V6] if ids is None else ids}


def locations(ids=(V4, V6)):
    return {'subnet:' + identifier: dict(LOCATION) for identifier in ids}


class OpenWISPTests(unittest.TestCase):
    def source(self, replies=None, ids=None):
        http = HTTP([row(), row(V6, PREFIXES[1])] if replies is None else replies)
        return OpenWISP('https://example.net/mounted/', 'synthetic-token', settings(ids), http), http

    def test_exact_dual_stack_selected_details_and_private_field_projection(self):
        source, http = self.source()
        snapshot = source.for_publication(source.snapshot())
        data, report = build(snapshot, {'allowed_prefixes': PREFIXES, 'site_locations': locations()})
        self.assertEqual([str(n) for n in parse_feed(data)], PREFIXES)
        self.assertEqual([n.num_addresses for n in parse_feed(data)], [256, 4])
        self.assertNotIn('PRIVATE', json.dumps(snapshot))
        self.assertNotIn('foreign', json.dumps(snapshot))
        self.assertEqual(len(http.calls), 2)
        for (url, args), identifier in zip(http.calls, (V4, V6)):
            self.assertEqual(url, 'https://example.net/mounted/api/v1/ipam/subnet/' + identifier + '/')
            self.assertEqual(args, {'headers': {'Authorization': 'Bearer synthetic-token'}, 'method': 'GET'})
        self.assertIn('not complete instance inventory', snapshot['selection_scope'])
        self.assertIn('no native facility join claimed', snapshot['site_resolution'])
        self.assertEqual(len(report), 2)

    def test_missing_wrong_or_global_organization_refuses_before_more_reads(self):
        for org in (None, OTHER, {}, False, ORG.upper()):
            bad = row(); bad['organization'] = org
            source, http = self.source([bad], [V4])
            with self.subTest(org=org), self.assertRaisesRegex(GeofeedError, 'configured organization'):
                source.snapshot()
            self.assertEqual(len(http.calls), 1)
        bad = row(); del bad['organization']
        source, _ = self.source([bad], [V4])
        with self.assertRaises(GeofeedError): source.snapshot()

    def test_detail_identity_envelope_and_late_failure_never_return_partial_inventory(self):
        for bad in (None, [], {'results': [row(V6, PREFIXES[1])]}, {},
                    row(OTHER), {**row(), 'id': False}, {**row(), 'id': V6.upper()}):
            source, http = self.source([row(), bad])
            with self.subTest(bad=bad), self.assertRaisesRegex(GeofeedError, 'no partial inventory'):
                source.snapshot()
            self.assertEqual(len(http.calls), 2)

    def test_noncanonical_invalid_or_missing_boundaries_do_not_echo_response_data(self):
        for value in (None, True, {}, 'PRIVATE', '11.22.33.1/24', '11.22.33.0',
                      '2001:4860:1234:0000::/126', '2001:4860:1234::1/126',
                      '2001:4860:1234::%PRIVATE/126', '1'*65):
            source, _ = self.source([{**row(), 'subnet': value}], [V4])
            with self.subTest(value=value):
                with self.assertRaisesRegex(GeofeedError, 'boundaries') as error:
                    source.snapshot()
                self.assertNotIn('PRIVATE', str(error.exception))

    def test_explicit_geography_needed_and_organization_or_parent_not_used(self):
        source, _ = self.source(); snapshot = source.snapshot()
        with self.assertRaises(GeofeedError): build(snapshot, {'allowed_prefixes': PREFIXES})
        for change in ({'country': 'XX'}, {'city': 'bad,city'}, {'country': 'CA'}, {'city': 'bad\ncity'}):
            overrides = locations(); overrides['subnet:' + V6].update(change)
            with self.subTest(change=change), self.assertRaises(GeofeedError):
                build(snapshot, {'allowed_prefixes': PREFIXES, 'site_locations': overrides})
        # Optional output coordinates use the common typed output contract.
        from isp_geofeed_generator.feed import build_records
        records, _ = build_records(snapshot, {'allowed_prefixes': PREFIXES, 'site_locations': {
            key: {**value, 'latitude': 41.8, 'longitude': -88.6} for key, value in locations().items()}},
            frozenset({'latitude', 'longitude'}))
        self.assertEqual(records[0]['location'], {'latitude': 41.8, 'longitude': -88.6})

    def test_selection_validation_precedes_http_and_is_bounded(self):
        bad_ids = (None, [], V4, [V4, V4], [False], [V4.upper()], [V4.replace('-', '')],
                   ['00000000-0000-0000-0000-000000000000'], ['../PRIVATE'], [V4]*257)
        for ids in bad_ids:
            http = Mock()
            with self.subTest(ids=ids), self.assertRaises(GeofeedError):
                OpenWISP('https://example.net', 'token', {'organization_id': ORG, 'subnet_ids': ids}, http)
            http.request.assert_not_called()
        for org in (None, '', False, ORG.upper()):
            with self.assertRaises(GeofeedError): validate_settings({**settings(), 'organization_id': org})

    def test_https_header_and_named_credential_scope(self):
        for url in ('http://example.net', 'https://key@example.net', 'https://example.net/?secret=x', 'https://example.net/#x'):
            with self.assertRaises(GeofeedError): OpenWISP(url, 'token', settings())
        for token in (None, '', False, 'bad\nheader', 'bad token', '\u00e9', 'a'*16385):
            with self.assertRaises(GeofeedError): OpenWISP('https://example.net', token, settings())
        credentials = Mock(); credentials.get.return_value = 'synthetic-token'
        with patch.dict('os.environ', {'OPENWISP_URL': 'https://example.net'}):
            SOURCES['openwisp'].create(settings(), credentials)
        self.assertEqual([c.args for c in credentials.get.call_args_list], [('OPENWISP_API_TOKEN',)])
        parent = CredentialStore(environ={'EXT_OPENWISP_TOKEN': 'synthetic-token'})
        named = InputCredentialStore({'OPENWISP_API_TOKEN': 'env:EXT_OPENWISP_TOKEN'}, parent, 'https://named.example.net')
        with patch.dict('os.environ', {'OPENWISP_URL': 'https://wrong.example'}):
            self.assertEqual(SOURCES['openwisp'].create(settings(), named).url, 'https://named.example.net')
        self.assertTrue(SOURCES['openwisp'].initial)

    def test_denial_timeout_and_late_error_make_no_retry(self):
        for failure in ('HTTP 403; no retry was made', 'Connection failed (TimeoutError); no retry was made'):
            for replies in ([GeofeedError(failure)], [row(), GeofeedError(failure)]):
                source, _ = self.source(); source.http = Mock(); source.http.request.side_effect = replies
                with self.assertRaisesRegex(GeofeedError, 'no retry'): source.snapshot()
                self.assertEqual(source.http.request.call_count, len(replies))

    def test_for_publication_checks_selected_completeness(self):
        source, _ = self.source(); snapshot = source.snapshot()
        for pools in ([], snapshot['pools'][:1], snapshot['pools'][::-1], snapshot['pools']*2):
            with self.assertRaises(GeofeedError): source.for_publication({**snapshot, 'pools': pools})

    def test_combines_with_netbox_without_source_or_credential_precedence(self):
        from isp_geofeed_generator.inputs import read_inputs, combine_inputs
        from isp_geofeed_generator.netbox import NetBox
        from test_sources import page, SITE, PREFIX
        source, _ = self.source([row(V6, PREFIXES[1])], [V6])
        netbox_http = HTTP([page([PREFIX]), page([]), page([SITE])])
        netbox = NetBox('https://netbox.example', 'netbox-token', {'prefix_ids': ['1']}, netbox_http)
        config = {'inputs': {'customers': {'source': {'type': 'openwisp', **settings([V6])},
                      'url': 'https://openwisp.example', 'credentials': {'OPENWISP_API_TOKEN': 'env:EXT_OPENWISP_TOKEN'},
                      'site_locations': locations([V6])},
                    'infra': {'source': {'type': 'netbox', 'prefix_ids': ['1']},
                      'url': 'https://netbox.example', 'credentials': {'NETBOX_API_TOKEN': 'env:EXT_NETBOX_TOKEN'}}},
                  'allowed_prefixes': PREFIXES}
        class Config(dict): pass
        config = Config(config); config.sources = SOURCES
        parent = CredentialStore(environ={'EXT_OPENWISP_TOKEN': 'synthetic-token', 'EXT_NETBOX_TOKEN': 'netbox-token'})
        with patch('isp_geofeed_generator.adapters.OpenWISP', return_value=source), \
                patch('isp_geofeed_generator.adapters.NetBox', return_value=netbox):
            results = read_inputs(config, parent, 'generate')
        records, report = combine_inputs(results, config, frozenset({'country', 'region', 'city'}))
        self.assertEqual([r['prefix'] for r in records], PREFIXES)
        self.assertEqual({r['input'] for r in report}, {'customers', 'infra'})
        # A bad required input cannot yield the other input's standalone feed.
        bad, _ = self.source([{**row(V6, PREFIXES[1]), 'organization': OTHER}], [V6])
        with patch('isp_geofeed_generator.adapters.OpenWISP', return_value=bad), self.assertRaisesRegex(GeofeedError, 'customers'):
            read_inputs(config, parent, 'generate')

    def test_shared_ownership_overlap_and_special_space_guards_remain_active(self):
        source, _ = self.source(); snapshot = source.snapshot()
        with self.assertRaisesRegex(GeofeedError, 'outside allowed_prefixes'):
            build(snapshot, {'allowed_prefixes': PREFIXES[:1], 'site_locations': locations()})
        source, _ = self.source([row(), row(V6, PREFIXES[0])])
        with self.assertRaisesRegex(GeofeedError, 'Overlapping/duplicate'):
            build(source.snapshot(), {'allowed_prefixes': PREFIXES, 'site_locations': locations()})
        for prefix in ('10.0.0.0/24', '2001:db8::/64'):
            source, _ = self.source([row(V4, prefix)], [V4])
            with self.assertRaisesRegex(GeofeedError, 'No public mapped prefixes'):
                build(source.snapshot(), {'allowed_prefixes': [prefix], 'site_locations': locations([V4])})

    def test_private_guard_removals_fail_real_controls(self):
        from isp_geofeed_generator import openwisp
        text = Path(openwisp.__file__).read_text(encoding='utf-8')
        controls = [
            ('organization', "if row.get('organization') != self.organization:", 'if False:',
             'test_missing_wrong_or_global_organization_refuses_before_more_reads'),
            ('identity', "row.get('id') != rid", 'False',
             'test_detail_identity_envelope_and_late_failure_never_return_partial_inventory'),
            ('canonical-boundaries', 'strict=True', 'strict=False',
             'test_noncanonical_invalid_or_missing_boundaries_do_not_echo_response_data')]
        def run(method):
            result = unittest.TestResult(); OpenWISPTests(method).run(result); return result
        positive = 'test_exact_dual_stack_selected_details_and_private_field_projection'
        for name, find, replacement, method in controls:
            with self.subTest(mutation=name):
                self.assertTrue(run(positive).wasSuccessful()); self.assertTrue(run(method).wasSuccessful())
                self.assertEqual(text.count(find), 1)
                mutated = text.replace(find, replacement)
                if name == 'canonical-boundaries':
                    mutated = mutated.replace('if str(network) != value:', 'if False:')
                module = types.ModuleType('isp_geofeed_generator._private_openwisp_control')
                module.__package__ = 'isp_geofeed_generator'
                exec(compile(mutated, '<private OpenWISP control>', 'exec'), module.__dict__)
                with patch(__name__ + '.OpenWISP', module.OpenWISP): result = run(method)
                self.assertEqual(result.errors, []); self.assertGreater(len(result.failures), 0)
                self.assertTrue(run(method).wasSuccessful()); self.assertTrue(run(positive).wasSuccessful())
                print('OPENWISP MUTATION OBSERVATION: ' + json.dumps({'mutation': name,
                    'assertion_failures': len(result.failures), 'errors': 0, 'intact_before_after': True}))

    def test_cli_publish_unchanged_and_bad_late_input_preserves_feed_and_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); path = root/'config.yaml'
            config = {'inputs': {'infra': {'source': {'type': 'openwisp', **settings()},
                'url': 'https://example.net', 'credentials': {'OPENWISP_API_TOKEN': 'env:EXT_OPENWISP_TOKEN'},
                'site_locations': locations()}}, 'allowed_prefixes': PREFIXES,
                'state_dir': str(root/'state'), 'publish': {'type': 'file', 'path': str(root/'feed.csv')}}
            def run(replies):
                path.write_text(yaml.safe_dump(config), encoding='utf-8')
                output, error = io.StringIO(), io.StringIO()
                with patch.dict('os.environ', {'EXT_OPENWISP_TOKEN': 'synthetic-token'}), \
                        patch('isp_geofeed_generator.openwisp.JsonHTTP', return_value=HTTP(replies)), \
                        patch('isp_geofeed_generator.cli.load_policy', return_value=policy()), \
                        contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                    result = main(['publish', '--config', str(path)])
                self.assertNotIn('PRIVATE', output.getvalue() + error.getvalue())
                self.assertNotIn('synthetic-token', output.getvalue() + error.getvalue())
                return result
            good = [row(), row(V6, PREFIXES[1])]
            self.assertEqual(run(good), 1); self.assertFalse((root/'feed.csv').exists())
            config['inputs']['infra']['source']['allow_initial'] = True
            self.assertEqual(run(good), 0)
            before = (root/'feed.csv').read_bytes(); stamp = (root/'feed.csv').stat().st_mtime_ns
            recovery = root/'state/before.csv'
            recovery_before = (recovery.read_bytes(), recovery.stat().st_mtime_ns)
            self.assertEqual(run(good), 0)
            self.assertEqual((root/'feed.csv').stat().st_mtime_ns, stamp)
            self.assertEqual((recovery.read_bytes(), recovery.stat().st_mtime_ns), recovery_before)
            backup = root/'state/private-backup'; backup.write_bytes(b'PRIVATE backup')
            for bad in ({**row(V6, PREFIXES[1]), 'organization': OTHER}, {},
                        {**row(V6, PREFIXES[1]), 'subnet': 'PRIVATE'},
                        row(V6, PREFIXES[0]), row(V6, '12.0.0.0/24')):
                self.assertEqual(run([row(), bad]), 1)
                self.assertEqual((root/'feed.csv').read_bytes(), before)
                self.assertEqual((root/'feed.csv').stat().st_mtime_ns, stamp)
                self.assertEqual(backup.read_bytes(), b'PRIVATE backup')
                self.assertEqual((recovery.read_bytes(), recovery.stat().st_mtime_ns), recovery_before)
                self.assertFalse(json.loads((root/'state/status.json').read_text())['data']['healthy'])
