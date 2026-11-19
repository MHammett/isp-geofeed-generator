"""RDAP discovery uses exact network scopes and never invents absent capability."""
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

from isp_geofeed_generator import registry_rdap, registry_batch, registry_check
from isp_geofeed_generator.cli import main
from isp_geofeed_generator.client import GeofeedError, JsonHTTP
from isp_geofeed_generator.credentials import CredentialStore
from isp_geofeed_generator.feed import digest

URL='https://example.net/feed.csv'
OTHER='https://other.example/feed.csv'
STAMP='2020-01-01T00:00:00Z'
NOW=datetime(2026,11,18,tzinfo=timezone.utc)
CSV=b'11.22.33.0/24,US,US-IL,Example City,\r\n'
V6=b'2001:4860:1234::/124,US,US-IL,Example City,\r\n'


def link(url=URL):
    return {'value':'https://rdap.example/ip/11.22.33.0/24','rel':'geofeed','href':url,
            'type':'application/geofeed+csv'}


def network(**changes):
    return {'objectClassName':'ip network','handle':'PRIVATE-HANDLE','startAddress':'11.22.33.0',
            'endAddress':'11.22.33.255','ipVersion':'v4','rdapConformance':['rdap_level_0','geofeed1'],
            'links':[link()],'country':'NL','name':'PRIVATE-NAME',
            'entities':[{'vcardArray':['vcard',[['email',{},'text','PRIVATE@example.net']]]}],**changes}


def saved(source):return json.dumps(source).encode()


def normalize(source):return registry_rdap.normalize_rdap(saved(source),STAMP)


def compare(source,csv=CSV):
    data,metadata=normalize(source)
    return registry_check.check_snapshot(data,csv,URL,now=NOW),metadata


