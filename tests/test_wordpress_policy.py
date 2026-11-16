"""Policy negotiation, publisher ownership and checked recovery outcomes."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from isp_geofeed_generator.client import GeofeedError
from isp_geofeed_generator.feed import digest,render_csv
from isp_geofeed_generator.overlap import REJECT,LONGEST_PREFIX
from isp_geofeed_generator.publish import WordPress,publish_wordpress
from isp_geofeed_generator.wordpress_policy import Snapshot,recover
from test_nested_core import PARENT,CHILD,row

A=render_csv([PARENT],overlap_policy=LONGEST_PREFIX)
B=render_csv([PARENT,CHILD],overlap_policy=LONGEST_PREFIX)
C=render_csv([row(PARENT['prefix'],'C')],overlap_policy=LONGEST_PREFIX)


class PolicyWP:
    public_url='https://example.net/wp-json/isp-geofeed-generator/v1/feed'
    def __init__(self):
        self.current=Snapshot(b'',REJECT,LONGEST_PREFIX,b'',REJECT,None)
        self.writes=[];self.mode=None;self.wrong_reads=0;self.deny_restore=False;self.lose_restore=False
    def policy_state(self):return self.current
    def read_public(self,**kwargs):
        if self.wrong_reads:self.wrong_reads-=1;return C
        return self.current.csv
    def replace_policy(self,csv,policy,expected,identity,operation='publish'):
        if expected!=self.current:raise GeofeedError('HTTP 409')
        if operation=='restore' and self.deny_restore:raise GeofeedError('HTTP 503')
        mode=self.mode;self.mode=None
        if operation=='publish' and mode=='before':raise GeofeedError('HTTP 503')
        self.writes.append((csv,policy,operation,identity))
        before=self.current
        self.current=Snapshot(csv,policy,before.required,before.csv,before.policy,identity)
        if operation=='restore' and self.lose_restore:
            self.lose_restore=False;raise GeofeedError('Lost restore reply')
        if operation=='publish':
            if mode=='lost':raise GeofeedError('Lost write reply')
            if mode in ('bad-public','failed-recovery','lost-restore'):self.wrong_reads=1
            if mode=='failed-recovery':self.deny_restore=True
            if mode=='lost-restore':self.lose_restore=True
            if mode=='winner':self.current=Snapshot(C,LONGEST_PREFIX,before.required,csv,policy,'f'*32)


class WordPressPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.wp=PolicyWP()
    def publish(self,value,**kwargs):
        return publish_wordpress(self.wp,value,self.root,overlap_policy=LONGEST_PREFIX,**kwargs)
    def test_first_change_noop_preserves_private_history_and_exact_policy(self):
        self.assertTrue(self.publish(A)['changed'])
        self.assertEqual(self.wp.current.policy,LONGEST_PREFIX)
        self.assertEqual(self.wp.current.previous_policy,REJECT)
        self.assertTrue(self.publish(B,max_relocated_fraction=1)['changed'])
        before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in self.root.iterdir()}
        writes=list(self.wp.writes);state=self.wp.current
        self.assertFalse(self.publish(B)['changed'])
        self.assertEqual(self.wp.current,state);self.assertEqual(self.wp.writes,writes)
        self.assertEqual({p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in self.root.iterdir()},before)
    def test_platform_contract_and_instance_configuration_errors_are_separate(self):
        self.wp.current=Snapshot(b'',REJECT,REJECT,b'',REJECT,None)
        with self.assertRaisesRegex(GeofeedError,'configured for reject'):self.publish(A)
        self.assertEqual(self.wp.writes,[]);self.assertFalse((self.root/'before.csv').exists())
        with self.assertRaisesRegex(GeofeedError,'lacks the version-2'):
            publish_wordpress(object(),A,self.root,overlap_policy=LONGEST_PREFIX)
    def test_stale_public_preflight_stops_before_backup_and_writes(self):
        self.publish(A);before=(self.root/'before.csv').read_bytes();self.wp.wrong_reads=1
        with self.assertRaisesRegex(GeofeedError,'no policy write attempted'):self.publish(B,max_relocated_fraction=1)
        self.assertEqual(len(self.wp.writes),1);self.assertEqual((self.root/'before.csv').read_bytes(),before)
    def test_moves_and_withdrawal_still_stop_without_replacing_backups(self):
        self.publish(A);before=(self.root/'before-policy.json').read_bytes()
        with self.assertRaisesRegex(GeofeedError,'location changes'):self.publish(B)
        self.assertEqual((self.root/'before-policy.json').read_bytes(),before)
        self.publish(B,max_relocated_fraction=1)
        with self.assertRaisesRegex(GeofeedError,'feed removal'):
            self.publish(render_csv([CHILD],overlap_policy=LONGEST_PREFIX),max_relocated_fraction=1)
    def test_bad_readback_lost_write_and_lost_restore_reply_are_checked(self):
        for mode in ('bad-public','lost','lost-restore','before'):
            with self.subTest(mode=mode):
                self.wp=PolicyWP();self.publish(A);self.wp.mode=mode
                with self.assertRaisesRegex(GeofeedError,'Previous feed and policy retained/restored'):
                    self.publish(B,max_relocated_fraction=1)
                self.assertEqual(self.wp.current.csv,A);self.assertEqual(self.wp.current.policy,LONGEST_PREFIX)
                self.assertEqual((self.root/'before.csv').read_bytes(),A)
    def test_upgrade_recovery_restores_legacy_strict_bytes_and_policy(self):
        legacy=render_csv([PARENT]);self.wp.current=Snapshot(legacy,REJECT,LONGEST_PREFIX,b'',REJECT,None)
        self.wp.mode='bad-public'
        with self.assertRaisesRegex(GeofeedError,'retained/restored'):self.publish(A)
        self.assertEqual(self.wp.current.csv,legacy);self.assertEqual(self.wp.current.policy,REJECT)
    def test_other_publisher_even_with_identical_candidate_bytes_is_not_overwritten(self):
        self.publish(A);self.wp.mode='winner'
        with self.assertRaisesRegex(GeofeedError,'Another WordPress publisher'):self.publish(B,max_relocated_fraction=1)
        self.assertEqual(self.wp.current.csv,C);self.assertEqual(len(self.wp.writes),2)
        # A different owner's identical content is also outside our recovery claim.
        self.wp=PolicyWP();self.publish(A)
        original=self.wp.replace_policy
        def other_owner(*args,**kwargs):
            original(*args,**kwargs)
            state=self.wp.current
            self.wp.current=Snapshot(state.csv,state.policy,state.required,state.previous,state.previous_policy,'e'*32)
            raise GeofeedError('Lost reply after another owner')
        self.wp.replace_policy=other_owner
        with self.assertRaisesRegex(GeofeedError,'Another WordPress publisher'):self.publish(B,max_relocated_fraction=1)
        self.assertEqual(self.wp.current.csv,B);self.assertEqual(self.wp.current.publication_id,'e'*32)
    def test_failed_restore_keeps_candidate_and_manual_recovery_is_conditional(self):
        self.publish(A);self.wp.mode='failed-recovery'
        with self.assertRaisesRegex(GeofeedError,'Recovery needs attention'):self.publish(B,max_relocated_fraction=1)
        self.assertEqual(self.wp.current.csv,B);self.assertEqual((self.root/'before.csv').read_bytes(),A)
        self.wp.deny_restore=False
        result=recover(self.wp,self.root,digest(B))
        self.assertTrue(result['recovered']);self.assertEqual(self.wp.current.csv,A)
    def test_manual_recovery_refuses_wrong_destination_hash_baseline_and_owner(self):
        self.publish(A);self.publish(B,max_relocated_fraction=1)
        state=self.wp.current;writes=list(self.wp.writes)
        with self.assertRaises(GeofeedError):recover(self.wp,self.root,'0'*64)
        current=self.wp.current
        self.wp.current=Snapshot(current.csv,current.policy,current.required,current.previous,current.previous_policy,'f'*32)
        with self.assertRaisesRegex(GeofeedError,'changed'):recover(self.wp,self.root,digest(B))
        self.assertEqual(self.wp.writes,writes)
    def test_policy_switch_during_noop_is_refused_without_writes(self):
        self.publish(A);calls=0;before=self.wp.current
        def state():
            nonlocal calls
            calls+=1
            return before if calls==1 else Snapshot(before.csv,before.policy,REJECT,before.previous,before.previous_policy,before.publication_id)
        self.wp.policy_state=state
        with self.assertRaisesRegex(GeofeedError,'changed during unchanged'):self.publish(A)
        self.assertEqual(len(self.wp.writes),1)


class PolicyHTTPTests(unittest.TestCase):
    def test_old_plugin_and_malformed_policy_state_refuse_before_put(self):
        class HTTP:
            def __init__(self,value):self.value=value;self.calls=[]
            def request(self,*args,**kwargs):
                self.calls.append((args,kwargs))
                if isinstance(self.value,Exception):raise self.value
                return self.value
        for value in (GeofeedError('HTTP 404; no retry was made'),{},
                      {'protocol_version':True}, {'protocol_version':2,'supported_overlap_policies':['reject']}):
            http=HTTP(value);client=WordPress('https://example.net','user','synthetic',http)
            with tempfile.TemporaryDirectory() as tmp,self.assertRaises(GeofeedError):
                publish_wordpress(client,A,tmp,overlap_policy=LONGEST_PREFIX)
            self.assertEqual(len(http.calls),1);self.assertNotIn('body',http.calls[0][1])
