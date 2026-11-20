"""Public cache probes describe evidence without publishing or clearing failures."""
import contextlib
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import yaml

from isp_geofeed_generator.adapters import SOURCES
from isp_geofeed_generator.cli import main
from isp_geofeed_generator.client import GeofeedError
from isp_geofeed_generator.contracts import SourceAdapter
from isp_geofeed_generator.credentials import CredentialStore
from isp_geofeed_generator.feed import digest, render_csv
from isp_geofeed_generator.overlap import REJECT, LONGEST_PREFIX
from isp_geofeed_generator.publish import WordPress
from isp_geofeed_generator.wordpress_inspection import inspect_delivery
from isp_geofeed_generator.wordpress_policy import Snapshot
from test_nested_core import PARENT

A = render_csv([PARENT])
B = A.replace(b',A,', b',B,')
C = A.replace(b',A,', b',C,')


class Client:
    public_url = 'https://example.net/wp-json/isp-geofeed-generator/v1/feed'

    def __init__(self, canonical=A, probe=A):
        self.current = Snapshot(A, REJECT, REJECT, b'', REJECT, 'a' * 32)
        self.canonical, self.probe = canonical, probe
        self.calls = []
        self.recheck = self.current

    def policy_state(self):
        self.calls.append('state')
        value = self.current if self.calls.count('state') == 1 else self.recheck
        if isinstance(value, Exception):
            raise value
        return value

    def read_public(self, **kwargs):
        self.calls.append('canonical')
        if isinstance(self.canonical, Exception):
            raise self.canonical
        return self.canonical

    def read_public_probe(self, **kwargs):
        self.calls.append('probe')
        if isinstance(self.probe, Exception):
            raise self.probe
        return self.probe


class InspectionTests(unittest.TestCase):
    def test_default_checks_canonical_without_a_probe(self):
        client = Client()
        result = inspect_delivery(client)
        self.assertEqual(client.calls, ['state', 'canonical', 'state'])
        self.assertTrue(result['inspection_consistent'])
        self.assertFalse(result['cache_probe_requested'])
        self.assertIsNone(result['cache_probe_matches_stored'])
        self.assertEqual(result['delivery_finding'], 'canonical_matches')
        self.assertNotIn('healthy', result)
        self.assertNotIn('csv', result)

    def test_probe_outcomes_distinguish_matches_differences_and_not_measured(self):
        failure = GeofeedError('private upstream body and credentials must not escape')
        cases = [
            (A, A, 'both_match', True), (B, A, 'canonical_differs_probe_matches', False),
            (A, B, 'probe_differs', False), (B, B, 'both_differ_same_bytes', False),
            (B, C, 'both_differ_different_bytes', False),
            (failure, A, 'canonical_unavailable_probe_matches', False),
            (A, failure, 'probe_unavailable', False),
            (B, failure, 'canonical_differs_probe_unavailable', False),
            (failure, failure, 'public_read_unavailable', False),
        ]
        self.assertNotEqual(A, B)
        self.assertNotEqual(B, C)
        for canonical, probe, finding, consistent in cases:
            with self.subTest(finding=finding):
                client = Client(canonical, probe)
                result = inspect_delivery(client, probe_cache=True)
                self.assertEqual(result['delivery_finding'], finding)
                self.assertEqual(result['inspection_consistent'], consistent)
                self.assertEqual(result['public_read_measured'], isinstance(canonical, bytes))
                self.assertEqual(result['cache_probe_measured'], isinstance(probe, bytes))
                self.assertEqual(client.calls, ['state', 'canonical', 'probe', 'state'])
                self.assertNotIn('private upstream', json.dumps(result))
                self.assertNotIn('healthy', result)
                if isinstance(canonical, Exception):
                    self.assertIsNone(result['public_sha256'])
                    self.assertIsNone(result['public_matches_stored'])

    def test_same_bytes_with_changed_policy_owner_or_history_is_not_stable(self):
        for changes in ({'publication_id': 'b' * 32}, {'required': LONGEST_PREFIX},
                        {'previous': B}, {'previous_policy': LONGEST_PREFIX}):
            with self.subTest(changes=changes):
                client = Client()
                client.recheck = replace(client.current, **changes)
                result = inspect_delivery(client, probe_cache=True)
                self.assertTrue(result['public_matches_stored'])
                self.assertTrue(result['cache_probe_matches_stored'])
                self.assertFalse(result['policy_state_stable'])
                self.assertFalse(result['inspection_consistent'])
                self.assertEqual(result['delivery_finding'], 'state_changed')

    def test_failed_state_recheck_is_not_measured(self):
        client = Client()
        client.recheck = GeofeedError('private state body')
        result = inspect_delivery(client, probe_cache=True)
        self.assertIsNone(result['policy_state_stable'])
        self.assertEqual(result['delivery_finding'], 'state_recheck_unavailable')
        self.assertFalse(result['inspection_consistent'])
        self.assertNotIn('private state', json.dumps(result))

    def test_unsupported_probe_refuses_before_reads(self):
        client = Client()
        client.read_public_probe = None
        with self.assertRaisesRegex(GeofeedError, 'lacks the read-only public cache probe'):
            inspect_delivery(client, probe_cache=True)
        self.assertEqual(client.calls, [])

    def test_empty_target_is_explicit_and_not_publication_health(self):
        client = Client(b'', b'')
        client.current = replace(client.current, csv=b'')
        client.recheck = client.current
        result = inspect_delivery(client, probe_cache=True)
        self.assertTrue(result['inspection_consistent'])
        self.assertFalse(result['feed_present'])
        self.assertNotIn('healthy', result)

    def test_cli_probe_keeps_failed_status_and_reads_only_publisher_credential(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            status = root / 'status.json'
            status.write_bytes(b'unhealthy publication')
            baseline = (status.read_bytes(), status.stat().st_mtime_ns)
            config = root / 'config.yaml'
            config.write_text(yaml.safe_dump({'source': {'type': 'offline'}, 'state_dir': str(root),
                                             'publish': {'type': 'wordpress'}}))
            client = Client(B, A)
            factory = Mock(side_effect=AssertionError('source must not be read'))
            output = io.StringIO()
            with patch.dict(SOURCES, {'offline': SourceAdapter(factory, initial=False)}), \
                 patch('isp_geofeed_generator.adapters.WordPress', return_value=client), \
                 patch.object(CredentialStore, 'get', autospec=True, return_value='synthetic') as credential, \
                 contextlib.redirect_stdout(output):
                self.assertEqual(main(['inspect-wordpress', '--config', str(config), '--probe-cache']), 1)
            factory.assert_not_called()
            self.assertEqual(credential.call_count, 1)
            self.assertEqual(credential.call_args.args[1], 'WP_APP_PASSWORD')
            self.assertEqual(json.loads(output.getvalue())['delivery_finding'], 'canonical_differs_probe_matches')
            self.assertEqual((status.read_bytes(), status.stat().st_mtime_ns), baseline)
            self.assertEqual({p.name for p in root.iterdir()}, {'status.json', 'config.yaml'})

    def test_probe_flag_cannot_be_used_to_publish(self):
        with patch('isp_geofeed_generator.cli.load_config') as config, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['publish', '--probe-cache']), 1)
        config.assert_not_called()


