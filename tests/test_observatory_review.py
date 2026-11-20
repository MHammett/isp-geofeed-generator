"""External manual notes remain separate from measured local registry coverage."""
import contextlib
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from isp_geofeed_generator import observatory_review as module
from isp_geofeed_generator.cli import main
from isp_geofeed_generator.client import GeofeedError, JsonHTTP
from isp_geofeed_generator.credentials import CredentialStore

URL = 'https://feed.example/feed.csv'
NOW = datetime(2026, 11, 19, 20, tzinfo=timezone.utc)


def review():
    return {'schema_version': 1, 'source': 'geoflaw', 'feed_url': URL,
            'reviewed_at': '2026-11-19T19:00:00.123456Z', 'datasets': {
                'reference': {'status': 'finding', 'observed_on': '2026-11-11'},
                'retrieval': {'status': 'no_finding', 'observed_on': '2026-11-11'},
                'content': {'status': 'not_measured', 'observed_on': None},
                'coverage': {'status': 'finding', 'observed_on': '2026-11-04'}}}


class ObservatoryReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.path = self.root/'review.json'
        self.path.write_text(json.dumps(review()))

    def read(self):
        return module.read_review(self.path, URL, now=NOW)

    def test_distinct_states_and_dataset_dates_never_become_health_or_authority(self):
        result = self.read()
        self.assertEqual(result['datasets']['reference']['dataset_age_days'], 8)
        self.assertEqual(result['datasets']['coverage']['dataset_age_days'], 15)
        self.assertEqual(result['datasets']['retrieval']['status'], 'no_finding')
        self.assertEqual(result['datasets']['content'], {'status':'not_measured', 'dataset_observed_on':None, 'dataset_age_days':None})
        self.assertEqual(result['reviewed_at'], review()['reviewed_at'])
        self.assertEqual(result['input_kind'], 'operator_entered_review')
        self.assertFalse(result['publication_gate']); self.assertNotIn('healthy', result)
        for key in ('review_authenticity','dataset_completeness','current_public_feed',
                    'candidate_content_match','registry_authority','provider_ingestion'):
            self.assertEqual(result[key], 'not_measured')

    def test_exact_url_mismatch_is_refused_without_echoing_input(self):
        value = review(); value['feed_url'] = 'https://PRIVATE.example/feed.csv'
        self.path.write_text(json.dumps(value))
        with self.assertRaises(GeofeedError) as error: self.read()
        self.assertNotIn('PRIVATE', str(error.exception))

    def test_dataset_date_after_review_is_refused_even_if_it_is_in_the_past(self):
        value = review(); value['reviewed_at'] = '2026-11-10T19:00:00Z'
        self.path.write_text(json.dumps(value))
        with self.assertRaises(GeofeedError): self.read()

    def test_closed_schema_duplicates_nonfinite_and_malformed_json_are_refused(self):
        value = review()
        duplicate = json.dumps(value).replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1')
        cases = [b'[]', b'{', b'{"PRIVATE":NaN}', duplicate.encode(),
                 json.dumps({**value,'schema_version':True}).encode(),
                 json.dumps({**value,'PRIVATE':'secret'}).encode(),
                 json.dumps({**value,'source':'https://PRIVATE.example/'}).encode()]
        for data in cases:
            self.path.write_bytes(data)
            with self.subTest(data=data), self.assertRaises(GeofeedError) as error: self.read()
            self.assertNotIn('PRIVATE', str(error.exception))

    def test_every_dataset_is_explicit_and_unknown_statuses_or_notes_are_refused(self):
        for change in ('missing','extra','unknown','notes','undated','false_date'):
            value = review()
            if change == 'missing': del value['datasets']['coverage']
            elif change == 'extra': value['datasets']['PRIVATE'] = {}
            elif change == 'unknown': value['datasets']['reference']['status'] = 'healthy'
            elif change == 'notes': value['datasets']['reference']['notes'] = 'PRIVATE secret'
            elif change == 'undated': value['datasets']['reference']['observed_on'] = None
            else: value['datasets']['content']['observed_on'] = '2026-11-11'
            self.path.write_text(json.dumps(value))
            with self.subTest(change=change), self.assertRaises(GeofeedError): self.read()

    def test_bad_calendar_future_precision_and_naive_review_dates_are_refused(self):
        for stamp in ('2026-11-19T19:00:00','2026-11-19T19:00:00+01:00',
                      '2026-11-19T19:00:00.1234567Z','2099-01-01T00:00:00Z','PRIVATE'):
            self.path.write_text(json.dumps({**review(),'reviewed_at':stamp}))
            with self.subTest(stamp=stamp), self.assertRaises(GeofeedError): self.read()
        value = review(); value['datasets']['reference']['observed_on'] = '2026-02-30'
        self.path.write_text(json.dumps(value))
        with self.assertRaises(GeofeedError): self.read()

    def test_missing_directory_and_oversize_files_are_refused(self):
        for path in (self.root/'missing', self.root):
            with self.assertRaises(GeofeedError): module.read_review(path, URL, now=NOW)
        self.path.write_bytes(b' '*(module.MAX_BYTES+1))
        with self.assertRaises(GeofeedError): self.read()

    def cli(self, *extra):
        output, error = io.StringIO(), io.StringIO()
        with patch('isp_geofeed_generator.cli.load_config', side_effect=AssertionError('config read')) as config_read, \
             patch.object(CredentialStore,'get',side_effect=AssertionError('credential read')) as credential_read, \
             patch.object(JsonHTTP,'request',side_effect=AssertionError('network read')) as network_read, \
             patch('isp_geofeed_generator.cli.atomic_write',side_effect=AssertionError('output write')) as output_write, \
             patch('isp_geofeed_generator.rdap_bootstrap.plan_file',side_effect=AssertionError('plan read')) as plan_read, \
             patch('isp_geofeed_generator.rdap_capture.capture',side_effect=AssertionError('capture read')) as capture_read, \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            code = main(list(extra))
        for operation in (config_read,credential_read,network_read,output_write,plan_read,capture_read):
            operation.assert_not_called()
        return code, output.getvalue(), error.getvalue()

    def test_cli_notes_do_not_change_local_verdict_and_invalid_notes_emit_no_partial_report(self):
        feed = self.root/'feed.csv'; feed.write_bytes(b'11.22.33.0/24,US,US-IL,Example City,\r\n')
        registry = self.root/'registry.json'
        value = {'schema_version':1,'observed_at':'2026-11-18T00:00:00Z',
                 'objects':[{'id':'parent','prefix':'11.22.33.0/24','geofeed':URL}]}
        registry.write_text(json.dumps(value)); sentinel = self.root/'status.json'; sentinel.write_bytes(b'PRIVATE old status')
        paths = (self.path,feed,registry,sentinel)
        before = {p:(p.read_bytes(),p.stat().st_mtime_ns) for p in paths}
        args = ['check-registry','--registry-records',str(registry),'--feed',str(feed),'--feed-url',URL]
        code, text, error = self.cli(*args,'--observatory-review',str(self.path))
        self.assertEqual((code,error),(0,'')); result = json.loads(text)
        self.assertTrue(result['comparison_consistent'])
        self.assertEqual(result['external_observatory_review']['datasets']['reference']['status'],'finding')
        self.assertEqual({p:(p.read_bytes(),p.stat().st_mtime_ns) for p in paths},before)
        value['objects'][0]['geofeed'] = 'https://other.example/feed.csv'; registry.write_text(json.dumps(value))
        self.assertEqual(self.cli(*args)[0],1)
        self.assertEqual(self.cli(*args,'--observatory-review',str(self.path))[0],1)
        clear = review()
        for row in clear['datasets'].values():
            row.update(status='no_finding', observed_on='2026-11-11')
        self.path.write_text(json.dumps(clear))
        code, text, _ = self.cli(*args,'--observatory-review',str(self.path))
        self.assertEqual(code,1); self.assertFalse(json.loads(text)['comparison_consistent'])
        self.path.write_text(json.dumps({**review(),'feed_url':'https://PRIVATE.example/'}))
        code, text, error = self.cli(*args,'--observatory-review',str(self.path))
        self.assertEqual((code,text),(1,'')); self.assertNotIn('PRIVATE',error)
        self.assertEqual((sentinel.read_bytes(),sentinel.stat().st_mtime_ns),before[sentinel])

    def test_write_planning_and_capture_commands_refuse_the_flag_before_io(self):
        for command in ('discover','generate','publish','recover-local','recover-wordpress',
                        'configure-wordpress-policy','inspect-wordpress','plan-rdap','capture-rdap'):
            args = [command,'--observatory-review',str(self.path)]
            if command in ('plan-rdap','capture-rdap'):
                args += ['--bootstrap-records',str(self.root/'unused.json'),
                         '--bootstrap-observed-at','2026-11-18T00:00:00Z','--rdap-prefix','11.22.33.0/24']
                if command == 'capture-rdap': args += ['--rdap-capture-dir',str(self.root/'unused-capture')]
            code, text, _ = self.cli(*args)
            self.assertEqual((code,text),(1,''))

    def test_private_url_and_date_guard_removals_are_caught_by_assertions(self):
        text = Path(module.__file__).read_text()
        cases = [('exact-url',"or source['feed_url'] != expected_url",'or False',
                  'test_exact_url_mismatch_is_refused_without_echoing_input'),
                 ('dataset-date','if day > reviewed.date():','if False:',
                  'test_dataset_date_after_review_is_refused_even_if_it_is_in_the_past')]
        def run(name):
            result = unittest.TestResult(); ObservatoryReviewTests(name).run(result); return result
        positive = 'test_distinct_states_and_dataset_dates_never_become_health_or_authority'
        for name, find, replacement, method in cases:
            self.assertTrue(run(positive).wasSuccessful()); self.assertTrue(run(method).wasSuccessful())
            self.assertEqual(text.count(find),1)
            private = types.ModuleType('isp_geofeed_generator._private_observatory_control')
            private.__package__ = 'isp_geofeed_generator'
            exec(compile(text.replace(find,replacement),'<private observatory control>','exec'),private.__dict__)
            with patch.object(module,'read_review',private.read_review): result = run(method)
            self.assertEqual(result.errors,[]); self.assertEqual(len(result.failures),1)
            self.assertTrue(run(positive).wasSuccessful()); self.assertTrue(run(method).wasSuccessful())
            print('OBSERVATORY REVIEW MUTATION OBSERVATION: '+json.dumps({'mutation':name,
                'assertion_failures':1,'errors':0,'intact_before_after':True}))
