"""Regression cases from the independent review and adapter contract checks."""
import contextlib
import io
import ipaddress
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from isp_geofeed_generator import __version__
from isp_geofeed_generator.adapters import SOURCES, TARGETS, SourceAdapter, FileTarget
from isp_geofeed_generator.cli import main, run_lock
from isp_geofeed_generator.client import GeofeedError, JsonHTTP
from isp_geofeed_generator.credentials import NAMES
from isp_geofeed_generator.feed import build, public
from isp_geofeed_generator.netbox import NetBox
from test_feed import snapshot
from test_sources import HTTP, SITE, PREFIX, page


class ReviewTests(unittest.TestCase):
    def config(self, directory, source='fixture', target='file'):
        cfg = directory / 'config.yaml'
        cfg.write_text(f'source: {{type: {source}}}\nstate_dir: {directory.as_posix()}/state\n'
                       f'allowed_prefixes: [11.22.33.0/24]\npool_sites: {{"101": "11"}}\n'
                       f'publish: {{type: {target}, path: {directory.as_posix()}/public.csv}}\n')
        return str(cfg)

    def source(self, sites=None, prefixes=None):
        return NetBox('https://netbox.example.net', 'fake-token', {'prefix_ids': ['1']},
                      HTTP([page([PREFIX] if prefixes is None else prefixes), page([]), page([SITE] if sites is None else sites)]))

    def test_helper_accepts_every_supported_credential(self):
        result = subprocess.run([sys.executable, 'tools/store_systemd_credential.py', '--help'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        for name in NAMES:
            self.assertIn(name, result.stdout)

    def test_proxy_next_link_is_a_hint_and_never_downgrades_transport(self):
        http = HTTP([page([{'id': 1}], 2, 'http://netbox.example.net/api/dcim/sites/?offset=999'), page([{'id': 2}], 2)])
        source = NetBox('https://netbox.example.net', 'fake-token', http=http)
        self.assertEqual(len(source.pages('/dcim/sites/')), 2)
        self.assertTrue(http.calls[1][0].startswith('https://netbox.example.net/'))
        self.assertIn('offset=1', http.calls[1][0])
        for url in ('http://other.example.net/api/dcim/sites/', 'http://netbox.example.net/api/ipam/prefixes/',
                    'ftp://netbox.example.net/api/dcim/sites/', 'http://netbox.example.net:999/api/dcim/sites/'):
            http = HTTP([page([{'id': 1}], 2, url)])
            with self.assertRaises(GeofeedError):
                NetBox('https://netbox.example.net', 'fake-token', http=http).pages('/dcim/sites/')
            self.assertEqual(len(http.calls), 1)

    def test_null_custom_fields_becomes_an_actionable_setup_failure(self):
        source = self.source(sites=[{**SITE, 'custom_fields': None}])
        with self.assertRaisesRegex(GeofeedError, 'Site 10.*country'):
            build(source.for_publication(source.snapshot()), {'allowed_prefixes': ['11.22.33.0/24']})

    def test_bad_netbox_records_name_id_without_echoing_values(self):
        with self.assertRaisesRegex(GeofeedError, 'NetBox prefix 1.*invalid') as result:
            self.source(prefixes=[{**PREFIX, 'prefix': 'sensitive-value'}]).snapshot()
        self.assertNotIn('sensitive-value', str(result.exception))
        with self.assertRaisesRegex(GeofeedError, 'NetBox site 10.*custom_fields'):
            self.source(sites=[{**SITE, 'custom_fields': ['invalid']}]).snapshot()

    def test_review_special_ranges_are_rejected_with_public_control(self):
        for value in ('192.88.99.0/24', '2001:20::/28', '5f00::/16', 'fec0::/10'):
            self.assertFalse(public(ipaddress.ip_network(value)), value)
        self.assertTrue(public(ipaddress.ip_network('8.8.8.0/24')))
        self.assertTrue(public(ipaddress.ip_network('2001:4860::/32')))

    def test_normalized_record_failures_are_actionable_and_private(self):
        for field, value, message in (('ip_range', None, 'Pool 101.*ip_range'),
                                      ('ip_range', 'sensitive-value', 'Pool 101.*invalid IP range'),
                                      ('subnet', {}, 'Pool 101.*parent subnet')):
            value_snapshot = snapshot()
            value_snapshot['pools'][0][field] = value
            with self.assertRaisesRegex(GeofeedError, message) as result:
                build(value_snapshot, {'pool_sites': {'101': '11'}, 'allowed_prefixes': ['11.22.33.0/24']})
            self.assertNotIn('sensitive-value', str(result.exception))
        value_snapshot = snapshot()
        value_snapshot['pools'].append(dict(value_snapshot['pools'][0]))
        with self.assertRaisesRegex(GeofeedError, 'duplicate ID 101'):
            build(value_snapshot, {})

    def test_unexpected_failure_records_status_and_no_raw_details(self):
        class BrokenSource:
            def snapshot(self): raise AttributeError('sensitive upstream content')
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            with patch.dict(SOURCES, fixture=SourceAdapter(lambda s, c: BrokenSource())), contextlib.redirect_stderr(io.StringIO()) as output:
                self.assertEqual(main(['publish', '--config', self.config(directory)]), 1)
            saved = json.loads((directory/'state/status.json').read_text())
            self.assertFalse(saved['data']['healthy'])
            self.assertIn('reading fixture inventory', saved['data']['error'])
            self.assertNotIn('sensitive', output.getvalue())
            self.assertNotIn('Traceback', output.getvalue())

    def test_read_commands_do_not_block_publication_or_rewrite_status(self):
        class FixtureSource:
            def snapshot(self): return snapshot()
            def for_publication(self, value): return value
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            cfg = self.config(directory)
            state = directory/'state'
            with patch.dict(SOURCES, fixture=SourceAdapter(lambda s, c: FixtureSource())), run_lock(state):
                (state/'status.json').write_text('active publisher sentinel')
                for command in ('discover', 'generate'):
                    self.assertEqual(main([command, '--config', cfg, '--output', str(directory/(command+'.txt'))]), 0)
                self.assertEqual(main(['publish', '--config', cfg]), 1)
                self.assertEqual((state/'status.json').read_text(), 'active publisher sentinel')

    def test_new_source_and_target_compose_without_cli_changes(self):
        calls = []
        class FixtureSource:
            def snapshot(self): return snapshot()
            def for_publication(self, value): calls.append('normalize'); return value
        class Target:
            def publish(self, csv, state_dir, **guards):
                calls.append(csv)
                return {'changed': True}
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(SOURCES, fixture=SourceAdapter(lambda s, c: FixtureSource())), patch.dict(TARGETS, fixture=lambda s, c: Target()):
                self.assertEqual(main(['publish', '--config', self.config(Path(tmp), target='fixture')]), 0)
        self.assertEqual(calls[0], 'normalize')
        self.assertIn(b',US,US-IL,Example City,', calls[1])

    def test_unselected_source_secrets_are_never_requested(self):
        class Credentials:
            def get(self, name):
                self.assertion(name)
                return 'test-token'
        credentials = Credentials()
        for kind, needed, environment in (
            ('sonar', {'SONAR_API_TOKEN'}, {'SONAR_URL': 'https://example.net'}),
            ('netbox', {'NETBOX_API_TOKEN'}, {'NETBOX_URL': 'https://example.net'}),
            ('splynx', {'SPLYNX_API_KEY', 'SPLYNX_API_SECRET'}, {'SPLYNX_URL': 'https://example.net'}),
            ('phpipam', {'PHPIPAM_API_TOKEN'}, {'PHPIPAM_URL': 'https://example.net', 'PHPIPAM_APP_ID': 'geofeed'})):
            requested = set()
            def check(name):
                self.assertIn(name, needed)
                requested.add(name)
            credentials.assertion = check
            with patch.dict('os.environ', environment, clear=True):
                source = SOURCES[kind].create({}, credentials)
                self.assertTrue(callable(source.snapshot))
                self.assertTrue(callable(source.for_publication))
            self.assertEqual(requested, needed)
        credentials.assertion = lambda name: self.fail('File target asked for a secret')
        self.assertIsInstance(TARGETS['file']({'path': 'candidate.csv'}, credentials), FileTarget)

    def test_json_user_agent_matches_package_version(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, limit): return b'{}'
        http = JsonHTTP()
        with patch.object(http.opener, 'open', return_value=Response()) as opened:
            http.request('https://example.net')
        self.assertEqual(opened.call_args.args[0].get_header('User-agent'), 'isp-geofeed-generator/'+__version__)
