"""Saved response sets must not drop files, dates, limits or discovery scopes."""
import contextlib
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from isp_geofeed_generator import registry_batch, registry_check
from isp_geofeed_generator.cli import main
from isp_geofeed_generator.client import GeofeedError, JsonHTTP
from isp_geofeed_generator.credentials import CredentialStore
from isp_geofeed_generator.feed import digest
from test_registry_ripe import CSV, URL, OTHER, STAMP, obj, saved

SECOND='2021-01-01T00:00:00Z'


def normalized(rows, stamp=STAMP):
    return json.dumps({'schema_version':1,'observed_at':stamp,'objects':rows},
                      ensure_ascii=False,separators=(',',':')).encode()


class RegistryBatchTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.feed=self.root/'PRIVATE-feed.csv';self.feed.write_bytes(CSV)
        self.paths=[self.root/f'PRIVATE-input-{i}.json' for i in (1,2)]
        self.paths[0].write_bytes(saved([obj()]))
        self.paths[1].write_bytes(saved([obj('inet6num','2001:4860:1234::/126')]))

    def check(self, **changes):
        return registry_batch.check_file_set(self.paths,self.feed,URL,
            **{'input_format':'ripe-rest','observed_at':[STAMP,SECOND],**changes})

    def standard(self):
        self.paths[0].write_bytes(normalized([{'id':'v4','prefix':'11.22.33.0/24','geofeed':URL}]))
        self.paths[1].write_bytes(normalized([{'id':'v6','prefix':'2001:4860:1234::/126','geofeed':URL}],SECOND))

    def test_dual_family_files_keep_every_input_and_original_hash(self):
        report=self.check()
        self.assertTrue(report['comparison_consistent'])
        self.assertEqual(report['coverage']['4']['this_feed'],'256')
        self.assertEqual(report['coverage']['6']['this_feed'],'4')
        self.assertEqual(report['registry_objects'],2)
        self.assertEqual(report['snapshot_input_count'],2)
        self.assertEqual([item['snapshot_sha256'] for item in report['snapshot_inputs']],
                         [digest(path.read_bytes()) for path in self.paths])
        self.assertEqual(report['snapshot_sha256_scope'],'combined_normalized_snapshot')
        self.assertEqual(report['snapshot_sha256'],report['normalized_snapshot_sha256'])
        self.assertEqual(report['registry_source'],'RIPE')
        self.assertNotIn('PRIVATE',json.dumps(report));self.assertNotIn(URL,json.dumps(report))
        self.assertNotIn('healthy',report)
        for field in ('live_registry_read','provider_ingestion','ownership_validation'):
            self.assertEqual(report[field],'not_measured')

    def test_normalized_inputs_keep_separate_dates_and_use_the_oldest(self):
        self.standard()
        report=self.check(input_format='normalized',observed_at=None)
        self.assertTrue(report['comparison_consistent'])
        self.assertEqual(report['snapshot_observed_at'],'2020-01-01T00:00:00+00:00')
        self.assertEqual(report['snapshot_observed_at_basis'],'oldest_supplied_input')
        inputs=report['snapshot_inputs']
        self.assertEqual([row['snapshot_observed_at'] for row in inputs],
                         ['2020-01-01T00:00:00+00:00','2021-01-01T00:00:00+00:00'])
        self.assertEqual(report['snapshot_age_seconds'],max(row['snapshot_age_seconds'] for row in inputs))
        self.assertNotIn('registry_source',report)

    def test_source_manifest_hash_excludes_run_time_age(self):
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):return cls(2026,11,18,tzinfo=timezone.utc)
        with patch.object(registry_batch,'datetime',Clock):first=self.check()
        class Later(Clock):
            @classmethod
            def now(cls,tz=None):return cls(2026,11,19,tzinfo=timezone.utc)
        with patch.object(registry_batch,'datetime',Later):second=self.check()
        self.assertNotEqual(first['snapshot_age_seconds'],second['snapshot_age_seconds'])
        self.assertEqual(first['source_manifest_sha256'],second['source_manifest_sha256'])
        self.assertEqual(first['snapshot_sha256'],second['snapshot_sha256'])

    def test_file_and_date_count_fail_before_any_file_access(self):
        with patch.object(registry_batch,'read_output',side_effect=AssertionError('file read')):
            for paths,dates,kind in (([],[],'ripe-rest'),(self.paths*17,[STAMP]*34,'ripe-rest'),
                                     (self.paths,[STAMP],'ripe-rest'),(self.paths,[STAMP]*3,'ripe-rest'),
                                     (self.paths,None,'ripe-rest'),(self.paths,[STAMP,None],'ripe-rest'),
                                     (self.paths,[STAMP,SECOND],'normalized'),(self.paths,None,'unknown')):
                with self.subTest(count=len(paths),dates=dates,kind=kind),self.assertRaises(GeofeedError):
                    registry_batch.check_file_set(paths,self.feed,URL,input_format=kind,observed_at=dates)

    def test_combined_raw_bytes_are_bounded_before_the_second_input_finishes(self):
        limit=sum(len(path.read_bytes()) for path in self.paths)-1
        with patch.object(registry_batch,'MAX_BYTES',limit),self.assertRaisesRegex(GeofeedError,'Registry input 2'):
            self.check()

    def test_combined_normalized_bytes_have_a_separate_bound(self):
        self.standard()
        for path in self.paths:
            source=json.loads(path.read_bytes());source['objects'][0]['remarks']=['🙂'*100]
            path.write_bytes(normalized(source['objects'],source['observed_at']))
        limit=sum(len(path.read_bytes()) for path in self.paths)
        with patch.object(registry_batch,'MAX_BYTES',limit),self.assertRaisesRegex(GeofeedError,'normalized.*byte limit'):
            self.check(input_format='normalized',observed_at=None)

    def test_combined_object_limit_is_enforced_across_inputs(self):
        with patch.object(registry_batch,'MAX_OBJECTS',1),self.assertRaisesRegex(GeofeedError,'object limit'):
            self.check()

    def test_duplicate_versions_are_refused_even_when_identical_or_newer(self):
        for native in (URL,OTHER):
            self.paths[1].write_bytes(saved([obj(native=native)]))
            with self.subTest(native=native),self.assertRaisesRegex(GeofeedError,'unique safe IDs'):
                self.check()
        self.standard()
        self.paths[1].write_bytes(normalized([{'id':'v4','prefix':'2001:4860:1234::/126','geofeed':URL}],SECOND))
        with self.assertRaisesRegex(GeofeedError,'unique safe IDs'):
            self.check(input_format='normalized',observed_at=None)

    def test_crossing_scopes_in_different_files_stop_the_whole_check(self):
        self.paths[1].write_bytes(saved([obj(value='11.22.33.128 - 11.22.34.0')]))
        with self.assertRaisesRegex(GeofeedError,'crossing referring scopes'):self.check()

    def test_child_references_across_files_keep_precedence_and_native_rules(self):
        self.feed.write_bytes(CSV.splitlines(keepends=True)[0])
        self.paths[0].write_bytes(saved([obj(remarks=[f'Geofeed {OTHER}'])]))
        self.paths[1].write_bytes(saved([obj(value='11.22.33.0 - 11.22.33.127',native=OTHER)]))
        report=self.check()
        self.assertFalse(report['comparison_consistent'])
        self.assertEqual(report['coverage']['4']['this_feed'],'128')
        self.assertEqual(report['coverage']['4']['other_feed'],'128')
        self.assertEqual(report['native_precedence_objects'],1)
        self.paths[1].write_bytes(saved([obj(value='11.22.33.0 - 11.22.33.127',native=None)]))
        self.assertTrue(self.check()['comparison_consistent'])

    def test_any_bad_response_or_date_prevents_partial_success(self):
        good=self.paths[1].read_bytes()
        for data in (b'PRIVATE',b'{"objects":{},"objects":{}}',saved([],errormessages={}),
                     saved([obj()],errormessages={'errormessage':[{'severity':'Info','text':'PRIVATE'}]})):
            self.paths[1].write_bytes(data)
            with self.subTest(data=data[:20]),self.assertRaisesRegex(GeofeedError,'Registry input 2') as caught:
                self.check()
            self.assertNotIn('PRIVATE',str(caught.exception))
        self.paths[1].write_bytes(good)
        for stamp in ('2999-01-01T00:00:00Z','PRIVATE','2021-01-01T00:00:00-05:00'):
            with self.subTest(stamp=stamp),self.assertRaisesRegex(GeofeedError,'Registry input 2'):
                self.check(observed_at=[STAMP,stamp])
        self.paths[1].unlink()
        with self.assertRaisesRegex(GeofeedError,'Registry input 2'):self.check()

    def test_normalized_bad_envelope_or_future_date_cannot_hide_behind_oldest(self):
        self.standard()
        for data in (normalized([],stamp='2999-01-01T00:00:00Z'),
                     b'{"schema_version":1,"observed_at":"2020-01-01T00:00:00Z","objects":[],"extra":1}',
                     normalized([{'id':'v6','prefix':'2001:4860:1234::/126','remarks':['bad\nline']}])):
            self.paths[1].write_bytes(data)
            with self.subTest(data=data[:20]),self.assertRaises(GeofeedError):
                self.check(input_format='normalized',observed_at=None)

    def test_same_scope_different_ids_stays_unsupported_instead_of_selecting(self):
        self.standard()
        self.paths[1].write_bytes(normalized([{'id':'different-id','prefix':'11.22.33.0/24','geofeed':URL}],SECOND))
        report=self.check(input_format='normalized',observed_at=None)
        self.assertFalse(report['comparison_consistent'])
        self.assertEqual(report['coverage']['4']['ambiguous_reference'],'256')
        self.assertEqual(report['findings'][0]['kind'],'same_scope_resolution_unsupported')

    def test_single_file_delegates_with_the_original_contract(self):
        for kind,dates in (('ripe-rest',[STAMP]),('normalized',None)):
            with self.subTest(kind=kind),patch.object(registry_batch,'check_files',return_value={'original':True}) as check:
                result=registry_batch.check_file_set(self.paths[:1],self.feed,URL,input_format=kind,observed_at=dates)
                self.assertEqual(result,{'original':True})
                check.assert_called_once_with(self.paths[0],self.feed,URL,overlap_policy='reject',
                                              input_format=kind,observed_at=STAMP if dates else None)

    def test_cli_refuses_operation_flags_and_dates_without_reads(self):
        with patch('isp_geofeed_generator.cli.load_config',side_effect=AssertionError('config read')), \
             patch.object(registry_batch,'read_output',side_effect=AssertionError('file read')), \
             contextlib.redirect_stderr(io.StringIO()):
            for args in (['publish','--registry-records','a','--registry-records','b'],
                         ['check-registry','--registry-records','a','--registry-records','b','--feed','c','--feed-url',URL,
                          '--registry-format','ripe-rest','--registry-observed-at',STAMP],
                         ['check-registry','--registry-records','a','--registry-records','b','--feed','c','--feed-url',URL,
                          '--output','d']):
                self.assertEqual(main(args),1)

    def test_cli_success_and_refusal_preserve_files_without_other_access(self):
        (self.root/'status.json').write_bytes(b'failed status');(self.root/'before.csv').write_bytes(b'baseline')
        args=['check-registry','--registry-format','ripe-rest','--feed',str(self.feed),'--feed-url',URL,
              '--config',str(self.root/'absent.yaml')]
        for path,stamp in zip(self.paths,(STAMP,SECOND)):
            args+=['--registry-records',str(path),'--registry-observed-at',stamp]
        with patch('isp_geofeed_generator.cli.load_config',side_effect=AssertionError('config read')), \
             patch.object(CredentialStore,'get',side_effect=AssertionError('credential read')), \
             patch.object(JsonHTTP,'request',side_effect=AssertionError('HTTP call')), \
             patch('socket.getaddrinfo',side_effect=AssertionError('DNS lookup')), \
             patch('urllib.request.urlopen',side_effect=AssertionError('URL open')), \
             patch('isp_geofeed_generator.cli.atomic_write',side_effect=AssertionError('output write')):
            for invalid in (False,True):
                if invalid:self.paths[1].write_bytes(saved([],errormessages={'errormessage':[{'text':'PRIVATE'}]}))
                before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in self.root.iterdir()}
                output=io.StringIO();error=io.StringIO()
                with contextlib.redirect_stdout(output),contextlib.redirect_stderr(error):
                    self.assertEqual(main(args),1 if invalid else 0)
                self.assertNotIn('PRIVATE',output.getvalue()+error.getvalue())
                if invalid:self.assertEqual(output.getvalue(),'')
                else:self.assertEqual(json.loads(output.getvalue())['snapshot_input_count'],2)
                self.assertEqual({p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in self.root.iterdir()},before)

    def test_private_mutations_expose_dropped_files_and_combined_limits(self):
        source=Path(registry_batch.__file__).read_text(encoding='utf-8')
        controls=[('drop-later-files','enumerate(paths, 1)','enumerate(paths[:1], 1)',
                   'test_dual_family_files_keep_every_input_and_original_hash'),
                  ('raw-byte-budget','remaining -= len(snapshot.data)','remaining -= 0',
                   'test_combined_raw_bytes_are_bounded_before_the_second_input_finishes'),
                  ('object-budget','if total_objects > MAX_OBJECTS:','if False:',
                   'test_combined_object_limit_is_enforced_across_inputs')]
        def run(method):
            result=unittest.TestResult();RegistryBatchTests(method).run(result);return result
        for name,find,replacement,method in controls:
            with self.subTest(mutation=name):
                self.assertTrue(run(method).wasSuccessful())
                self.assertEqual(source.count(find),1)
                module=types.ModuleType('isp_geofeed_generator._private_batch_control');module.__package__='isp_geofeed_generator'
                with patch.dict(sys.modules,{module.__name__:module}):
                    exec(compile(source.replace(find,replacement),'<private registry batch control>','exec'),module.__dict__)
                    with patch.object(registry_batch,'check_file_set',module.check_file_set):result=run(method)
                self.assertEqual(result.errors,[])
                self.assertGreater(len(result.failures),0)
                self.assertTrue(run(method).wasSuccessful())
                print('REGISTRY BATCH MUTATION OBSERVATION: '+json.dumps({'mutation':name,
                    'assertion_failures':len(result.failures),'errors':len(result.errors),'intact_before_after':True}))
