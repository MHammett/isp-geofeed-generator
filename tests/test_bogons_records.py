import contextlib
import io
import ipaddress
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from bogon_fixture import data, policy
from test_feed import snapshot, config
from isp_geofeed_generator.bogons import BogonIndex, load_policy
from isp_geofeed_generator.cli import main
from isp_geofeed_generator.adapters import SOURCES
from isp_geofeed_generator.contracts import SourceAdapter
from isp_geofeed_generator.client import GeofeedError
from isp_geofeed_generator.feed import build_records, render_csv
from isp_geofeed_generator.feed import SPECIAL
from isp_geofeed_generator.records import encode_records, parse_records, publish_records_file


class BogonTests(unittest.TestCase):
    def test_special_space_fixture_matches_python_and_wordpress_contract(self):
        fixture = json.loads((Path(__file__).parent/'fixtures/special-prefixes.json').read_text())
        self.assertEqual(fixture, [str(net) for net in SPECIAL])
    def test_interior_overlap_and_unallocated_space_are_refused(self):
        guard = policy()
        for value in ('14.102.240.0/20', '14.0.0.0/8', '4000::/3', 'fc00::/7'):
            with self.subTest(value=value), self.assertRaisesRegex(GeofeedError, 'bogon'):
                guard.check([ipaddress.ip_network(value)])
        guard.check([ipaddress.ip_network('11.22.33.0/24'), ipaddress.ip_network('2001:4860:1234::/48')])

    def test_stale_empty_malformed_future_wrong_family_and_missing_canaries_fail(self):
        now = int(time.time())
        for payload in (b'', b'<html>error</html>', data(4, now-86401), data(4, now+1000), data(6),
                        ('# last updated '+str(now)+'\n14.102.240.0/20\n').encode()):
            with self.assertRaises(GeofeedError): BogonIndex(payload, 4, now)

    def test_refresh_cache_and_fail_closed_without_stale_fallback(self):
        now = int(time.time())
        with tempfile.TemporaryDirectory() as tmp:
            settings = {'state_dir': tmp}
            load_policy(settings, fetch=lambda version: data(version), now=now)
            def denied(version): raise AssertionError('Fresh cache must not be fetched again')
            load_policy(settings, fetch=denied, now=now)
            for version in (4, 6):
                (Path(tmp)/'bogons'/f'fullbogons-ipv{version}.txt').write_bytes(data(version, now-90000))
            def offline(version): raise OSError('offline')
            with self.assertRaisesRegex(GeofeedError, 'Cannot refresh'): load_policy(settings, fetch=offline, now=now)
            load_policy(settings, fetch=lambda version: data(version), now=now)

    def test_bogon_guard_cannot_be_disabled_by_configuration(self):
        for setting in (False, {'enabled': False}, {'ipv4_file': 'relative.txt'}):
            with self.assertRaises(GeofeedError): load_policy({'bogons': setting})

    def test_cli_refuses_bogons_before_calling_any_output(self):
        class Source:
            def snapshot(self):
                value = snapshot();value['pools'][0].update(ip_range='14.102.240.0/24', subnet={'subnet': '14.102.240.0/20'});return value
            def for_publication(self, value):return value
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp);target=directory/'public.csv';target.write_bytes(b'untouched')
            cfg=directory/'config.yaml'
            cfg.write_text(f'source: {{type: fixture}}\nstate_dir: {directory.as_posix()}/state\nallowed_prefixes: [14.102.240.0/20]\npool_sites: {{"101": "11"}}\npublish: {{type: file, path: {target.as_posix()}}}\n')
            with patch.dict(SOURCES, fixture=SourceAdapter(lambda s,c:Source(),initial=False)),patch('isp_geofeed_generator.cli.load_policy',return_value=policy()),contextlib.redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(main(['publish','--config',str(cfg)]),1)
            self.assertIn('bogon',stderr.getvalue());self.assertEqual(target.read_bytes(),b'untouched')


class LocationRecordTests(unittest.TestCase):
    def coordinate_snapshot(self):
        value=snapshot();value['sites'][0]['addresses'][0]={'id':'501','latitude':41.9,'longitude':-88.7};return value

    def test_coordinates_need_no_invented_city_and_csv_requires_its_fields(self):
        records,_=build_records(self.coordinate_snapshot(),config(),frozenset({'latitude','longitude'}))
        self.assertEqual(records[0]['location'],{'latitude':41.9,'longitude':-88.7})
        with self.assertRaises(GeofeedError):render_csv(records)
        with self.assertRaises(GeofeedError):build_records(snapshot(),config(),frozenset({'latitude','longitude'}))

    def test_invalid_coordinate_pair_range_and_nan_fail(self):
        for values,fields in (({'latitude':91,'longitude':0},{'latitude','longitude'}),
                              ({'latitude':0,'longitude':181},{'latitude','longitude'}),
                              ({'latitude':float('nan'),'longitude':0},{'latitude','longitude'}),
                              ({'latitude':True,'longitude':0},{'latitude','longitude'}),
                              ({'latitude':0},{'latitude'})):
            value=self.coordinate_snapshot();value['sites'][0]['addresses'][0].update(values)
            with self.assertRaises(GeofeedError):build_records(value,config(),frozenset(fields))

    def test_json_readback_noop_and_address_coverage_guard(self):
        records,_=build_records(self.coordinate_snapshot(),config(),frozenset({'latitude','longitude'}))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'records.json'
            self.assertTrue(publish_records_file(path,records,tmp)['changed'])
            self.assertFalse(publish_records_file(path,records,tmp)['changed'])
            with self.assertRaisesRegex(GeofeedError,'removal'):publish_records_file(path,records[:1],tmp)
        self.assertEqual(parse_records(encode_records(records))[0],records)

    def test_cli_selects_coordinate_json_and_refuses_incompatible_csv_projection(self):
        value=self.coordinate_snapshot()
        class Source:
            def snapshot(self):return value
            def for_publication(self, source):return source
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);cfg=directory/'config.yaml';target=directory/'records.json'
            base=f'source: {{type: fixture}}\nstate_dir: {directory.as_posix()}/state\nallowed_prefixes: [11.22.33.0/24]\npool_sites: {{"101": "11"}}\npublish: {{type: OUTPUT, path: {target.as_posix()}, location_fields: [latitude, longitude], allow_initial: true}}\n'
            with patch.dict(SOURCES,fixture=SourceAdapter(lambda s,c:Source(),initial=False)),patch('isp_geofeed_generator.cli.load_policy',return_value=policy()):
                cfg.write_text(base.replace('OUTPUT','json'));self.assertEqual(main(['publish','--config',str(cfg)]),0)
                first=target.read_bytes();self.assertNotIn(b'city',first);self.assertIn(b'latitude',first)
                cfg.write_text(base.replace('OUTPUT','file'));self.assertEqual(main(['publish','--config',str(cfg)]),1)
                self.assertEqual(target.read_bytes(),first)
