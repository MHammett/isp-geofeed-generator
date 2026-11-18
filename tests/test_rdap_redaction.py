"""Redaction acceptance needs a complete syntax proof inside ignored entity data."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from isp_geofeed_generator import rdap_redaction, registry_rdap, registry_batch
from isp_geofeed_generator.cli import main
from isp_geofeed_generator.client import GeofeedError, JsonHTTP
from isp_geofeed_generator.credentials import CredentialStore
from test_registry_rdap import network, saved, CSV, URL, STAMP, normalize

CONTACT="$.entities[?(@.handle=='EXAMPLE-1')].vcardArray[1][?(@[0]=='email')]"


def entry(path=CONTACT, **changes):
    return {'name':{'description':'PRIVATE logical contact field'},'prePath':path,**changes}


def source(rows=None):
    return network(rdapConformance=['rdap_level_0','geofeed1','redacted'],
                   redacted=[entry()] if rows is None else rows)


class RdapRedactionTests(unittest.TestCase):
    def test_rooted_entity_members_indices_and_filters_are_parsed_as_syntax(self):
        for path in (CONTACT,"$['entities'][0]['vcardArray'][1][0]",'$.entities',
                     '$["entities"][*].vcardArray[1][?(@[0]=="fn")][3]',
                     "$.entities[?@.roles[0]=='technical'].vcardArray[1]",
                     '$.entities[0].vcardArray[1][0][3][:3]', '$.entities[0].vcardArray[1:]',
                     '$.entities[:].vcardArray', '$.entities[0]["__class__"]'):
            with self.subTest(path=path):
                steps=rdap_redaction.contact_path(path)
                self.assertEqual(steps[0],('member','entities'))
                self.assertTrue(all(step[0] in ('member','index','slice','filter','wildcard') for step in steps))

    def test_all_methods_keep_every_declared_target_inside_entities(self):
        rows=[entry(),{'name':{'type':'Example'},'postPath':CONTACT+'[3]','method':'emptyValue'},
              {'name':{'description':'ignored'},'postPath':CONTACT+'[3]','method':'partialValue'},
              {'name':{'description':'ignored'},'postPath':CONTACT+'[3]','method':'replacementValue'},
              entry(method='replacementValue',replacementPath="$.entities[0].vcardArray[1][0]"),
              {'name':{'type':'Example'},'postPath':CONTACT,'replacementPath':CONTACT+'[3]','method':'replacementValue'}]
        self.assertEqual(rdap_redaction.validate_redactions(source(rows)),6)

    def test_discovery_bytes_and_ids_are_unchanged_by_accepted_redaction(self):
        original,_=normalize(network())
        candidate,metadata=normalize(source([entry()]*12))
        self.assertEqual(candidate,original)
        self.assertEqual(metadata['rdap_ignored_entity_redactions'],12)
        self.assertEqual(metadata['rdap_redaction_status'],'ignored_entities_only')
        self.assertEqual(metadata['rdap_link_status'],'link_returned')
        self.assertNotIn('PRIVATE',json.dumps(metadata))
        self.assertNotIn(CONTACT,json.dumps(metadata))
        self.assertNotIn('EXAMPLE-1',json.dumps(metadata))

    def test_scope_bounds_identity_links_and_ancestor_redaction_still_refuse(self):
        for path in ('$', '$.startAddress', '$.endAddress', '$.ipVersion', '$.handle', '$.links',
                     '$.links[0].href', '$.rdapConformance', '$.notices', '$.entitiesOther',
                     "$['entities','links']", '$[*]', '$..entities'):
            with self.subTest(path=path),self.assertRaises(GeofeedError):normalize(source([entry(path)]))

    def test_every_replacement_path_is_checked_not_only_the_first_path(self):
        for path in ('$.links', '$.startAddress', '$.handle'):
            with self.subTest(path=path),self.assertRaises(GeofeedError):
                normalize(source([entry(method='replacementValue',replacementPath=path)]))
        with self.assertRaises(GeofeedError):
            normalize(source([{'name':{'type':'Example'},'postPath':'$.links',
                               'replacementPath':CONTACT,'method':'replacementValue'}]))

    def test_trailing_root_or_current_queries_cannot_escape_the_parsed_path(self):
        for path in ('$.entities $.links', '$.entities @.handle', '$.entities $["links"]',
                     '$.entities[0]$.startAddress'):
            with self.subTest(path=path),self.assertRaises(GeofeedError):normalize(source([entry(path)]))

    def test_broad_recursive_function_and_mixed_expressions_remain_unsupported(self):
        for path in ('$.entities..links', '$.entities[0]^', '$.entities[0,-1]', '$.entities[-1]',
                     '$.entities[0:9:2]', "$.entities[?(@.handle=='x'||$.handle=='y')]",
                     '$.entities[?length(@.handle)=="x"]', '$.entities[?($.links=="x")]',
                     '$.entities[?(@.handle=~".*")]', '$.entities[?(@.handle>"x")]',
                     '$.entities[?(@.handle=="x")].vcardArray;system("PRIVATE")',
                     '$.entities[?(@.roles[*]=="x")]', '$.entities[?(@.roles[:]=="x")]',
                     '$["entit\\u0069es"]', '$.entities.foo-bar', '$. entities', '$.entities. child'):
            with self.subTest(path=path),self.assertRaises(GeofeedError):normalize(source([entry(path)]))

    def test_quoted_filter_constants_cannot_become_path_or_code(self):
        for literal in ('"$.links"', '"X]$.handle"', r'"X\" ] $.links"', "'https://PRIVATE.invalid/no-fetch'"):
            path='$.entities[?(@.handle=='+literal+')].vcardArray'
            self.assertEqual(rdap_redaction.validate_redactions(source([entry(path)])),1)

    def test_structural_metadata_is_required_and_human_names_do_not_choose_scope(self):
        bad=[None,{}, {'name':'PRIVATE','prePath':CONTACT}, {'prePath':CONTACT},
             entry(pathLang='javascript'),entry(method='PRIVATE'), entry(extraPath='$.links'),
             entry(postPath=CONTACT),entry(method='emptyValue'),entry(method='partialValue'),
             entry(method='replacementValue'),entry(replacementPath=CONTACT),entry(reason='PRIVATE'),
             entry(prePath=None),entry(prePath=''),entry(prePath=42),entry(name={'type':None}),
             entry(name={}),entry(name={'description':''}),entry(name={'type':'x','extra':'y'}),
             entry(reason={}),entry(reason={'description':['PRIVATE']}),entry(name={'type':'x'*1025})]
        for row in bad:
            with self.subTest(row=row),self.assertRaises(GeofeedError) as caught:normalize(source([row]))
            self.assertNotIn('PRIVATE',str(caught.exception))
            self.assertNotIn(CONTACT,str(caught.exception))
        # Labels cannot convert a discovery field into an ignored contact field.
        with self.assertRaises(GeofeedError):normalize(source([entry('$.links',name={'description':'Safe contact only'})]))

    def test_missing_redaction_declaration_and_empty_or_oversize_containers_refuse(self):
        for rows in (None,[],{},[entry()]*101):
            bad=source();bad['redacted']=rows
            with self.subTest(kind=type(rows).__name__),self.assertRaises(GeofeedError):normalize(bad)
        bad=source();bad['rdapConformance']=['rdap_level_0','geofeed1']
        with self.assertRaises(GeofeedError):normalize(bad)
        self.assertEqual(rdap_redaction.validate_redactions(network()),0)

    def test_path_token_literal_and_numeric_budgets_are_enforced(self):
        for path in ('$.entities'+'.x'*1024,'$.entities'+'.x'*128,
                     "$.entities[?(@.handle=='"+'x'*257+"')]",'$.entities[1234567]',
                     '$.entities[00]','$.entities\n.x','$.entities\x7f.x'):
            with self.subTest(length=len(path)),self.assertRaises(GeofeedError):normalize(source([entry(path)]))
        with patch.object(rdap_redaction,'MAX_TOKENS',3):
            self.assertEqual(rdap_redaction.validate_redactions(source([entry('$.entities')])),1)
            with self.assertRaises(GeofeedError):normalize(source([entry('$.entities[*]')]))
        self.assertEqual(rdap_redaction.validate_redactions(source([entry()]*100)),100)

    def test_contact_scope_does_not_override_error_or_truncation(self):
        for extra in ({'errorCode':400},{'notices':[{'type':'object truncated due to authorization'}]}):
            value=source();value.update(extra)
            with self.subTest(extra=extra),self.assertRaises(GeofeedError):normalize(value)

    def test_unknown_link_availability_survives_contact_redaction(self):
        value=source();value['links']=[];value['rdapConformance']=['rdap_level_0','redacted']
        _,metadata=normalize(value)
        self.assertEqual(metadata['rdap_link_status'],'availability_not_measured')
        self.assertEqual(metadata['rdap_ignored_entity_redactions'],1)

    def test_cli_preserves_files_and_does_not_execute_paths_or_read_other_sources(self):
        # Guard the parser itself. Patching exec around the whole CLI would
        # also block Python's unrelated lazy module imports.
        with patch('builtins.eval',side_effect=AssertionError('path evaluation')), \
             patch('builtins.exec',side_effect=AssertionError('path execution')):
            self.assertEqual(rdap_redaction.validate_redactions(source()),1)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);reply=root/'source.json';feed=root/'feed.csv';state=root/'status.json'
            reply.write_bytes(saved(source()));feed.write_bytes(CSV);state.write_bytes(b'failed status')
            before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()}
            output=io.StringIO()
            with patch('isp_geofeed_generator.cli.load_config',side_effect=AssertionError('config read')), \
                 patch.object(CredentialStore,'get',side_effect=AssertionError('credential read')), \
                 patch.object(JsonHTTP,'request',side_effect=AssertionError('HTTP call')), \
                 patch('socket.getaddrinfo',side_effect=AssertionError('DNS lookup')), \
                 patch('builtins.eval',side_effect=AssertionError('path evaluation')), \
                 patch('isp_geofeed_generator.cli.atomic_write',side_effect=AssertionError('output write')), \
                 contextlib.redirect_stdout(output):
                self.assertEqual(main(['check-registry','--registry-format','rdap','--registry-records',str(reply),
                    '--registry-observed-at',STAMP,'--feed',str(feed),'--feed-url',URL]),0)
            report=json.loads(output.getvalue())
            self.assertTrue(report['comparison_consistent'])
            self.assertEqual(report['rdap_redaction_status'],'ignored_entities_only')
            self.assertNotIn('PRIVATE',output.getvalue());self.assertNotIn(CONTACT,output.getvalue())
            self.assertEqual({p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()},before)

    def test_mixed_later_redaction_refuses_whole_set_without_partial_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);paths=[root/(str(i)+'.json') for i in (1,2)];feed=root/'feed.csv';feed.write_bytes(CSV)
            first=source();second=source([entry(),entry('$.links')]);second['handle']='SECOND'
            for path,value in zip(paths,(first,second)):path.write_bytes(saved(value))
            before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()}
            output=io.StringIO();error=io.StringIO()
            args=['check-registry','--registry-format','rdap','--feed',str(feed),'--feed-url',URL]
            for path in paths:args+=['--registry-records',str(path),'--registry-observed-at',STAMP]
            with contextlib.redirect_stdout(output),contextlib.redirect_stderr(error):self.assertEqual(main(args),1)
            self.assertEqual(output.getvalue(),'');self.assertIn('Registry input 2',error.getvalue())
            self.assertNotIn('$.links',error.getvalue())
            self.assertEqual({p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()},before)

    def test_private_guard_removals_are_caught_with_intact_controls_before_and_after(self):
        text=Path(rdap_redaction.__file__).read_text(encoding='utf-8')
        controls=[('entity-root',"if not steps or steps[0] != ('member', 'entities'):",'if False:',
                   'test_scope_bounds_identity_links_and_ancestor_redaction_still_refuse'),
                  ('full-path','if self.position != len(self.tokens):','if False:',
                   'test_trailing_root_or_current_queries_cannot_escape_the_parsed_path'),
                  ('all-targets','for key in paths:','for key in paths[:1]:',
                   'test_every_replacement_path_is_checked_not_only_the_first_path')]
        def run(method):
            result=unittest.TestResult();RdapRedactionTests(method).run(result);return result
        for name,find,replacement,method in controls:
            with self.subTest(mutation=name):
                self.assertTrue(run(method).wasSuccessful());self.assertEqual(text.count(find),1)
                module=types.ModuleType('isp_geofeed_generator._private_redaction_control');module.__package__='isp_geofeed_generator'
                with patch.dict(sys.modules,{module.__name__:module}):
                    exec(compile(text.replace(find,replacement),'<private redaction control>','exec'),module.__dict__)
                    with patch.object(registry_rdap,'validate_redactions',module.validate_redactions):result=run(method)
                self.assertEqual(result.errors,[]);self.assertGreater(len(result.failures),0)
                self.assertTrue(run(method).wasSuccessful())
                print('RDAP REDACTION MUTATION OBSERVATION: '+json.dumps({'mutation':name,
                    'assertion_failures':len(result.failures),'errors':0,'intact_before_after':True}))
