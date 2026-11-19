"""Bounded Windows rename retries preserve guards and do not repeat writes."""
import errno
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, call, patch

from isp_geofeed_generator import publish
from isp_geofeed_generator import bound_output
from isp_geofeed_generator.client import GeofeedError
from isp_geofeed_generator.feed import render_csv
from isp_geofeed_generator.feed import digest
from isp_geofeed_generator.overlap import LONGEST_PREFIX
from test_nested_core import PARENT,CHILD


def denied(code=5):
    error=PermissionError(errno.EACCES,'synthetic replacement denial')
    if code is not None:error.winerror=code
    return error


class AtomicReplaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.target=self.root/'output'
        self.target.write_bytes(b'old')

    def assert_clean(self):
        self.assertEqual({p.name for p in self.root.iterdir()},{'output'})

    def test_transient_windows_codes_reuse_one_written_temp_and_recheck_guard(self):
        original_replace=os.replace
        for code in (5,32,33):
            with self.subTest(code=code):
                self.target.write_bytes(b'old');attempts=[];guard=Mock()
                def replace(source,target):
                    attempts.append((source,Path(target),Path(source).read_bytes()))
                    if len(attempts)<3:raise denied(code)
                    return original_replace(source,target)
                with patch.object(publish,'_WINDOWS_REPLACE',True), \
                     patch.object(publish.os,'replace',side_effect=replace), \
                     patch.object(publish.time,'sleep') as sleep, \
                     patch.object(publish.os,'fsync',wraps=os.fsync) as sync, \
                     patch.object(publish.tempfile,'mkstemp',wraps=tempfile.mkstemp) as temporary:
                    publish.atomic_write(self.target,b'new',before_replace=guard)
                self.assertEqual(self.target.read_bytes(),b'new')
                self.assertEqual(len(attempts),3)
                self.assertEqual(len({source for source,_,_ in attempts}),1)
                self.assertTrue(all(target==self.target and data==b'new' for _,target,data in attempts))
                self.assertEqual(guard.call_count,3)
                self.assertEqual(sync.call_count,1);self.assertEqual(temporary.call_count,1)
                self.assertEqual(sleep.call_args_list,[call(0.05),call(0.05)])
                self.assert_clean()

    def test_persistent_windows_denial_stops_after_five_attempts(self):
        error=denied(5);guard=Mock()
        with patch.object(publish,'_WINDOWS_REPLACE',True), \
             patch.object(publish.os,'replace',side_effect=error) as replace, \
             patch.object(publish.time,'sleep') as sleep, self.assertRaises(PermissionError) as caught:
            publish.atomic_write(self.target,b'new',before_replace=guard)
        self.assertIs(caught.exception,error)
        self.assertEqual(replace.call_count,5);self.assertEqual(guard.call_count,5)
        self.assertEqual(sleep.call_args_list,[call(0.05)]*4)
        self.assertEqual(self.target.read_bytes(),b'old');self.assert_clean()

    def test_other_errors_and_posix_are_not_retried(self):
        for windows,error in ((False,denied(5)),(True,denied(None)),(True,denied(2)),
                              (True,OSError(errno.ENOSPC,'synthetic disk full')),
                              (True,FileNotFoundError('synthetic missing source'))):
            with self.subTest(windows=windows,error=type(error).__name__,code=getattr(error,'winerror',None)):
                with patch.object(publish,'_WINDOWS_REPLACE',windows), \
                     patch.object(publish.os,'replace',side_effect=error) as replace, \
                     patch.object(publish.time,'sleep') as sleep, self.assertRaises(OSError) as caught:
                    publish.atomic_write(self.target,b'new')
                self.assertIs(caught.exception,error);self.assertEqual(replace.call_count,1)
                sleep.assert_not_called();self.assertEqual(self.target.read_bytes(),b'old');self.assert_clean()

    def test_guard_failure_is_never_retried(self):
        guard=Mock(side_effect=denied(5))
        with patch.object(publish,'_WINDOWS_REPLACE',True), patch.object(publish.os,'replace') as replace, \
             patch.object(publish.time,'sleep') as sleep, self.assertRaises(PermissionError):
            publish.atomic_write(self.target,b'new',before_replace=guard)
        guard.assert_called_once();replace.assert_not_called();sleep.assert_not_called()
        self.assertEqual(self.target.read_bytes(),b'old');self.assert_clean()

    def test_real_local_publisher_preserves_writer_that_wins_during_wait(self):
        old=render_csv([PARENT]);new=old.replace(b',A,',b',B,');winner=old.replace(b',A,',b',Winner,')
        self.assertNotEqual(old,new);self.assertNotEqual(old,winner)
        self.target.write_bytes(old);state=self.root/'state';original_replace=os.replace;attempts=[]
        def replace(source,target):
            if Path(target)==self.target:
                attempts.append(source)
                if len(attempts)==1:raise denied(32)
            return original_replace(source,target)
        def intervening_writer(_):self.target.write_bytes(winner)
        with patch.object(publish,'_WINDOWS_REPLACE',True), \
             patch.object(publish.os,'replace',side_effect=replace), \
             patch.object(publish.time,'sleep',side_effect=intervening_writer) as sleep, \
             self.assertRaisesRegex(GeofeedError,'changed before replacement'):
            publish.publish_file(self.target,new,state,max_relocated_fraction=1)
        self.assertEqual(len(attempts),1);sleep.assert_called_once_with(0.05)
        self.assertEqual(self.target.read_bytes(),winner)
        self.assertEqual((state/'before.csv').read_bytes(),old)
        self.assertFalse(any(p.name.startswith('.output.') for p in self.root.iterdir()))

    def test_initial_guard_refusal_does_not_sleep_or_replace(self):
        guard=Mock(side_effect=GeofeedError('changed by another owner'))
        with patch.object(publish,'_WINDOWS_REPLACE',True), patch.object(publish.os,'replace') as replace, \
             patch.object(publish.time,'sleep') as sleep, self.assertRaisesRegex(GeofeedError,'another owner'):
            publish.atomic_write(self.target,b'new',before_replace=guard)
        replace.assert_not_called();sleep.assert_not_called();guard.assert_called_once()
        self.assertEqual(self.target.read_bytes(),b'old');self.assert_clean()

    def check_policy_replacement_and_history(self, *, separate_retry=False):
        target=self.root/'nested.csv';state=self.root/'state'
        first=render_csv([PARENT],overlap_policy=LONGEST_PREFIX)
        second=render_csv([PARENT,CHILD],overlap_policy=LONGEST_PREFIX)
        publish.publish_file(target,first,state,overlap_policy=LONGEST_PREFIX)
        policy=bound_output.policy_path(target);original_replace=os.replace;calls=[]
        original_atomic=bound_output.atomic_write;active=[];delays={};injected=[]
        journal=state/'local-transaction.json'
        def atomic(path,*args,**kwargs):
            active.append(Path(path))
            try:return original_atomic(path,*args,**kwargs)
            finally:active.pop()
        def pause(delay):
            delays.setdefault(active[-1] if active else None,[]).append(delay)
        def replace(source,destination):
            if Path(destination)==policy:
                calls.append(source)
                if len(calls)<3:raise denied(5)
            elif separate_retry and Path(destination)==journal and not injected:
                injected.append(32);raise denied(32)
            return original_replace(source,destination)
        with patch.object(publish,'_WINDOWS_REPLACE',True),patch.object(publish.os,'replace',side_effect=replace), \
             patch.object(bound_output,'atomic_write',side_effect=atomic), \
             patch.object(publish.time,'sleep',side_effect=pause):
            result=publish.publish_file(target,second,state,overlap_policy=LONGEST_PREFIX,max_relocated_fraction=1)
        self.assertTrue(result['changed']);self.assertEqual(len(calls),3)
        self.assertEqual(len(set(calls)),1);self.assertEqual(delays.get(policy),[0.05,0.05])
        if separate_retry:
            self.assertEqual(injected,[32]);self.assertGreaterEqual(len(delays.get(journal,[])),1)
        stamps={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in (target,policy,*state.iterdir())}
        with patch.object(publish.os,'replace') as replace:
            self.assertFalse(publish.publish_file(target,second,state,overlap_policy=LONGEST_PREFIX)['changed'])
        replace.assert_not_called()
        self.assertEqual({p:(p.read_bytes(),p.stat().st_mtime_ns) for p in stamps},stamps)
        if separate_retry:
            print('POLICY RETRY SCOPE OBSERVATION: '+json.dumps({'injected_policy_denials':2,
                'policy_attempts':len(calls),'policy_sleeps':delays[policy],
                'injected_nonpolicy_denials':len(injected),'nonpolicy_sleeps':len(delays.get(journal,[])),
                'pair_verified':True,'noop_history_preserved':True}))

    def test_transient_policy_replacement_finishes_valid_pair_and_noop_preserves_history(self):
        self.check_policy_replacement_and_history()

    def test_nonpolicy_retry_does_not_pollute_policy_delay_measurement(self):
        self.check_policy_replacement_and_history(separate_retry=True)

    def test_persistent_policy_denial_retains_baseline_and_requires_checked_recovery(self):
        target=self.root/'nested.csv';state=self.root/'state'
        first=render_csv([PARENT],overlap_policy=LONGEST_PREFIX)
        second=render_csv([PARENT,CHILD],overlap_policy=LONGEST_PREFIX)
        publish.publish_file(target,first,state,overlap_policy=LONGEST_PREFIX)
        policy=bound_output.policy_path(target);prior=policy.read_bytes();original_replace=os.replace;calls=[]
        def replace(source,destination):
            if Path(destination)==policy:
                calls.append(source);raise denied(32)
            return original_replace(source,destination)
        with patch.object(publish,'_WINDOWS_REPLACE',True),patch.object(publish.os,'replace',side_effect=replace), \
             patch.object(publish.time,'sleep') as sleep,self.assertRaisesRegex(GeofeedError,'recovery needs attention'):
            publish.publish_file(target,second,state,overlap_policy=LONGEST_PREFIX,max_relocated_fraction=1)
        self.assertEqual(len(calls),5);self.assertEqual(sleep.call_count,4)
        self.assertEqual(target.read_bytes(),second);self.assertEqual(policy.read_bytes(),prior)
        self.assertEqual((state/'before.csv').read_bytes(),first)
        with self.assertRaisesRegex(GeofeedError,'incomplete or mismatched'):
            publish.publish_file(target,second,state,overlap_policy=LONGEST_PREFIX)
        bound_output.recover_bound(target,state,'csv',digest(second))
        self.assertEqual(target.read_bytes(),first);self.assertEqual(policy.read_bytes(),prior)

    @unittest.skipUnless(os.name=='nt','requires real Windows sharing semantics')
    def test_real_windows_handle_denies_replace_then_release_allows_retry(self):
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,
                                    wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
        kernel.CreateFileW.restype=wintypes.HANDLE
        kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle.restype=wintypes.BOOL
        handle=kernel.CreateFileW(str(self.target),0x80000000,0x1|0x2,None,3,0x80,None)
        self.assertNotEqual(handle,ctypes.c_void_p(-1).value)
        self.assertTrue(handle)
        original_replace=os.replace;original_sleep=publish.time.sleep;observations=[];guard=Mock()
        def replace(source,target):
            try:return original_replace(source,target)
            except PermissionError as error:
                observations.append(error.winerror)
                raise
        def release(delay):
            nonlocal handle
            if handle:
                self.assertTrue(kernel.CloseHandle(handle));handle=None
            original_sleep(delay)
        try:
            with patch.object(publish.os,'replace',side_effect=replace) as replace_call, \
                 patch.object(publish.time,'sleep',side_effect=release):
                publish.atomic_write(self.target,b'new',before_replace=guard)
            self.assertGreaterEqual(len(observations),1)
            self.assertTrue(all(code in (5,32,33) for code in observations))
            self.assertGreaterEqual(replace_call.call_count,2)
            self.assertLessEqual(replace_call.call_count,5)
            self.assertEqual(guard.call_count,replace_call.call_count)
            self.assertEqual(self.target.read_bytes(),b'new');self.assert_clean()
            print('WINDOWS REPLACE OBSERVATION: '+json.dumps({'denial_codes':observations,
                'replace_attempts':replace_call.call_count,'guard_checks':guard.call_count,'new_bytes_verified':True}))
        finally:
            if handle:kernel.CloseHandle(handle)
