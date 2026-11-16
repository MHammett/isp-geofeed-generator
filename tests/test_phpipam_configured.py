"""Explicit facilities for instances that do not use native phpIPAM locations."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from isp_geofeed_generator.cli import main
from isp_geofeed_generator.client import GeofeedError
from isp_geofeed_generator.feed import build
from isp_geofeed_generator.phpipam import PhpIPAM
from test_sources import HTTP
from bogon_fixture import policy

SUBNET = {'id': '1', 'subnet': '11.22.33.0', 'mask': '24', 'location': [], 'isFolder': '0'}
OPTIONS = {'subnet_ids': ['1'], 'location_mode': 'configured', 'facility_ids': ['pop-1']}
CONFIG = {'allowed_prefixes': ['11.22.33.0/24'], 'pool_sites': {'subnet:1': 'pop-1'},
          'site_locations': {'pop-1': {'country': 'US', 'region': 'US-IL', 'city': 'Example City'}}}


def ok(rows): return {'code': 200, 'success': True, 'data': rows}


class ConfiguredLocationTests(unittest.TestCase):
    def source(self, options=None, subnet=None):
        http = HTTP([ok([SUBNET if subnet is None else subnet])])
        source = PhpIPAM('https://ipam.example.net', 'geofeed', 'fake-token', OPTIONS if options is None else options, http)
        return source, http

    def test_no_native_locations_needed_when_facilities_are_explicit(self):
        source, http = self.source()
        data = source.for_publication(source.snapshot())
        self.assertEqual(build(data, CONFIG)[0], b'11.22.33.0/24,US,US-IL,Example City,\r\n')
        self.assertEqual(len(http.calls), 1)
        self.assertTrue(http.calls[0][0].endswith('/subnets/all/'))

    def test_configured_policy_does_not_use_private_native_location_details(self):
        source, _ = self.source(subnet={**SUBNET, 'location': {'id': 'private street', 'address': 'private street'}})
        data = source.for_publication(source.snapshot())
        self.assertIsNone(data['pools'][0]['site_id'])
        self.assertNotIn('private street', str(data))
        self.assertIn(b'Example City', build(data, CONFIG)[0])

    def test_invalid_modes_missing_or_duplicate_facilities_fail(self):
        for changes in ({'location_mode': 'guess'}, {'facility_ids': []}, {'facility_ids': ['pop-1', 'pop-1']},
                        {'facility_ids': ['private street']}, {'facility_ids': [True]}, {'location_mode': 'native'}):
            with self.subTest(changes=changes), self.assertRaises(GeofeedError): self.source({**OPTIONS, **changes})

    def test_missing_mapping_geo_and_facility_do_not_create_default_locations(self):
        source, _ = self.source(); snapshot = source.for_publication(source.snapshot())
        for changes in ({'pool_sites': {}}, {'site_locations': {}}, {'pool_sites': {'subnet:1': 'missing'}}):
            with self.assertRaises(GeofeedError): build(snapshot, {**CONFIG, **changes})

    def test_subnet_errors_and_native_location_errors_still_stop(self):
        for options, replies in ((OPTIONS, [{'code': 403, 'success': False, 'data': []}]),
                                 ({'subnet_ids': ['1']}, [ok([SUBNET]), {'code': 404, 'success': False, 'message': 'No objects found'}])):
            source = PhpIPAM('https://ipam.example.net', 'geofeed', 'token', options, HTTP(replies))
            with self.assertRaises(GeofeedError): source.snapshot()

    def test_authentication_error_explains_token_expiry_without_upstream_details(self):
        for status in (401, 403):
            class Denied:
                def request(self, *args, **kwargs): raise GeofeedError(f'HTTP {status}; private response details')
            source = PhpIPAM('https://ipam.example.net', 'geofeed', 'token', OPTIONS, Denied())
            with self.assertRaisesRegex(GeofeedError, 'token may have expired') as caught: source.snapshot()
            self.assertNotIn('private', str(caught.exception))
            self.assertIn('read-only', str(caught.exception))

    def test_cli_configured_location_publication_and_missing_geo_preserve_prior_feed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path = root/'config.yaml'; output = root/'public.csv'
            text = ('source: {type: phpipam, app_id: geofeed, subnet_ids: ["1"], location_mode: configured, facility_ids: [pop-1], allow_initial: true}\n'
                    f'state_dir: {root.as_posix()}/state\npublish: {{type: file, path: {output.as_posix()}}}\n'
                    'allowed_prefixes: [11.22.33.0/24]\npool_sites: {"subnet:1": pop-1}\n'
                    'site_locations: {pop-1: {country: US, region: US-IL, city: Example City}}\n')
            def response(url, **kwargs):
                self.assertTrue(url.endswith('/subnets/all/'), 'Locations API must not be called')
                return ok([SUBNET])
            with patch.dict('os.environ', {'PHPIPAM_URL': 'https://ipam.example.net', 'PHPIPAM_API_TOKEN': 'fake-token'}), patch('isp_geofeed_generator.client.JsonHTTP.request', side_effect=response), patch('isp_geofeed_generator.cli.load_policy', side_effect=lambda c: policy()), contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                path.write_text(text); self.assertEqual(main(['publish', '--config', str(path)]), 0)
                before = output.read_bytes()
                path.write_text(text.replace('city: Example City', 'city: ""'))
                self.assertEqual(main(['publish', '--config', str(path)]), 1)
                self.assertEqual(output.read_bytes(), before)
