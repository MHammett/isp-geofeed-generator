"""Saved RIPE REST inputs must preserve discovery scope without network or writes."""
import contextlib
import copy
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from isp_geofeed_generator import registry_ripe, registry_check
from isp_geofeed_generator.cli import main
from isp_geofeed_generator.client import GeofeedError, JsonHTTP
from isp_geofeed_generator.credentials import CredentialStore
from isp_geofeed_generator.feed import digest

URL='https://example.net/feed.csv'
OTHER='https://other.example/feed.csv'
STAMP='2020-01-01T00:00:00Z'
NOW=datetime(2026,11,18,tzinfo=timezone.utc)
CSV=b'11.22.33.0/24,US,US-IL,Example City,\r\n2001:4860:1234::/126,US,US-IL,Example City,\r\n'


def obj(kind='inetnum', value='11.22.33.0 - 11.22.33.255', *, native=URL, remarks=None):
    attributes=[{'name':kind,'value':value},{'name':'source','value':'RIPE'},
                {'name':'descr','value':'PRIVATE CONTACT DETAILS'},{'name':'country','value':'NL'},
                {'name':'geoloc','value':'52.0 4.0'}]
    if native is not None:attributes.append({'name':'geofeed','value':native})
    attributes.extend({'name':'remarks','value':v} for v in remarks or [])
    return {'type':kind,'source':{'id':'ripe'},'primary-key':{'attribute':[{'name':kind,'value':value}]},
            'attributes':{'attribute':attributes},'link':{'href':'https://PRIVATE.invalid/do-not-follow'}}


def saved(objects=None, **changes):
    return json.dumps({'objects':{'object':[obj()] if objects is None else objects},**changes}).encode()


def compare(objects=None, csv=CSV.splitlines(keepends=True)[0], **changes):
    return registry_check.check_snapshot(registry_ripe.normalize_ripe(saved(objects,**changes),STAMP),csv,URL,now=NOW)


