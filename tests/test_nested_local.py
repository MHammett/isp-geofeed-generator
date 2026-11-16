"""Local policy pairs, old-client refusal, crash windows and conditional recovery."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import yaml

from isp_geofeed_generator import bound_output
from isp_geofeed_generator.adapters import SOURCES
from isp_geofeed_generator.cli import main
from isp_geofeed_generator.client import GeofeedError
from isp_geofeed_generator.contracts import SourceAdapter
from isp_geofeed_generator.feed import digest,parse_feed,render_csv
from isp_geofeed_generator.overlap import LONGEST_PREFIX
from isp_geofeed_generator.publish import atomic_write,publish_file
from isp_geofeed_generator.records import encode_records,parse_records,publish_records_file
from test_nested_core import PARENT,CHILD,row


class NestedLocalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.target=self.root/'public.csv';self.state=self.root/'state'
        self.a=render_csv([PARENT],overlap_policy=LONGEST_PREFIX)
        self.b=render_csv([PARENT,CHILD],overlap_policy=LONGEST_PREFIX)
        self.c=render_csv([row(PARENT['prefix'],'C')],overlap_policy=LONGEST_PREFIX)
        self.meta=bound_output.policy_path(self.target)

    def publish(self,value,**kwargs):
        return publish_file(self.target,value,self.state,overlap_policy=LONGEST_PREFIX,**kwargs)

    def stamps(self):
        paths=[self.target,self.meta,self.state/'before.csv',self.state/'before.policy.json',self.state/'local-transaction.json']
        return {str(path):(path.read_bytes(),path.stat().st_mtime_ns) for path in paths}

    def test_first_changed_noop_and_old_strict_refusal_even_without_overlaps(self):
        self.assertTrue(self.publish(self.a)['changed'])
        with self.assertRaises(GeofeedError):parse_feed(self.a)
        with self.assertRaisesRegex(GeofeedError,'policy-bound'):publish_file(self.target,render_csv([PARENT]),self.root/'other-state')
        with self.assertRaisesRegex(GeofeedError,'location changes'):self.publish(self.b)
        self.assertTrue(self.publish(self.b,max_relocated_fraction=1)['changed'])
        before=self.stamps()
        self.assertFalse(self.publish(self.b)['changed'])
        self.assertEqual(self.stamps(),before)
        if os.name!='nt':self.assertEqual(self.meta.stat().st_mode & 0o777,0o600)

    def test_legacy_upgrade_and_exact_conditional_recovery(self):
        legacy=render_csv([PARENT]);publish_file(self.target,legacy,self.state)
        self.publish(self.a,max_relocated_fraction=0)
        result=bound_output.recover_bound(self.target,self.state,'csv',digest(self.a))
        self.assertTrue(result['recovered']);self.assertEqual(self.target.read_bytes(),legacy);self.assertFalse(self.meta.exists())
        self.assertFalse(bound_output.recover_bound(self.target,self.state,'csv',digest(self.a))['changed'])

    def test_guard_refusals_preserve_public_policy_and_recovery_bytes(self):
        self.publish(self.a);before=self.stamps()
        with self.assertRaisesRegex(GeofeedError,'location changes'):self.publish(self.b)
        self.assertEqual(self.stamps(),before)
        self.publish(self.b,max_relocated_fraction=1);before=self.stamps()
        child=render_csv([CHILD],overlap_policy=LONGEST_PREFIX)
        with self.assertRaisesRegex(GeofeedError,'feed removal'):self.publish(child,max_relocated_fraction=1)
        self.assertEqual(self.stamps(),before)

    def test_crash_between_data_and_policy_stops_publication_and_recovers_exact_pair(self):
        self.publish(self.a);prior=self.meta.read_bytes()
        def fail_policy(path,*args,**kwargs):
            if Path(path)==self.meta:raise OSError('synthetic policy interruption')
            return atomic_write(path,*args,**kwargs)
        with patch.object(bound_output,'atomic_write',side_effect=fail_policy),self.assertRaisesRegex(GeofeedError,'recovery needs attention'):
            self.publish(self.b,max_relocated_fraction=1)
        self.assertEqual(self.target.read_bytes(),self.b);self.assertEqual(self.meta.read_bytes(),prior)
        before=self.stamps()
        with self.assertRaisesRegex(GeofeedError,'incomplete or mismatched'):self.publish(self.b)
        self.assertEqual(self.stamps(),before)
        bound_output.recover_bound(self.target,self.state,'csv',digest(self.b))
        self.assertEqual(self.target.read_bytes(),self.a);self.assertEqual(self.meta.read_bytes(),prior)

    def test_interrupted_recovery_can_resume_after_prior_bytes_are_restored(self):
        self.publish(self.a);prior=self.meta.read_bytes();self.publish(self.b,max_relocated_fraction=1)
        def fail_policy(path,*args,**kwargs):
            if Path(path)==self.meta:raise OSError('synthetic recovery interruption')
            return atomic_write(path,*args,**kwargs)
        with patch.object(bound_output,'atomic_write',side_effect=fail_policy),self.assertRaisesRegex(GeofeedError,'recovery interrupted'):
            bound_output.recover_bound(self.target,self.state,'csv',digest(self.b))
        self.assertEqual(self.target.read_bytes(),self.a)
        stamp=self.target.stat().st_mtime_ns
        bound_output.recover_bound(self.target,self.state,'csv',digest(self.b))
        self.assertEqual(self.meta.read_bytes(),prior);self.assertEqual(self.target.stat().st_mtime_ns,stamp)

    def test_failed_first_replacement_recovers_without_rewriting_retained_baseline(self):
        legacy=render_csv([PARENT]);publish_file(self.target,legacy,self.state)
        def fail_data(path,*args,**kwargs):
            if Path(path)==self.target:raise OSError('synthetic data interruption')
            return atomic_write(path,*args,**kwargs)
        with patch.object(bound_output,'atomic_write',side_effect=fail_data),self.assertRaisesRegex(GeofeedError,'recovery needs attention'):
            self.publish(self.a)
        stamp=self.target.stat().st_mtime_ns
        result=bound_output.recover_bound(self.target,self.state,'csv',digest(self.a))
        self.assertFalse(result['changed']);self.assertEqual(self.target.read_bytes(),legacy)
        self.assertEqual(self.target.stat().st_mtime_ns,stamp);self.assertFalse(self.meta.exists())

    def test_concurrent_bytes_and_policy_winners_are_preserved(self):
        for change in ('bytes','policy'):
            with self.subTest(change=change):
                self.publish(self.a,max_relocated_fraction=1);self.publish(self.b,max_relocated_fraction=1)
                if change=='bytes':atomic_write(self.target,self.c,0o644)
                else:
                    meta=json.loads(self.meta.read_bytes());meta['publication_id']='f'*32
                    atomic_write(self.meta,bound_output.encode(meta))
                before=self.stamps()
                with self.assertRaisesRegex(GeofeedError,'changed concurrently'):bound_output.recover_bound(self.target,self.state,'csv',digest(self.b))
                self.assertEqual(self.stamps(),before)
                # Restore this fixture only, not through the production recovery path.
                self.target.unlink();self.meta.unlink()

    def test_missing_or_tampered_policy_cannot_be_assumed_from_header(self):
        self.publish(self.a);self.meta.unlink();before=self.target.read_bytes()
        with self.assertRaises(GeofeedError):self.publish(self.b,max_relocated_fraction=1)
        self.assertEqual(self.target.read_bytes(),before)
        bound_output.recover_bound(self.target,self.state,'csv',digest(self.a))
        self.assertFalse(self.target.exists());self.assertFalse(self.meta.exists())

    def test_corrupt_private_baseline_or_wrong_hash_never_writes(self):
        self.publish(self.a);self.publish(self.b,max_relocated_fraction=1);before=self.stamps()
        with self.assertRaisesRegex(GeofeedError,'baseline or transaction'):bound_output.recover_bound(self.target,self.state,'csv','0'*64)
        self.assertEqual(self.stamps(),before)
        (self.state/'before.csv').write_bytes(self.c);before=self.stamps()
        with self.assertRaisesRegex(GeofeedError,'baseline or transaction'):bound_output.recover_bound(self.target,self.state,'csv',digest(self.b))
        self.assertEqual(self.stamps(),before)

    def test_initial_recovery_preserves_missing_vs_empty_prior_file(self):
        for existed in (False,True):
            if existed:self.target.write_bytes(b'')
            self.publish(self.a)
            bound_output.recover_bound(self.target,self.state,'csv',digest(self.a))
            self.assertEqual(self.target.exists(),existed)
            if existed:self.assertEqual(self.target.read_bytes(),b'')

    def test_marker_tamper_and_unknown_policy_refuse_before_any_write(self):
        for value in (self.a.replace(b'body_sha256=',b'body_sha255='),self.a.replace(b',A,',b',Z,'),render_csv([PARENT])):
            with self.assertRaises(GeofeedError):self.publish(value)
            self.assertFalse(self.target.exists());self.assertFalse((self.state/'before.csv').exists())

    def test_rich_json_is_versioned_and_exact_coordinates_are_guarded(self):
        target=self.root/'rich.json';fields={'latitude':42,'longitude':-88}
        first=[row(PARENT['prefix'],**fields)]
        changed=first+[row(CHILD['prefix'],latitude=43,longitude=-88)]
        publish_records_file(target,first,self.state,overlap_policy=LONGEST_PREFIX)
        with self.assertRaises(GeofeedError):parse_records(target.read_bytes())
        with self.assertRaisesRegex(GeofeedError,'location changes'):
            publish_records_file(target,changed,self.state,overlap_policy=LONGEST_PREFIX)
        publish_records_file(target,changed,self.state,overlap_policy=LONGEST_PREFIX,max_relocated_fraction=1)
        before=target.read_bytes();metadata=bound_output.policy_path(target).read_bytes()
        self.assertFalse(publish_records_file(target,changed,self.state,overlap_policy=LONGEST_PREFIX)['changed'])
        self.assertEqual(target.read_bytes(),before);self.assertEqual(bound_output.policy_path(target).read_bytes(),metadata)
        bound_output.recover_bound(target,self.state,'records',digest(before))
        self.assertEqual(parse_records(target.read_bytes(),overlap_policy=LONGEST_PREFIX)[0],first)

    def test_recovery_cli_reads_no_source_and_keeps_failed_publication_status_unhealthy(self):
        self.publish(self.a);self.publish(self.b,max_relocated_fraction=1)
        factory=Mock(side_effect=RuntimeError('source unavailable'))
        config={'source':{'type':'offline_source'},'state_dir':str(self.state),'overlap_policy':LONGEST_PREFIX,
                'publish':{'type':'file','path':str(self.target)}}
        path=self.root/'config.yaml';path.write_text(yaml.safe_dump(config))
        with patch.dict(SOURCES,{'offline_source':SourceAdapter(factory,initial=False)}),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['recover-local','--config',str(path),'--expected-current-sha256',digest(self.b)]),0)
        factory.assert_not_called()
        status=json.loads((self.state/'status.json').read_text())['data']
        self.assertTrue(status['recovered']);self.assertFalse(status['healthy']);self.assertEqual(self.target.read_bytes(),self.a)
