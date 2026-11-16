"""Policy negotiation, publisher ownership and checked recovery outcomes."""
import copy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import yaml

from isp_geofeed_generator.client import GeofeedError
from isp_geofeed_generator.feed import digest,render_csv
from isp_geofeed_generator.overlap import REJECT,LONGEST_PREFIX
from isp_geofeed_generator.publish import WordPress,publish_wordpress
from isp_geofeed_generator.wordpress_policy import Snapshot,recover,configure,PolicyMismatch
from test_nested_core import PARENT,CHILD,row
from isp_geofeed_generator.cli import main
from isp_geofeed_generator.adapters import SOURCES
from isp_geofeed_generator.contracts import SourceAdapter
from isp_geofeed_generator.credentials import CredentialStore

A=render_csv([PARENT],overlap_policy=LONGEST_PREFIX)
B=render_csv([PARENT,CHILD],overlap_policy=LONGEST_PREFIX)
C=render_csv([row(PARENT['prefix'],'C')],overlap_policy=LONGEST_PREFIX)


class PolicyWP:
    public_url='https://example.net/wp-json/isp-geofeed-generator/v1/feed'
    def __init__(self):
        self.current=Snapshot(b'',REJECT,LONGEST_PREFIX,b'',REJECT,None)
        self.writes=[];self.mode=None;self.wrong_reads=0;self.deny_restore=False;self.lose_restore=False;self.config_writes=[];self.lose_config=False
    def policy_state(self):return self.current
    def state(self):
        if self.current.policy!=REJECT or self.current.required!=REJECT:raise PolicyMismatch('different overlap policy')
        return self.current.csv
    def configure_policy(self,policy,expected,identity):
        if expected!=self.current:raise GeofeedError('HTTP 409')
        self.config_writes.append((policy,identity))
        self.current=Snapshot(expected.csv,expected.policy,policy,expected.previous,expected.previous_policy,identity)
        if self.lose_config:self.lose_config=False;raise GeofeedError('Lost policy configuration reply')
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
        with self.assertRaisesRegex(GeofeedError,'location changes'):self.publish(A)
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
    def test_administrator_switch_preserves_data_history_and_noop_makes_no_writes(self):
        self.publish(A);self.wp.lose_config=True;before=self.wp.current
        self.assertTrue(configure(self.wp,REJECT,digest(A))['changed'])
        self.assertEqual(self.wp.current.csv,before.csv);self.assertEqual(self.wp.current.previous,before.previous)
        self.assertEqual(self.wp.current.policy,LONGEST_PREFIX);self.assertEqual(self.wp.current.required,REJECT)
        self.assertFalse(configure(self.wp,REJECT,digest(A))['changed']);self.assertEqual(len(self.wp.config_writes),1)
        with self.assertRaisesRegex(GeofeedError,'hash does not match'):configure(self.wp,LONGEST_PREFIX,'0'*64)
    def test_strict_migration_uses_versioned_guards_after_admin_policy_switch(self):
        self.publish(A);self.publish(B,max_relocated_fraction=1)
        configure(self.wp,REJECT,digest(B))
        strict=render_csv([PARENT])
        with self.assertRaisesRegex(GeofeedError,'location changes'):publish_wordpress(self.wp,strict,self.root)
        result=publish_wordpress(self.wp,strict,self.root,max_relocated_fraction=1)
        self.assertTrue(result['changed']);self.assertEqual(self.wp.current.csv,strict);self.assertEqual(self.wp.current.policy,REJECT)
        recover(self.wp,self.root,digest(strict))
        self.assertEqual(self.wp.current.csv,B);self.assertEqual(self.wp.current.policy,LONGEST_PREFIX)
    def test_policy_cli_uses_only_separate_admin_secret_and_never_reads_input(self):
        factory=Mock(side_effect=RuntimeError('input unavailable'))
        path=self.root/'config.yaml'
        path.write_text(yaml.safe_dump({'source':{'type':'offline_source'},'publish':{'type':'wordpress'},
                                       'overlap_policy':LONGEST_PREFIX,'state_dir':str(self.root/'state')}))
        with patch.dict(SOURCES,{'offline_source':SourceAdapter(factory,initial=False)}), \
             patch('isp_geofeed_generator.publish.WordPress',return_value=self.wp), \
             patch.dict('os.environ',{'WP_POLICY_ADMIN_USERNAME':'policy-admin'}), \
             patch.object(CredentialStore,'get',autospec=True,return_value='synthetic-admin-password') as key, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['configure-wordpress-policy','--config',str(path),'--expected-current-sha256',digest(b'')]),0)
        factory.assert_not_called();self.assertEqual(key.call_args.args[1],'WP_POLICY_ADMIN_APP_PASSWORD')
        self.assertEqual(key.call_count,1)
        status=json.loads((self.root/'state/status.json').read_text())['data']
        self.assertTrue(status['configured_policy']);self.assertFalse(status['healthy'])
    def test_readonly_inspection_uses_publisher_secret_and_never_changes_status_or_input(self):
        self.publish(A);factory=Mock(side_effect=RuntimeError('input unavailable'))
        path=self.root/'inspect.yaml'
        path.write_text(yaml.safe_dump({'source':{'type':'offline_source'},'publish':{'type':'wordpress'},'state_dir':str(self.root/'state')}))
        state=self.root/'state';state.mkdir();status=state/'status.json';status.write_bytes(b'failed-publication-status')
        prior=(status.read_bytes(),status.stat().st_mtime_ns);out=io.StringIO()
        with patch.dict(SOURCES,{'offline_source':SourceAdapter(factory,initial=False)}), \
             patch('isp_geofeed_generator.adapters.WordPress',return_value=self.wp), \
             patch.object(CredentialStore,'get',autospec=True,return_value='synthetic-publisher-password') as key, \
             contextlib.redirect_stdout(out):
            self.assertEqual(main(['inspect-wordpress','--config',str(path)]),0)
        factory.assert_not_called();self.assertEqual(key.call_args.args[1],'WP_APP_PASSWORD');self.assertEqual(key.call_count,1)
        result=json.loads(out.getvalue());self.assertTrue(result['inspection_only']);self.assertTrue(result['public_matches_stored'])
        self.assertTrue(result['policy_state_stable']);self.assertNotIn('healthy',result);self.assertNotIn('csv',result)
        self.assertEqual((status.read_bytes(),status.stat().st_mtime_ns),prior)


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