class RipeRegistryTests(unittest.TestCase):
    def test_dual_stack_and_exact_range_preserved(self):
        data=saved([obj(),obj('inet6num','2001:4860:1234::/126')])
        normalized=registry_ripe.normalize_ripe(data,STAMP)
        rows=json.loads(normalized)['objects']
        self.assertEqual(rows[0]['start'],'11.22.33.0');self.assertEqual(rows[0]['end'],'11.22.33.255')
        self.assertEqual(rows[1]['prefix'],'2001:4860:1234::/126')
        result=registry_check.check_snapshot(normalized,CSV,URL,now=NOW)
        self.assertTrue(result['comparison_consistent'])
        self.assertEqual(result['coverage']['4']['this_feed'],'256')
        self.assertEqual(result['coverage']['6']['this_feed'],'4')
        self.assertNotIn('PRIVATE',normalized.decode())
        self.assertNotIn('country',normalized.decode());self.assertNotIn('geoloc',normalized.decode())

    def test_non_cidr_endpoints_are_not_widened(self):
        result=compare([obj(value='11.22.33.1 - 11.22.33.254')])
        self.assertFalse(result['comparison_consistent'])
        self.assertEqual(result['coverage']['4']['this_feed'],'254')
        self.assertEqual(result['coverage']['4']['unreferenced'],'2')

    def test_reference_rules_reuse_shared_checker(self):
        self.assertTrue(compare([obj(remarks=[f'Geofeed {OTHER}'])])['comparison_consistent'])
        invalid=compare([obj(native='http://bad.invalid/',remarks=[f'Geofeed {URL}'])])
        self.assertEqual(invalid['coverage']['4']['invalid_reference'],'256')
        remarks=compare([obj(native=None,remarks=[f'Geofeed {URL}'])])
        self.assertTrue(remarks['comparison_consistent'])
        malformed=compare([obj(native=None,remarks=[f'geofeed {URL}'])])
        self.assertEqual(malformed['coverage']['4']['invalid_reference'],'256')

    def test_more_specific_and_reference_free_child(self):
        child=obj(value='11.22.33.0 - 11.22.33.127',native=OTHER)
        result=compare([obj(),child])
        self.assertEqual(result['coverage']['4']['other_feed'],'128')
        child['attributes']['attribute']=[a for a in child['attributes']['attribute'] if a['name']!='geofeed']
        self.assertTrue(compare([obj(),child])['comparison_consistent'])

    def test_primary_key_mismatch(self):
        for name,value in (('inetnum','11.22.34.0 - 11.22.34.255'),('inet6num','2001:4860:1234::/126')):
            row=obj();row['primary-key']['attribute']=[{'name':name,'value':value}]
            with self.subTest(name=name),self.assertRaises(GeofeedError):registry_ripe.normalize_ripe(saved([row]),STAMP)

    def test_invalid_sources(self):
        for source in ('TEST','ARIN-GRS','PRIVATE',''):
            row=obj();row['source']['id']=source
            for a in row['attributes']['attribute']:
                if a['name']=='source':a['value']=source
            with self.subTest(source=source),self.assertRaises(GeofeedError):registry_ripe.normalize_ripe(saved([row]),STAMP)
        row=obj();row['attributes']['attribute'][1]['value']='TEST'
        with self.assertRaises(GeofeedError):registry_ripe.normalize_ripe(saved([row]),STAMP)

    def test_error_or_warning_does_not_become_comparison(self):
        for severity in ('Error','Warning','Info'):
            with self.subTest(severity=severity),self.assertRaises(GeofeedError):
                compare(errormessages={'errormessage':[{'severity':severity,'text':'PRIVATE ERROR'}]})
        self.assertTrue(compare(errormessages={'errormessage':[]})['comparison_consistent'])

    def test_unsupported_or_empty_objects_are_not_silently_skipped(self):
        for objects in ([],[{'type':'person','PRIVATE':'contact'}],[obj(),{'type':'route6'}],[None]):
            with self.subTest(objects=objects),self.assertRaises(GeofeedError):registry_ripe.normalize_ripe(saved(objects),STAMP)

    def test_duplicates_and_malformed_attributes(self):
        rows=[]
        row=obj();rows.append([row,copy.deepcopy(row)])
        for field in ('geofeed','source','inetnum'):
            row=obj();row['attributes']['attribute'].append(next(copy.deepcopy(a) for a in row['attributes']['attribute'] if a['name']==field));rows.append([row])
        for value in (None,True,[],{'attribute':[]},{'attribute':[{'name':'remarks','value':'PRIVATE\nDATA'}]}):
            row=obj();row['attributes']=value;rows.append([row])
        for index,objects in enumerate(rows):
            with self.subTest(index=index),self.assertRaises(GeofeedError):registry_ripe.normalize_ripe(saved(objects),STAMP)

    def test_noncanonical_or_wrong_family_scopes(self):
        for kind,value in (('inetnum','11.22.33.0/24'),('inetnum','11.22.33.255 - 11.22.33.0'),
                           ('inetnum','011.22.33.0 - 11.22.33.255'),('inet6num','11.22.33.0/24'),
                           ('inet6num','2001:4860:1234::1/126'),('inet6num','2001:4860:ABCD::/48')):
            with self.subTest(kind=kind,value=value),self.assertRaises(GeofeedError):registry_ripe.normalize_ripe(saved([obj(kind,value)]),STAMP)

    def test_json_limits_and_safe_errors(self):
        for data in (b'{"objects":{},"objects":{},"PRIVATE":1}',b'NaN',b'{"PRIVATE":1e10000}',
                     b'\xff',b'['*1100,b'x'*8_000_001):
            with self.subTest(size=len(data)),self.assertRaises(GeofeedError) as caught:registry_ripe.normalize_ripe(data,STAMP)
            self.assertNotIn('PRIVATE',str(caught.exception))
        with patch.object(registry_ripe,'MAX_OBJECTS',1),self.assertRaises(GeofeedError):registry_ripe.normalize_ripe(saved([obj(),obj()]),STAMP)

    def test_shared_timestamp_and_remarks_limits(self):
        for stamp in ('PRIVATE','2026-11-19T00:00:00Z','2020-01-01T00:00:00-05:00'):
            with self.subTest(stamp=stamp),self.assertRaises(GeofeedError):
                registry_check.check_snapshot(registry_ripe.normalize_ripe(saved(),stamp),CSV,URL,now=NOW)
        with self.assertRaises(GeofeedError):compare([obj(remarks=['unrelated']*21)])

    def test_stable_safe_ids_do_not_depend_on_contacts_or_attribute_order(self):
        first=obj();second=copy.deepcopy(first);second['attributes']['attribute'].reverse()
        second['attributes']['attribute'].append({'name':'admin-c','value':'PRIVATE-123'})
        normalized=[json.loads(registry_ripe.normalize_ripe(saved([r]),STAMP))['objects'][0] for r in (first,second)]
        self.assertEqual(normalized[0]['id'],normalized[1]['id'])
        self.assertRegex(normalized[0]['id'],r'^ripe:inetnum:[0-9a-f]{64}$')

    def test_cli_has_no_config_credentials_network_or_output_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'ripe.json';feed=root/'feed.csv'
            source.write_bytes(saved([obj(),obj('inet6num','2001:4860:1234::/126')]))
            feed.write_bytes(CSV);(root/'status.json').write_bytes(b'failed status');(root/'before.csv').write_bytes(b'old baseline')
            before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()}
            output=io.StringIO()
            with patch('isp_geofeed_generator.cli.load_config',side_effect=AssertionError('config read')), \
                 patch.object(CredentialStore,'get',side_effect=AssertionError('credential read')), \
                 patch.object(JsonHTTP,'request',side_effect=AssertionError('HTTP call')), \
                 patch('socket.getaddrinfo',side_effect=AssertionError('DNS lookup')), \
                 patch('isp_geofeed_generator.cli.atomic_write',side_effect=AssertionError('output write')),contextlib.redirect_stdout(output):
                self.assertEqual(main(['check-registry','--registry-format','ripe-rest','--registry-observed-at',STAMP,
                                       '--registry-records',str(source),'--feed',str(feed),'--feed-url',URL,'--config',str(root/'absent.yaml')]),0)
            report=json.loads(output.getvalue())
            self.assertTrue(report['comparison_consistent']);self.assertNotIn('healthy',report)
            self.assertEqual(report['registry_input_format'],'ripe-rest')
            self.assertEqual(report['snapshot_sha256'],digest(source.read_bytes()))
            self.assertNotEqual(report['normalized_snapshot_sha256'],report['snapshot_sha256'])
            self.assertEqual(report['snapshot_observed_at_source'],'operator_supplied')
            self.assertNotIn('PRIVATE',output.getvalue());self.assertNotIn(URL,output.getvalue())
            self.assertEqual({p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()},before)

    def test_cli_format_scope_and_dates_fail_before_config_or_output(self):
        with patch('isp_geofeed_generator.cli.load_config',side_effect=AssertionError('config read')),contextlib.redirect_stderr(io.StringIO()):
            for args in (['publish','--registry-format','ripe-rest'],['generate','--registry-observed-at',STAMP],
                         ['check-registry','--registry-records','missing','--feed','missing','--feed-url',URL,'--registry-format','ripe-rest'],
                         ['check-registry','--registry-records','missing','--feed','missing','--feed-url',URL,'--registry-observed-at',STAMP]):
                self.assertEqual(main(args),1)

    def test_private_mutations_cannot_hide_key_source_or_api_errors(self):
        source=Path(registry_ripe.__file__).read_text(encoding='utf-8')
        controls=[('primary-key','if key_scope != scope:','if False:','test_primary_key_mismatch'),
                  ('source',"if source != 'RIPE':",'if False:','test_invalid_sources'),
                  ('api-messages',"if messages not in ({}, {'errormessage': []}):",'if False:',
                   'test_error_or_warning_does_not_become_comparison')]
        def run(method):
            result=unittest.TestResult();RipeRegistryTests(method).run(result);return result
        for name,find,replacement,method in controls:
            with self.subTest(mutation=name):
                self.assertTrue(run(method).wasSuccessful())
                self.assertEqual(source.count(find),1)
                module=types.ModuleType('isp_geofeed_generator._private_ripe_control')
                module.__package__='isp_geofeed_generator'
                with patch.dict(sys.modules,{module.__name__:module}):
                    exec(compile(source.replace(find,replacement),'<private RIPE control>','exec'),module.__dict__)
                    with patch.object(registry_ripe,'normalize_ripe',module.normalize_ripe):result=run(method)
                self.assertEqual(result.errors,[])
                self.assertGreater(len(result.failures),0)
                self.assertTrue(run(method).wasSuccessful())
                print('RIPE REGISTRY MUTATION OBSERVATION: '+json.dumps({'mutation':name,
                    'assertion_failures':len(result.failures),'errors':len(result.errors),'intact_before_after':True}))
