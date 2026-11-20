"""RFC 9535 quoted-string vectors must pass before entity-only scope is accepted."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from isp_geofeed_generator import rdap_redaction, registry_rdap
from isp_geofeed_generator.cli import main
from isp_geofeed_generator.client import GeofeedError
from test_registry_rdap import saved, network, normalize, CSV, URL, STAMP
from test_rdap_redaction import source, entry

BACKSLASH=chr(92)


def quoted(quote,body):return quote+body+quote


def paths(token):return ('$.entities['+token+']','$.entities[?(@.handle=='+token+')]')


class RdapStringLiteralTests(unittest.TestCase):
    def test_valid_quote_escapes_and_unicode_scalars_still_work(self):
        for quote in ('"',"'"):
            other="'" if quote=='"' else '"'
            bodies=['','plain',other,BACKSLASH+quote,BACKSLASH+BACKSLASH,
                    *[BACKSLASH+letter for letter in '/bfnrt'],
                    r'\u0000',r'\uD7FF',r'\uE000',r'\uffff',r'\uD800\uDC00',r'\udbff\udfff',
                    chr(0xD7FF),chr(0xE000),chr(0x10000),chr(0x10FFFF),'café']
            for index,body in enumerate(bodies):
                for path in paths(quoted(quote,body)):
                    with self.subTest(quote=quote,vector=index):
                        self.assertEqual(normalize(source([entry(path)]))[1]['rdap_ignored_entity_redactions'],1)

    def test_refuses_opposite_quote_escapes(self):
        for quote,other in (('"',"'"),("'",'"')):
            for index,path in enumerate(paths(quoted(quote,'before'+BACKSLASH+other+'after'))):
                with self.subTest(quote=quote,position=index):
                    with self.assertRaises(GeofeedError):normalize(source([entry(path)]))

    def test_refuses_raw_surrogate_code_points(self):
        for value in (0xD800,0xDBFF,0xDC00,0xDFFF):
            for quote in ('"',"'"):
                for index,path in enumerate(paths(quoted(quote,'before'+chr(value)+'after'))):
                    with self.subTest(codepoint=value,quote=quote,position=index):
                        with self.assertRaises(GeofeedError):normalize(source([entry(path)]))

    def test_refuses_lone_reversed_separated_and_malformed_surrogate_escapes(self):
        invalid=(r'\uD800',r'\uDBFF',r'\uDC00',r'\uDFFF',r'\uDC00\uD800',r'\uD800\u0041',
                 r'\uD800x\uDC00',r'\uD800\\uDC00',r'\uD800\uD800',r'\uDBFF\uE000',r'\uD800\uDC00\uDC00')
        for vector,body in enumerate(invalid):
            for quote in ('"',"'"):
                for index,path in enumerate(paths(quoted(quote,body))):
                    with self.subTest(vector=vector,quote=quote,position=index):
                        with self.assertRaises(GeofeedError):normalize(source([entry(path)]))

    def test_valid_constants_remain_opaque_and_cannot_execute_or_retarget(self):
        for token in ('"$.links"',r'"X\" ] $.startAddress"',r"'X\' ] $.links'",r'"\u0024.links"'):
            path=paths(token)[1]
            with patch('builtins.eval',side_effect=AssertionError('evaluation')), \
                 patch('builtins.exec',side_effect=AssertionError('execution')):
                self.assertEqual(rdap_redaction.validate_redactions(source([entry(path)])),1)
            steps=rdap_redaction.contact_path(path)
            self.assertEqual(steps[0],('member','entities'))
            self.assertEqual(steps[1][2],token)
        with self.assertRaises(GeofeedError):normalize(source([entry(r'$["entit\u0069es"]')]))

    def test_valid_strings_do_not_change_discovery_bytes_or_print_private_paths(self):
        original,_=normalize(network())
        path=paths(r'"PRIVATE\uD83D\uDE00"')[1]
        data,metadata=normalize(source([entry(path)]))
        self.assertEqual(data,original)
        self.assertEqual(metadata['rdap_ignored_entity_redactions'],1)
        self.assertNotIn('PRIVATE',data.decode()+json.dumps(metadata))
        self.assertNotIn(path,data.decode()+json.dumps(metadata))

    def test_every_declared_path_is_lexically_checked(self):
        bad=paths(r'"PRIVATE\uD800"')[1];good=paths('"fn"')[1]
        rows=[entry(bad),{'name':{'type':'Example'},'method':'partialValue','postPath':bad},
              entry(good,method='replacementValue',replacementPath=bad)]
        for index,row in enumerate(rows):
            with self.subTest(position=index):
                with self.assertRaises(GeofeedError) as caught:normalize(source([row]))
                self.assertNotIn('PRIVATE',str(caught.exception));self.assertNotIn(bad,str(caught.exception))

    def test_cli_bad_later_replacement_path_refuses_without_a_partial_report_or_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);feed=root/'feed.csv';feed.write_bytes(CSV)
            first=root/'one.json';first.write_bytes(saved(source()))
            second=root/'two.json'
            bad=source([entry(method='replacementValue',replacementPath=paths(r'"PRIVATE\uD800"')[0])])
            bad.update(handle='SECOND',startAddress='11.22.34.0',endAddress='11.22.34.255')
            second.write_bytes(saved(bad));(root/'status.json').write_bytes(b'failed status')
            (root/'before.csv').write_bytes(b'baseline')
            args=['check-registry','--registry-format','rdap','--registry-records',str(first),
                  '--registry-observed-at',STAMP,'--feed',str(feed),'--feed-url',URL]
            before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()}
            output=io.StringIO()
            with contextlib.redirect_stdout(output):self.assertEqual(main(args),0)
            self.assertTrue(json.loads(output.getvalue())['comparison_consistent'])
            output=io.StringIO();error=io.StringIO()
            with contextlib.redirect_stdout(output),contextlib.redirect_stderr(error):
                self.assertEqual(main(args+['--registry-records',str(second),'--registry-observed-at',STAMP]),1)
            self.assertEqual(output.getvalue(),'');self.assertIn('Registry input 2',error.getvalue())
            self.assertNotIn('PRIVATE',error.getvalue());self.assertNotIn(str(second),error.getvalue())
            self.assertEqual({p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()},before)

    def test_double_quoted_vectors_match_json_codec_and_scalar_validity(self):
        bodies=[r'\"',r"\'",r'\u0000',r'\uD7FF',r'\uD800',r'\uDFFF',r'\uE000',
                r'\uD800\uDC00',r'\uDBFF\uDFFF',r'\uDBFF\uE000',r'\uDC00\uD800',
                r'\U1234',r'\u123',r'\uZZZZ',chr(0xD800),chr(0xE000),chr(0x10FFFF)]
        for index,body in enumerate(bodies):
            token=quoted('"',body)
            try:
                decoded=json.loads(token)
                valid=all(not 0xD800<=ord(char)<=0xDFFF for char in decoded)
            except json.JSONDecodeError:valid=False
            for path in paths(token):
                with self.subTest(vector=index,expected=valid):
                    if valid:self.assertEqual(normalize(source([entry(path)]))[1]['rdap_ignored_entity_redactions'],1)
                    else:
                        with self.assertRaises(GeofeedError):normalize(source([entry(path)]))

    def test_unicode_validation_keeps_existing_token_and_path_budgets(self):
        # Twenty-one paired escapes use 252 characters plus two quote delimiters.
        body=r'\uD800\uDC00'*21
        self.assertEqual(len(quoted('"',body+'aa')),256)
        self.assertEqual(normalize(source([entry(paths(quoted('"',body+'aa'))[0])]))[1]['rdap_ignored_entity_redactions'],1)
        with self.assertRaises(GeofeedError):normalize(source([entry(paths(quoted('"',body+'aaa'))[0])]))

    def test_private_quote_and_surrogate_guard_removals_fail_assertions(self):
        text=Path(rdap_redaction.__file__).read_text(encoding='utf-8')
        controls=[('quote-style',"if escape not in (quote, '\\\\', '/', 'b', 'f', 'n', 'r', 't'):",'if False:',
                   'test_refuses_opposite_quote_escapes'),
                  ('raw-surrogate','if 0xD800 <= codepoint <= 0xDFFF:','if False:',
                   'test_refuses_raw_surrogate_code_points'),
                  ('quoted-validation','_quoted(token[1])','pass',
                   'test_refuses_lone_reversed_separated_and_malformed_surrogate_escapes')]
        def run(method):
            result=unittest.TestResult();RdapStringLiteralTests(method).run(result);return result
        for name,find,replacement,method in controls:
            with self.subTest(mutation=name):
                self.assertTrue(run('test_valid_quote_escapes_and_unicode_scalars_still_work').wasSuccessful())
                self.assertTrue(run(method).wasSuccessful());self.assertEqual(text.count(find),1)
                module=types.ModuleType('isp_geofeed_generator._private_string_control');module.__package__='isp_geofeed_generator'
                with patch.dict(sys.modules,{module.__name__:module}):
                    exec(compile(text.replace(find,replacement),'<private string control>','exec'),module.__dict__)
                    with patch.object(registry_rdap,'validate_redactions',module.validate_redactions):result=run(method)
                self.assertEqual(result.errors,[]);self.assertGreater(len(result.failures),0)
                self.assertTrue(run(method).wasSuccessful())
                self.assertTrue(run('test_valid_quote_escapes_and_unicode_scalars_still_work').wasSuccessful())
                print('RDAP STRING MUTATION OBSERVATION: '+json.dumps({'mutation':name,
                    'assertion_failures':len(result.failures),'errors':0,'intact_before_after':True}))