class ProbeTransportTests(unittest.TestCase):
    def setUp(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                self.server.observations.append((self.path, dict(self.headers)))
                status, content_type, body = self.server.reply
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(body)))
                if status == 302:
                    self.send_header('Location', '/must-not-follow')
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.reply = (200, 'text/csv', A)
        self.server.observations = []
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)
        self.thread.start()
        server = self.server

        class LocalWordPress(WordPress):
            @property
            def public_url(self):
                return f'http://127.0.0.1:{server.server_port}/wp-json/isp-geofeed-generator/v1/feed'

        self.client = LocalWordPress('https://example.net', 'publisher', 'synthetic-private-password')
        self.addCleanup(self.close)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def test_probe_uses_one_anonymous_get_per_fresh_same_route_url(self):
        self.assertEqual(self.client.read_public(), A)
        for _ in range(2):
            self.assertEqual(self.client.read_public_probe(), A)
        paths = []
        for path, headers in self.server.observations:
            self.assertNotIn('authorization', {key.lower() for key in headers})
            self.assertNotIn('cookie', {key.lower() for key in headers})
            self.assertEqual(headers['Cache-Control'], 'no-cache')
            parts = urlsplit(path)
            self.assertEqual(parts.path, '/wp-json/isp-geofeed-generator/v1/feed')
            paths.append(parts.query)
        self.assertEqual(paths[0], '')
        for query in paths[1:]:
            values = parse_qs(query)
            self.assertEqual(set(values), {'isp_geofeed_probe'})
            self.assertRegex(values['isp_geofeed_probe'][0], r'^[0-9a-f]{32}$')
        self.assertNotEqual(paths[1], paths[2])
        self.assertEqual(len(paths), 3)

    def test_probe_refuses_redirect_without_following(self):
        self.server.reply = (302, 'text/html', b'private remote response')
        with self.assertRaisesRegex(GeofeedError, '^Public feed HTTP 302$'):
            self.client.read_public_probe()
        self.assertEqual(len(self.server.observations), 1)

    def test_probe_keeps_public_type_size_and_parser_limits(self):
        for content_type, body in (('application/json', b'private remote body'),
                                   ('text/csv', b'x' * 1_000_001), ('text/csv', b'not a geofeed')):
            with self.subTest(content_type=content_type, size=len(body)):
                self.server.reply = (200, content_type, body)
                with self.assertRaises(GeofeedError) as error:
                    self.client.read_public_probe()
                self.assertNotIn('private remote', str(error.exception))