class RdapRegistryTests(unittest.TestCase):
    def test_exact_inclusive_ipv4_range_and_safe_normalized_identity(self):
        source=network(startAddress='11.22.33.1',endAddress='11.22.33.254')
        data,metadata=normalize(source);row=json.loads(data)['objects'][0]
        self.assertEqual((row['start'],row['end']),('11.22.33.1','11.22.33.254'))
        self.assertRegex(row['id'],r'^rdap:[a-f0-9]{64}$')
        self.assertNotIn('PRIVATE',data.decode());self.assertNotIn('country',data.decode())
        report=registry_check.check_snapshot(data,CSV,URL,now=NOW)
        self.assertEqual(report['coverage']['4']['this_feed'],'254')
        self.assertEqual(report['coverage']['4']['unreferenced'],'2')
        self.assertTrue(metadata['rdap_geofeed1_advertised'])
        self.assertEqual(metadata['rdap_link_status'],'link_returned')

    def test_ipv6_ranges_are_canonicalized_without_widening(self):
        source=network(startAddress='2001:4860:1234:0:0:0:0:1',endAddress='2001:4860:1234::e',ipVersion='v6')
        data,_=normalize(source);row=json.loads(data)['objects'][0]
        self.assertEqual(row['start'],'2001:4860:1234::1')
        report=registry_check.check_snapshot(data,V6,URL,now=NOW)
        self.assertEqual(report['coverage']['6']['this_feed'],'14')
        self.assertEqual(report['coverage']['6']['unreferenced'],'2')

    def test_link_is_allowed_without_the_optional_extension_advertisement(self):
        for declarations in (None,[],['rdap_level_0']):
            source=network(rdapConformance=declarations)
            if declarations is None:del source['rdapConformance']
            with self.subTest(declarations=declarations):
                report,metadata=compare(source)
                self.assertTrue(report['comparison_consistent'])
                self.assertFalse(metadata['rdap_geofeed1_advertised'])
                self.assertEqual(metadata['rdap_link_status'],'link_returned')

    def test_recommended_media_type_is_not_mandatory(self):
        source=network();del source['links'][0]['type']
        self.assertTrue(compare(source)[0]['comparison_consistent'])
        for relation in ('GEOFEED','alternate geofeed','geofeed alternate',' geofeed '):
            source['links'][0]['rel']=relation
            self.assertTrue(compare(source)[0]['comparison_consistent'])
        source['links'][0]['rel']='not-geofeed'
        self.assertFalse(compare(source)[0]['comparison_consistent'])

    def test_absence_without_extension_is_unknown_availability(self):
        report,metadata=compare(network(links=[],rdapConformance=['rdap_level_0']))
        self.assertEqual(metadata['rdap_link_status'],'availability_not_measured')
        self.assertFalse(metadata['rdap_geofeed1_advertised'])
        self.assertFalse(report['comparison_consistent'])
        self.assertEqual(report['coverage']['4']['unreferenced'],'256')
        self.assertNotIn('healthy',report)

    def test_declared_extension_without_a_link_has_separate_metadata(self):
        report,metadata=compare(network(links=[]))
        self.assertEqual(metadata['rdap_link_status'],'not_returned_with_extension')
        self.assertTrue(metadata['rdap_geofeed1_advertised'])
        self.assertEqual(report['coverage']['4']['unreferenced'],'256')

    def test_nested_contacts_and_remarks_do_not_supply_network_references(self):
        source=network(links=[{'rel':'self','href':'https://PRIVATE.invalid/never-fetch'}],
                       remarks=[{'description':[f'Geofeed {URL}']}],
                       entities=[{'links':[link()],'networks':[network()]}])
        report,metadata=compare(source)
        self.assertFalse(report['comparison_consistent'])
        self.assertEqual(report['registry_objects'],1)
        self.assertEqual(metadata['rdap_link_status'],'not_returned_with_extension')

    def test_invalid_network_class_handle_and_family_are_refused(self):
        for changes in ({'objectClassName':'domain'},{'handle':None},{'handle':'PRIVATE\nVALUE'},
                        {'startAddress':'11.22.33.255','endAddress':'11.22.33.0'},
                        {'endAddress':'2001:4860:1234::f'},{'ipVersion':'v6'},
                        {'startAddress':'fe80::1%PRIVATE'},{'startAddress':'011.22.33.0'}):
            with self.subTest(changes=changes),self.assertRaises(GeofeedError):normalize(network(**changes))

    def test_truncated_notices_and_remarks_stop_before_comparison(self):
        for key in ('notices','remarks'):
            for kind in ('result set truncated due to authorization','object truncated due to excessive load',
                         'object truncated due to unexplainable reasons'):
                with self.subTest(key=key,kind=kind),self.assertRaisesRegex(GeofeedError,'reports truncation'):
                    normalize(network(**{key:[{'type':kind,'description':['PRIVATE']}]}))
        self.assertTrue(compare(network(notices=[{'title':'Terms','description':['PRIVATE']}]))[0]['comparison_consistent'])

    def test_errors_and_explicit_redaction_are_not_partial_success(self):
        for changes in ({'errorCode':429},{'errorCode':None},{'redacted':[]},{'redacted':[{'name':'PRIVATE'}]},
                        {'notices':None},{'remarks':[None]}):
            with self.subTest(changes=changes),self.assertRaises(GeofeedError) as caught:
                normalize(network(**changes))
            self.assertNotIn('PRIVATE',str(caught.exception))
            if 'redacted' in changes:self.assertIn('not supported by this reader',str(caught.exception))
            if 'errorCode' in changes:self.assertIn('error response',str(caught.exception))

    def test_policy_truncation_with_a_returned_link_refuses_the_whole_set(self):
        # Sanitized NIC.br shape from Claude's #96 review. Keep the valid link.
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);feed=root/'feed.csv';feed.write_bytes(CSV)
            paths=[root/'one.json',root/'two.json']
            paths[0].write_bytes(saved(network()))
            paths[1].write_bytes(saved(network(handle='SECOND',startAddress='11.22.34.0',endAddress='11.22.34.255',
                remarks=[{'type':'object truncated due to server policy','description':['PRIVATE data removed by policy']}])) )
            (root/'status.json').write_bytes(b'failed status');(root/'before.csv').write_bytes(b'baseline')
            before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()}
            self.assertTrue(registry_batch.check_file_set(paths[:1],feed,URL,input_format='rdap',observed_at=[STAMP])['comparison_consistent'])
            args=['check-registry','--registry-format','rdap','--feed',str(feed),'--feed-url',URL]
            for path in paths:args+=['--registry-records',str(path),'--registry-observed-at',STAMP]
            output=io.StringIO();error=io.StringIO()
            with contextlib.redirect_stdout(output),contextlib.redirect_stderr(error):self.assertEqual(main(args),1)
            self.assertEqual(output.getvalue(),'');self.assertIn('Registry input 2',error.getvalue())
            self.assertIn('reports truncation',error.getvalue());self.assertNotIn('PRIVATE',error.getvalue())
            self.assertEqual(error.getvalue().count('no partial comparison made'),1)
            self.assertEqual({p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()},before)

    def test_unsafe_or_unsupported_geofeed_links_are_not_dropped(self):
        for changes in ({'value':None},{'value':'https://user:PRIVATE@rdap.example/ip/1'},
                        {'value':'https://rdap.example:PRIVATE/ip/1'},{'href':'http://example.net/feed.csv'},
                        {'href':'https://user:PRIVATE@example.net/feed.csv'},{'href':'https://example.net/\nPRIVATE'},
                        {'href':None},{'rel':None},{'rel':' '},{'type':'text/html'},{'type':True}):
            source=network();source['links'][0].update(changes)
            with self.subTest(changes=changes),self.assertRaises(GeofeedError) as caught:normalize(source)
            self.assertNotIn('PRIVATE',str(caught.exception))
        for links in (None,{},[None],[link()]*201):
            with self.subTest(links=str(links)[:10]),self.assertRaises(GeofeedError):normalize(network(links=links))

    def test_multiple_links_do_not_silently_choose_a_language_or_first_url(self):
        for url in (URL,OTHER):
            with self.subTest(url=url),self.assertRaisesRegex(GeofeedError,'multiple geofeed links'):
                normalize(network(links=[{**link(),'hreflang':['en']},{**link(url),'hreflang':['fr']}]))

    def test_json_and_conformance_limits_are_bounded(self):
        for data in (b'NaN',b'{"PRIVATE":1e10000}',b'{"objectClassName":1,"objectClassName":2}',
                     b'\xff',b'['*1100,b'x'*8_000_001):
            with self.subTest(size=len(data)),self.assertRaises(GeofeedError) as caught:
                registry_rdap.normalize_rdap(data,STAMP)
            self.assertNotIn('PRIVATE',str(caught.exception))
        for declarations in (None,{},['geofeed1']*2,[None],['x']*101,['PRIVATE\nVALUE']):
            with self.subTest(declarations=declarations),self.assertRaises(GeofeedError):
                normalize(network(rdapConformance=declarations))

    def test_hashed_identity_tracks_handle_and_exact_scope_not_contact_text(self):
        first,_=normalize(network());second,_=normalize(network(country='DE',entities=[],name='other'))
        self.assertEqual(first,second)
        third,_=normalize(network(handle='OTHER'))
        self.assertNotEqual(json.loads(first)['objects'][0]['id'],json.loads(third)['objects'][0]['id'])

    def test_file_set_preserves_dates_parent_precedence_and_unknown_absence(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);feed=root/'feed.csv';feed.write_bytes(CSV)
            paths=[root/(str(i)+'.json') for i in range(3)]
            sources=[network(handle='PARENT',links=[link(OTHER)]),
                     network(handle='CHILD',endAddress='11.22.33.127'),
                     network(handle='GRANDCHILD',endAddress='11.22.33.63',links=[],rdapConformance=['rdap_level_0'])]
            for path,source in zip(paths,sources):path.write_bytes(saved(source))
            result=registry_batch.check_file_set(paths,feed,URL,input_format='rdap',observed_at=[STAMP]*3)
            self.assertEqual(result['coverage']['4']['this_feed'],'128')
            self.assertEqual(result['coverage']['4']['other_feed'],'128')
            self.assertEqual(result['rdap_geofeed1_advertised_inputs'],2)
            self.assertEqual(result['rdap_linked_inputs'],2)
            self.assertEqual(result['rdap_absence_unknown_inputs'],1)
            self.assertEqual(result['snapshot_inputs'][2]['rdap_link_status'],'availability_not_measured')
            for field in ('live_registry_read','signature_validation','provider_ingestion'):
                self.assertEqual(result[field],'not_measured')
            # Reversing arguments keeps scope selection, not a first-file winner.
            self.assertEqual(registry_batch.check_file_set(list(reversed(paths)),feed,URL,input_format='rdap',
                observed_at=[STAMP]*3)['coverage'],result['coverage'])
            paths[1].write_bytes(paths[0].read_bytes())
            with self.assertRaisesRegex(GeofeedError,'unique safe IDs'):
                registry_batch.check_file_set(paths,feed,URL,input_format='rdap',observed_at=[STAMP]*3)

    def test_single_file_cli_preserves_hashes_and_has_no_other_access(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'PRIVATE.json';feed=root/'feed.csv';status=root/'status.json'
            source.write_bytes(saved(network()));feed.write_bytes(CSV);status.write_bytes(b'failed')
            before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()}
            output=io.StringIO()
            with patch('isp_geofeed_generator.cli.load_config',side_effect=AssertionError('config read')), \
                 patch.object(CredentialStore,'get',side_effect=AssertionError('credential read')), \
                 patch.object(JsonHTTP,'request',side_effect=AssertionError('HTTP request')), \
                 patch('socket.getaddrinfo',side_effect=AssertionError('DNS lookup')), \
                 patch('urllib.request.urlopen',side_effect=AssertionError('URL open')), \
                 patch('isp_geofeed_generator.cli.atomic_write',side_effect=AssertionError('output write')), \
                 contextlib.redirect_stdout(output):
                self.assertEqual(main(['check-registry','--config',str(root/'absent.yaml'),'--registry-format','rdap',
                    '--registry-records',str(source),'--registry-observed-at',STAMP,'--feed',str(feed),'--feed-url',URL]),0)
            report=json.loads(output.getvalue())
            self.assertTrue(report['comparison_consistent'])
            self.assertEqual(report['registry_input_format'],'rdap')
            self.assertEqual(report['registry_source'],'operator_supplied_rdap')
            self.assertEqual(report['snapshot_sha256'],digest(source.read_bytes()))
            self.assertNotIn('PRIVATE',output.getvalue());self.assertNotIn(URL,output.getvalue())
            self.assertNotIn('healthy',report)
            self.assertEqual({p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()},before)

    def test_cli_future_date_missing_dates_and_invalid_later_file_leave_no_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'one.json';source.write_bytes(saved(network()))
            feed=root/'feed.csv';feed.write_bytes(CSV);bad=root/'two.json';bad.write_bytes(saved(network(errorCode=429)))
            args=['check-registry','--registry-format','rdap','--feed',str(feed),'--feed-url',URL,'--registry-records',str(source)]
            before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()}
            for extra in ([],['--registry-observed-at','2999-01-01T00:00:00Z'],
                          ['--registry-observed-at',STAMP,'--registry-records',str(bad),'--registry-observed-at',STAMP]):
                output=io.StringIO();error=io.StringIO()
                with contextlib.redirect_stdout(output),contextlib.redirect_stderr(error):self.assertEqual(main(args+extra),1)
                self.assertEqual(output.getvalue(),'')
                self.assertEqual({p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()},before)

    def test_private_mutations_cannot_hide_multiple_links_truncation_or_unknown_absence(self):
        source=Path(registry_rdap.__file__).read_text(encoding='utf-8')
        controls=[('multiple-links','if len(references) > 1:','if False:',
                   'test_multiple_links_do_not_silently_choose_a_language_or_first_url'),
                  ('truncation',"if kind.lower().startswith(('result set truncated', 'object truncated')):",'if False:',
                   'test_truncated_notices_and_remarks_stop_before_comparison'),
                  ('absence',"else 'availability_not_measured'","else 'not_returned_with_extension'",
                   'test_absence_without_extension_is_unknown_availability')]
        def run(method):
            result=unittest.TestResult();RdapRegistryTests(method).run(result);return result
        for name,find,replacement,method in controls:
            with self.subTest(mutation=name):
                self.assertTrue(run(method).wasSuccessful());self.assertEqual(source.count(find),1)
                module=types.ModuleType('isp_geofeed_generator._private_rdap_control');module.__package__='isp_geofeed_generator'
                with patch.dict(sys.modules,{module.__name__:module}):
                    exec(compile(source.replace(find,replacement),'<private RDAP control>','exec'),module.__dict__)
                    with patch.object(registry_rdap,'normalize_rdap',module.normalize_rdap):result=run(method)
                self.assertEqual(result.errors,[]);self.assertGreater(len(result.failures),0)
                self.assertTrue(run(method).wasSuccessful())
                print('RDAP REGISTRY MUTATION OBSERVATION: '+json.dumps({'mutation':name,
                    'assertion_failures':len(result.failures),'errors':0,'intact_before_after':True}))
