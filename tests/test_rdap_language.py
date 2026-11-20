"""An explicit language choice must not hide ambiguous or unsafe alternatives."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from isp_geofeed_generator import rdap_language, registry_rdap, registry_batch, registry_check, registry_formats
from isp_geofeed_generator.cli import main
from isp_geofeed_generator.client import GeofeedError, JsonHTTP
from isp_geofeed_generator.credentials import CredentialStore
from isp_geofeed_generator.feed import digest
from test_registry_rdap import network, link, saved, CSV, V6, URL, OTHER, STAMP, NOW
from test_rdap_redaction import entry


def alternatives():
    return [{**link(), 'hreflang': ['en-US', 'en']}, {**link(OTHER), 'hreflang': 'fr'}]


def normalize(links=None, language='en', **changes):
    return registry_rdap.normalize_rdap(saved(network(links=alternatives() if links is None else links, **changes)),
                                        STAMP, rdap_language=language)


class RdapLanguageTests(unittest.TestCase):
    def test_common_language_script_region_tags_are_case_insensitive(self):
        for tag in ('en','EN-us','fr-CA','zh-Hant-TW','es-419','sr-Latn','deu','abcd','abcdefgh-Latn-123'):
            with self.subTest(tag=tag):self.assertEqual(rdap_language.language_tag(tag),tag.lower())

    def test_unsupported_tag_shapes_and_untrusted_values_refuse_without_echo(self):
        for tag in (None,True,1,{},[], '', ' en', 'en ', 'en_US','en-US\nPRIVATE','*','en-*','en,fr',
                    'en;q=1','x-private','i-klingon','de-CH-1996','en-a-foo','en-x-local','zh-cmn-Hans-CN',
                    'en-419-US','en-Latn-Latn','e','abcdefghi','en-İS','en-KK','a'*33):
            with self.subTest(kind=type(tag).__name__):
                with self.assertRaises(GeofeedError) as caught:rdap_language.language_tag(tag)
                self.assertNotIn('PRIVATE',str(caught.exception))

    def test_explicit_choice_is_independent_of_link_order_and_preserves_identity(self):
        for language,url in (('en',URL),('EN-us',URL),('fr',OTHER)):
            before=None
            for links in (alternatives(),list(reversed(alternatives()))):
                data,metadata=normalize(links,language);row=json.loads(data)['objects'][0]
                self.assertEqual(row['geofeed'],url)
                self.assertEqual(metadata['rdap_requested_language'],language.lower())
                self.assertEqual(metadata['rdap_geofeed_link_count'],2)
                self.assertEqual(metadata['rdap_link_selection'],'exact_language')
                self.assertEqual(metadata['rdap_link_status'],'link_returned')
                if before is not None:self.assertEqual(data,before)
                before=data
        first=json.loads(normalize(language='en')[0])['objects'][0]
        second=json.loads(normalize(language='fr')[0])['objects'][0]
        self.assertEqual(first['id'],second['id'])
        self.assertEqual((first['start'],first['end']),(second['start'],second['end']))

    def test_single_string_and_array_labels_support_exact_common_tags(self):
        for labels in ('zh-Hant-TW',['ZH-hant-tw'],['fr','zh-Hant-TW']):
            data,metadata=normalize([{**link(),'hreflang':labels}],'zh-Hant-TW')
            self.assertEqual(json.loads(data)['objects'][0]['geofeed'],URL)
            self.assertEqual(metadata['rdap_requested_language'],'zh-hant-tw')

    def test_default_behavior_never_uses_locale_order_or_response_language(self):
        with patch.dict('os.environ',{'LANG':'fr_FR.UTF-8','LC_ALL':'fr_FR.UTF-8'}):
            for links in (alternatives(),list(reversed(alternatives()))):
                with self.assertRaisesRegex(GeofeedError,'multiple geofeed links'):
                    normalize(links,None,lang='fr')
        for labels in (None,{},['unsupported-extension-tag']):
            _,metadata=normalize([{**link(),'hreflang':labels}],None)
            self.assertEqual(metadata['rdap_link_selection'],'single_link')
            self.assertIsNone(metadata['rdap_requested_language'])
        _,metadata=normalize([link()],None)
        self.assertEqual(metadata['rdap_geofeed_link_count'],1)

    def test_exact_language_never_falls_back_to_a_prefix_or_related_tag(self):
        for requested,offered in (('en','en-US'),('en-CA','en-US'),('zh-Hant','zh-Hant-TW')):
            with self.subTest(requested=requested),self.assertRaisesRegex(GeofeedError,'no unique exact match'):
                normalize([{**link(),'hreflang':offered}],requested)

    def test_duplicate_labels_even_on_unselected_alternatives_refuse(self):
        cases=[([{**link(),'hreflang':['en','EN']}],'en'),
               ([{**link(),'hreflang':['en','fr']},{**link(OTHER),'hreflang':['fr','de']}],'en'),
               ([{**link(),'hreflang':'en'},{**link(),'hreflang':'EN'}],'en'),
               ([{**link(),'hreflang':'en'},{**link(OTHER),'hreflang':'en'}],'en')]
        for links,requested in cases:
            with self.subTest(labels=len(links)),self.assertRaises(GeofeedError):normalize(links,requested)
        # Different declared languages can share a URL. This proves no content language.
        data,_=normalize([{**link(),'hreflang':'en'},{**link(),'hreflang':'fr'}],'fr')
        self.assertEqual(json.loads(data)['objects'][0]['geofeed'],URL)

    def test_missing_malformed_or_unsupported_labels_cannot_be_skipped(self):
        for labels in (None,[],{},True,42,['en',None],['fr','FR'],['de-CH-1996'],'PRIVATE\nVALUE',['fr']*21):
            links=alternatives();links[1]['hreflang']=labels
            with self.subTest(kind=type(labels).__name__),self.assertRaises(GeofeedError):normalize(links)
        with self.assertRaises(GeofeedError):normalize([link()])

    def test_unsafe_unselected_links_are_still_validated_before_selection(self):
        for changes in ({'href':'http://PRIVATE.invalid/feed.csv'}, {'href':None},
                        {'href':'https://user:PRIVATE@example.net/feed.csv'}, {'value':None},
                        {'value':'https://user:PRIVATE@rdap.example/ip/1'}, {'type':'text/html'},
                        {'type':True}, {'rel':None}):
            links=alternatives();links[1].update(changes)
            with self.subTest(field=next(iter(changes))):
                with self.assertRaises(GeofeedError) as caught:normalize(links)
                self.assertNotIn('PRIVATE',str(caught.exception))

    def test_no_match_refuses_but_no_links_preserves_unknown_availability(self):
        with self.assertRaisesRegex(GeofeedError,'no unique exact match'):normalize(language='de')
        for declarations,status in ((['rdap_level_0'],'availability_not_measured'),
                                    (['rdap_level_0','geofeed1'],'not_returned_with_extension')):
            data,metadata=normalize([],rdapConformance=declarations)
            self.assertNotIn('geofeed',json.loads(data)['objects'][0])
            self.assertEqual(metadata['rdap_link_status'],status)
            self.assertEqual(metadata['rdap_link_selection'],'no_link')
            self.assertEqual(metadata['rdap_geofeed_link_count'],0)
            self.assertEqual(metadata['rdap_requested_language'],'en')

    def test_redaction_truncation_and_scope_guards_remain_in_force(self):
        data,metadata=normalize(redacted=[entry()],rdapConformance=['redacted','geofeed1'])
        self.assertEqual(metadata['rdap_ignored_entity_redactions'],1)
        for changes in ({'redacted':[entry('$.links')],'rdapConformance':['redacted']},
                        {'notices':[{'type':'object truncated due to authorization'}]},
                        {'errorCode':429},{'ipVersion':'v6'}):
            with self.subTest(field=next(iter(changes))),self.assertRaises(GeofeedError):normalize(**changes)
        self.assertEqual(json.loads(data)['objects'][0]['end'],'11.22.33.255')

    def test_expected_url_does_not_override_the_explicit_language(self):
        data,_=normalize(language='fr')
        report=registry_check.check_snapshot(data,CSV,URL,now=NOW)
        self.assertFalse(report['comparison_consistent'])
        self.assertEqual(report['coverage']['4']['other_feed'],'256')

    def test_multi_file_selection_preserves_exact_dual_family_coverage_dates_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);feed=root/'feed.csv';feed.write_bytes(CSV+V6)
            paths=[root/'v4.json',root/'v6.json']
            sources=[network(links=alternatives()),network(handle='V6',ipVersion='v6',startAddress='2001:4860:1234::',
                       endAddress='2001:4860:1234::f',links=list(reversed(alternatives())))]
            for path,source in zip(paths,sources):path.write_bytes(saved(source))
            before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()}
            report=registry_batch.check_file_set(paths,feed,URL,input_format='rdap',observed_at=[STAMP,'2021-01-01T00:00:00Z'],rdap_language='EN')
            self.assertEqual(report['coverage']['4']['this_feed'],'256')
            self.assertEqual(report['coverage']['6']['this_feed'],'16')
            self.assertEqual(report['rdap_language_selected_inputs'],2)
            self.assertEqual(report['rdap_requested_language'],'en')
            self.assertEqual(report['snapshot_observed_at'],'2020-01-01T00:00:00+00:00')
            self.assertEqual([v['snapshot_sha256'] for v in report['snapshot_inputs']],[digest(p.read_bytes()) for p in paths])
            self.assertTrue(all(v['rdap_link_selection']=='exact_language' and v['rdap_geofeed_link_count']==2 for v in report['snapshot_inputs']))
            self.assertEqual({p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()},before)
            for field in ('live_registry_read','signature_validation','provider_ingestion'):self.assertEqual(report[field],'not_measured')

    def test_later_file_failure_has_no_partial_report_and_preserves_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);paths=[root/'one.json',root/'two.json'];feed=root/'feed.csv';feed.write_bytes(CSV)
            paths[0].write_bytes(saved(network(links=alternatives())))
            paths[1].write_bytes(saved(network(handle='SECOND',links=[{**link(),'hreflang':'fr'}])))
            (root/'status.json').write_bytes(b'failed status');(root/'before.csv').write_bytes(b'baseline')
            before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()}
            args=['check-registry','--registry-format','rdap','--rdap-language','en','--feed',str(feed),'--feed-url',URL]
            for path in paths:args+=['--registry-records',str(path),'--registry-observed-at',STAMP]
            output=io.StringIO();error=io.StringIO()
            with contextlib.redirect_stdout(output),contextlib.redirect_stderr(error):self.assertEqual(main(args),1)
            self.assertEqual(output.getvalue(),'');self.assertIn('Registry input 2',error.getvalue())
            self.assertNotIn('SECOND',error.getvalue());self.assertNotIn(URL,error.getvalue())
            self.assertEqual({p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()},before)

    def test_single_file_cli_is_read_only_without_config_credentials_or_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);reply=root/'rdap.json';feed=root/'feed.csv'
            reply.write_bytes(saved(network(links=alternatives())));feed.write_bytes(CSV)
            (root/'status.json').write_bytes(b'failed status');(root/'before.csv').write_bytes(b'baseline')
            before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()};output=io.StringIO()
            with patch('isp_geofeed_generator.cli.load_config',side_effect=AssertionError('config read')), \
                 patch.object(CredentialStore,'get',side_effect=AssertionError('credential read')), \
                 patch.object(JsonHTTP,'request',side_effect=AssertionError('HTTP call')), \
                 patch('socket.getaddrinfo',side_effect=AssertionError('DNS lookup')), \
                 patch('urllib.request.urlopen',side_effect=AssertionError('URL open')), \
                 patch('isp_geofeed_generator.cli.atomic_write',side_effect=AssertionError('output write')), \
                 contextlib.redirect_stdout(output):
                self.assertEqual(main(['check-registry','--registry-format','rdap','--rdap-language','EN',
                    '--registry-records',str(reply),'--registry-observed-at',STAMP,'--feed',str(feed),'--feed-url',URL]),0)
            report=json.loads(output.getvalue())
            self.assertTrue(report['comparison_consistent']);self.assertEqual(report['rdap_link_selection'],'exact_language')
            for value in ('PRIVATE',URL,OTHER,str(reply)):self.assertNotIn(value,output.getvalue())
            self.assertEqual({p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()},before)

    def test_mixed_multilingual_and_unlabeled_single_link_files_refuse_as_a_whole(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);feed=root/'feed.csv';feed.write_bytes(CSV)
            paths=[root/'parent.json',root/'child.json']
            paths[0].write_bytes(saved(network(links=alternatives())))
            paths[1].write_bytes(saved(network(handle='CHILD',endAddress='11.22.33.127',links=[link(OTHER)])))
            (root/'status.json').write_bytes(b'failed status');(root/'before.csv').write_bytes(b'baseline')
            before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()}
            common=['check-registry','--registry-format','rdap','--feed',str(feed),'--feed-url',URL]
            records=[['--registry-records',str(path),'--registry-observed-at',STAMP] for path in paths]
            output=io.StringIO();error=io.StringIO()
            with contextlib.redirect_stdout(output),contextlib.redirect_stderr(error):
                self.assertEqual(main(common+records[0]+records[1]+['--rdap-language','en']),1)
            self.assertEqual(output.getvalue(),'');self.assertIn('Registry input 2',error.getvalue())
            self.assertIn('hreflang labels',error.getvalue())
            # Separate reports are possible, but neither is the combined hierarchy.
            output=io.StringIO()
            with contextlib.redirect_stdout(output):self.assertEqual(main(common+records[0]+['--rdap-language','en']),0)
            self.assertEqual(json.loads(output.getvalue())['coverage']['4']['this_feed'],'256')
            output=io.StringIO()
            with contextlib.redirect_stdout(output):self.assertEqual(main(common+records[1]),1)
            self.assertEqual(json.loads(output.getvalue())['coverage']['4']['other_feed'],'128')
            self.assertEqual({p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()},before)

    def test_language_option_cannot_reach_other_formats_or_publication(self):
        with patch('isp_geofeed_generator.cli.load_config',side_effect=AssertionError('config read')), \
             patch.object(registry_check,'read_output',side_effect=AssertionError('input read')), \
             patch.object(registry_batch,'read_output',side_effect=AssertionError('input read')):
            for kind in ('normalized','ripe-rest'):
                with self.subTest(kind=kind),self.assertRaisesRegex(GeofeedError,'requires --registry-format rdap'):
                    registry_batch.check_file_set(['absent'],'absent',URL,input_format=kind,rdap_language='en')
                with self.assertRaises(GeofeedError):registry_check.check_files('absent','absent',URL,input_format=kind,rdap_language='en')
                with self.assertRaises(GeofeedError):registry_formats.normalize_input(b'',kind,None,rdap_language='en')
            for command in ('publish','generate','recover-local'):
                error=io.StringIO()
                with contextlib.redirect_stderr(error):self.assertEqual(main([command,'--rdap-language','en']),1)
                self.assertIn('require check-registry',error.getvalue())
            with self.assertRaises(GeofeedError):registry_batch.check_file_set(['absent'],'absent',URL,input_format='rdap',rdap_language='PRIVATE\nVALUE')

    def test_language_lists_and_tag_lengths_are_bounded_without_truncation(self):
        tags=['a'+chr(code) for code in range(ord('a'),ord('a')+20)]
        self.assertEqual(len(tags),20)
        self.assertEqual(json.loads(normalize([{**link(),'hreflang':tags}],'aa')[0])['objects'][0]['geofeed'],URL)
        with self.assertRaises(GeofeedError):normalize([{**link(),'hreflang':tags+['ba']}],'aa')
        with patch.object(rdap_language,'MAX_TAG',2):
            self.assertEqual(rdap_language.language_tag('EN'),'en')
            with self.assertRaises(GeofeedError):rdap_language.language_tag('en-US')

    def test_private_guard_removals_fail_assertions_with_intact_controls(self):
        controls=[('exact-match',rdap_language,'if requested in tags:',
                   'if requested.split("-")[0] in {tag.split("-")[0] for tag in tags}:',
                   'test_exact_language_never_falls_back_to_a_prefix_or_related_tag'),
                  ('all-labels',rdap_language,'if len(set(tags)) != len(tags) or seen.intersection(tags):','if False:',
                   'test_duplicate_labels_even_on_unselected_alternatives_refuse'),
                  ('all-links',registry_rdap,'for link in links:','for link in links[:1]:',
                   'test_unsafe_unselected_links_are_still_validated_before_selection')]
        def run(method):
            result=unittest.TestResult();RdapLanguageTests(method).run(result);return result
        for name,target,find,replacement,method in controls:
            with self.subTest(mutation=name):
                self.assertTrue(run(method).wasSuccessful())
                text=Path(target.__file__).read_text(encoding='utf-8');self.assertEqual(text.count(find),1)
                module=types.ModuleType('isp_geofeed_generator._private_language_control');module.__package__='isp_geofeed_generator'
                with patch.dict(sys.modules,{module.__name__:module}):
                    exec(compile(text.replace(find,replacement),'<private language control>','exec'),module.__dict__)
                    attribute='normalize_rdap' if target is registry_rdap else 'select_language'
                    with patch.object(registry_rdap,attribute,getattr(module,attribute)):result=run(method)
                self.assertEqual(result.errors,[]);self.assertGreater(len(result.failures),0)
                self.assertTrue(run(method).wasSuccessful())
                print('RDAP LANGUAGE MUTATION OBSERVATION: '+json.dumps({'mutation':name,
                    'assertion_failures':len(result.failures),'errors':0,'intact_before_after':True}))
