"""ISO membership is distinct from code shape and real-world geography."""
import tempfile
import json
import hashlib
import unittest
from pathlib import Path
from isp_geofeed_generator.client import GeofeedError
from isp_geofeed_generator.feed import parse_feed
from isp_geofeed_generator.locations import validate_location
from isp_geofeed_generator.records import encode_records


class IsoMembership(unittest.TestCase):
    def test_shared_conformance_controls(self):
        cases=json.loads((Path(__file__).parent/'fixtures/conformance.json').read_text(encoding='utf-8'))
        for case in cases:
            with self.subTest(case=case['name']):
                if case['core_refuses']:
                    with self.assertRaises(GeofeedError):parse_feed(case['csv'].encode())
                else:parse_feed(case['csv'].encode())
    def test_assigned_country_and_subdivision_examples_still_pass(self):
        for country,region in (('US','US-IL'),('CA','CA-ON'),('GB','GB-ENG'),('JP','JP-13'),
                               ('BR','BR-SP'),('FR','FR-IDF'),('ZA','ZA-GP'),('AU','AU-NSW'),('US','')):
            with self.subTest(country=country):
                parse_feed(f'11.22.33.0/24,{country},{region},Example,\r\n'.encode())

    def test_shape_correct_but_unassigned_country_is_refused(self):
        for code in ('XX','ZZ','UK','SU'):
            with self.subTest(code=code),self.assertRaises(GeofeedError):
                parse_feed(f'11.22.33.0/24,{code},,Example,\r\n'.encode())

    def test_nonexistent_and_cross_country_subdivisions_are_refused(self):
        for country,region in (('US','US-ZZZ'),('US','GB-ENG'),('CA','CA-ZZZ')):
            with self.subTest(region=region),self.assertRaises(GeofeedError):
                parse_feed(f'11.22.33.0/24,{country},{region},Example,\r\n'.encode())

    def test_rich_country_and_region_fields_enforce_membership_independently(self):
        for value in ({'country':'XX'},{'region':'US-ZZZ'}):
            with self.subTest(value=value),self.assertRaises(GeofeedError):
                validate_location(value,set(value))
            with self.assertRaises(GeofeedError):
                encode_records([{'prefix':'11.22.33.0/24','location':value}])

    def test_coordinate_only_output_does_not_invent_or_publish_country(self):
        self.assertEqual(validate_location({'latitude':41,'longitude':-88,'country':'XX'},
                                          {'latitude','longitude'}),{'latitude':41,'longitude':-88})

    def test_missing_and_changed_iso_files_fail_closed_without_content_leaks(self):
        from isp_geofeed_generator.iso_codes import load_tables
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with self.assertRaises(GeofeedError):load_tables(root)
            (root/'iso3166-1.json').write_text('{"private":"secret test marker"}')
            with self.assertRaises(GeofeedError) as caught:load_tables(root)
            self.assertNotIn('secret test marker',str(caught.exception))

    def test_python_and_plugin_ship_identical_data_and_notices(self):
        root=Path(__file__).resolve().parents[1]
        python=root/'isp_geofeed_generator/iso_data';php=root/'wordpress/isp-geofeed-generator/iso_data'
        expected={'iso3166-1.json','iso3166-2.json','LICENSE.txt','COPYRIGHT.txt','sources.json'}
        self.assertEqual({p.name for p in python.iterdir()},expected)
        for name in expected:self.assertEqual((python/name).read_bytes(),(php/name).read_bytes())
        manifest=json.loads((python/'sources.json').read_bytes())
        for name,entry in manifest['files'].items():
            self.assertEqual(hashlib.sha256((python/name).read_bytes()).hexdigest(),entry['sha256'])
