"""Layer observations must preserve core decisions and reject missing evidence."""
import inspect
from pathlib import Path
import types
import unittest
from unittest.mock import patch

from wordpress import storage_layers
from wordpress import run as workload


class StorageLayerTests(unittest.TestCase):
    def test_core_insertion_adds_only_observations_after_the_two_anchors(self):
        source='before\n'+storage_layers.VALIDATION+'\nreturn false;\n'+storage_layers.DRIVER+'\nafter'
        observed=storage_layers.instrument_core(source)
        self.assertNotEqual(source,observed)
        for anchor,addition in storage_layers.CALLS.items():
            self.assertEqual(observed.count(anchor),1)
            self.assertIn(anchor+addition,observed)
            observed=observed.replace(addition,'')
        self.assertEqual(observed,source)

    def test_missing_or_ambiguous_core_anchors_stop_before_modification(self):
        for source in ('',storage_layers.VALIDATION,storage_layers.DRIVER,
                       storage_layers.VALIDATION*2+storage_layers.DRIVER,
                       storage_layers.VALIDATION+storage_layers.DRIVER*2,
                       storage_layers.instrument_core(storage_layers.VALIDATION+storage_layers.DRIVER)):
            with self.subTest(source=source[:20]),self.assertRaisesRegex(AssertionError,'one exact'):
                storage_layers.instrument_core(source)

    def test_supported_layer_records_distinguish_validation_driver_and_success(self):
        for row,expected in (({'stage':'wordpress_validation','failed':True,'driver_error':'not_applicable'},'wordpress_validation'),
                             ({'stage':'driver_result','failed':False,'driver_error':'none'},'database_success'),
                             ({'stage':'driver_result','failed':True,'driver_error':'unknown_column'},'database_driver'),
                             ({'stage':'driver_result','failed':True,'driver_error':'charset'},'database_driver')):
            self.assertEqual(storage_layers.classify_trace([row]),expected)

    def test_no_events_are_not_a_measured_refusal(self):
        with self.assertRaisesRegex(AssertionError,'Missing or unsupported'):
            storage_layers.classify_trace([])

    def test_mixed_malformed_or_contradictory_records_are_not_measured(self):
        valid={'stage':'wordpress_validation','failed':True,'driver_error':'not_applicable'}
        driver={'stage':'driver_result','failed':True,'driver_error':'charset'}
        for rows in (None,[valid,driver],[driver,driver],[{}],[{**valid,'failed':1}],
                     [{**valid,'sql':'PRIVATE'}],[{**driver,'failed':False}],
                     [{**driver,'driver_error':'none'}],[{**valid,'failed':False}]):
            with self.subTest(rows=rows),self.assertRaisesRegex(AssertionError,'Missing or unsupported'):
                storage_layers.classify_trace(rows)

    def test_private_entries_refuse_outside_hosted_prototype_without_file_or_process_access(self):
        methods=('storage_legacy_charset_tests','storage_layer_control','_storage_legacy_charset_trials')
        for disposable,enabled in ((False,'1'),(True,'0')):
            dummy=types.SimpleNamespace(environment={'GEOFEED_WP_STORAGE_PROTOTYPE':enabled})
            with patch.object(workload,'DISPOSABLE',disposable), \
                 patch.object(workload.subprocess,'run',side_effect=AssertionError('unexpected process')) as process, \
                 patch.object(Path,'read_bytes',side_effect=AssertionError('unexpected file')) as read:
                for method in methods:
                    args=() if method=='storage_layer_control' else ('prototype',)
                    with self.subTest(method=method,disposable=disposable),self.assertRaisesRegex(AssertionError,'requires?'):
                        getattr(workload.Workload,method)(dummy,*args)
                process.assert_not_called();read.assert_not_called()

    def test_private_missing_data_mutation_fails_the_assertion_with_no_setup_error(self):
        source=inspect.getsource(storage_layers.classify_trace)
        find="raise AssertionError('Missing or unsupported storage-layer evidence')"
        self.assertEqual(source.count(find),1)
        def run():
            result=unittest.TestResult();StorageLayerTests('test_no_events_are_not_a_measured_refusal').run(result);return result
        self.assertTrue(run().wasSuccessful())
        namespace={}
        exec(compile(source.replace(find,"return 'wordpress_validation'"),'<private layer control>','exec'),namespace)
        with patch.object(storage_layers,'classify_trace',namespace['classify_trace']):result=run()
        self.assertEqual(len(result.failures),1);self.assertEqual(result.errors,[])
        self.assertTrue(run().wasSuccessful())
        print('STORAGE LAYER MUTATION OBSERVATION: {"missing_evidence_accepted": true, "assertion_failures": 1, "errors": 0, "intact_before_after": true}')
