"""Identity failures remain strict and identify fields without leaking values."""
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace, ModuleType
import unittest
from unittest.mock import patch

from isp_geofeed_generator import bound_output,local_output
from isp_geofeed_generator.client import GeofeedError
from isp_geofeed_generator.feed import digest,render_csv
from isp_geofeed_generator.overlap import LONGEST_PREFIX
from isp_geofeed_generator.publish import publish_file
from test_nested_core import PARENT,CHILD


class FileIdentityTests(unittest.TestCase):
    def test_fixed_field_labels_do_not_expose_values(self):
        before=local_output.FileState(b'PRIVATE OLD',(1,2,3,4,5))
        self.assertEqual(local_output.change_description(before,before),'unknown')
        for index,name in enumerate(('device','file_id','size','mtime','ctime')):
            identity=list(before.identity);identity[index]+=1000000
            after=local_output.FileState(before.data,tuple(identity))
            self.assertEqual(local_output.change_description(before,after),name)
        after=local_output.FileState(b'PRIVATE NEW',(11,12,13,14,15))
        self.assertEqual(local_output.change_description(before,after),'content,device,file_id,size,mtime,ctime')
        self.assertEqual(local_output.change_description(before,local_output.FileState(b'',None)),'content,existence')

    def test_read_rejects_ctime_only_change(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'PRIVATE';path.write_bytes(b'synthetic')
            with path.open('rb') as stream:before=os.fstat(stream.fileno())
            after=SimpleNamespace(st_dev=before.st_dev,st_ino=before.st_ino,st_size=before.st_size,
                                  st_mtime_ns=before.st_mtime_ns,st_ctime_ns=before.st_ctime_ns+1)
            with patch.object(local_output.os,'fstat',side_effect=[before,after]),self.assertRaises(GeofeedError) as caught:
                local_output.read_output(path,100)
            self.assertIn('[changed: ctime]',str(caught.exception))
            self.assertNotIn('PRIVATE',str(caught.exception));self.assertEqual(path.read_bytes(),b'synthetic')

    def test_pair_guard_rejects_each_identity_field_and_content(self):
        first=local_output.FileState(b'PRIVATE CONTENT',(1,2,15,4,5))
        metadata=local_output.FileState(b'PRIVATE POLICY',(1,3,14,6,7))
        path=Path('PRIVATE')
        for role,baseline in (('feed',first),('policy',metadata)):
            for index,name in enumerate(('device','file_id','size','mtime','ctime','content')):
                values=list(baseline.identity)
                if name!='content':values[index]+=1
                changed=local_output.FileState(b'PRIVATE DIFFERENT' if name=='content' else baseline.data,tuple(values))
                reads=[changed] if role=='feed' else [first,changed]
                with self.subTest(role=role,field=name),patch.object(bound_output,'read_output',side_effect=reads),self.assertRaises(GeofeedError) as caught:
                    bound_output.same_pair(path,first,metadata,100)
                self.assertIn(f'[{role} changed: {name}]',str(caught.exception))
                self.assertNotIn('PRIVATE',str(caught.exception))

    def test_pair_guard_rejects_same_bytes_replacement_and_new_policy_owner(self):
        first=local_output.FileState(b'same',(1,2,4,5,6));policy=local_output.FileState(b'owner A',(1,3,7,8,9))
        with patch.object(bound_output,'read_output',return_value=local_output.FileState(b'same',(1,99,4,5,6))),self.assertRaisesRegex(GeofeedError,'file_id'):
            bound_output.same_pair(Path('file'),first,policy,100)
        with patch.object(bound_output,'read_output',side_effect=[first,local_output.FileState(b'owner B',policy.identity)]),self.assertRaisesRegex(GeofeedError,'policy changed: content'):
            bound_output.same_pair(Path('file'),first,policy,100)

    def test_diagnostic_is_not_a_retry_or_metadata_only_acceptance(self):
        first=local_output.FileState(b'same',(1,2,4,5,6));policy=local_output.FileState(b'owner A',(1,3,7,8,9))
        changed=local_output.FileState(first.data,(1,2,4,5,99))
        with patch.object(bound_output,'read_output',return_value=changed) as read,self.assertRaisesRegex(GeofeedError,'ctime'):
            bound_output.same_pair(Path('file'),first,policy,100)
        self.assertEqual(read.call_count,1,'stop after first changed component without rereading to accept it')

    def test_private_ctime_guard_removal_is_caught(self):
        source=Path(local_output.__file__).read_text(encoding='utf-8')
        find='info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns'
        self.assertEqual(source.count(find),1)
        def run():
            result=unittest.TestResult();FileIdentityTests('test_read_rejects_ctime_only_change').run(result);return result
        self.assertTrue(run().wasSuccessful())
        module=ModuleType('isp_geofeed_generator._private_identity_control');module.__package__='isp_geofeed_generator'
        exec(compile(source.replace(find,'info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, 0'),'<private ctime control>','exec'),module.__dict__)
        with patch.object(local_output,'read_output',module.read_output):result=run()
        self.assertEqual(result.errors,[]);self.assertEqual(len(result.failures),1)
        self.assertTrue(run().wasSuccessful())
        print('FILE IDENTITY MUTATION OBSERVATION: '+json.dumps({'ctime_guard_removed':True,'assertion_failures':1,
                                                              'errors':0,'intact_before_after':True}))


@unittest.skipUnless(os.name=='nt','requires native Windows file metadata')
class NativeWindowsIdentityTests(unittest.TestCase):
    def setUp(self):
        import ctypes
        from ctypes import wintypes
        self.ctypes=ctypes;self.types=wintypes
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        self.kernel.GetFileAttributesW.argtypes=[wintypes.LPCWSTR];self.kernel.GetFileAttributesW.restype=wintypes.DWORD
        self.kernel.SetFileAttributesW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD];self.kernel.SetFileAttributesW.restype=wintypes.BOOL
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.target=self.root/'feed.csv';self.state=self.root/'state'
        self.first=render_csv([PARENT],overlap_policy=LONGEST_PREFIX)
        self.second=render_csv([PARENT,CHILD],overlap_policy=LONGEST_PREFIX)
        publish_file(self.target,self.first,self.state,overlap_policy=LONGEST_PREFIX)

    def toggle_attribute(self,path):
        original=self.kernel.GetFileAttributesW(str(path));self.assertNotEqual(original,0xffffffff)
        try:
            self.assertTrue(self.kernel.SetFileAttributesW(str(path),original ^ 1))
        finally:self.assertTrue(self.kernel.SetFileAttributesW(str(path),original))

    def observe(self,path):
        with path.open('rb') as stream:info=os.fstat(stream.fileno());data=stream.read()
        return info,data

    def stop_after_candidate(self,mutate,kind):
        policy=bound_output.policy_path(self.target);old_policy=policy.read_bytes();original=bound_output.atomic_write
        seen={}
        def write(path,data,*args,**kwargs):
            if Path(path)==policy and not seen:
                before,old_bytes=self.observe(self.target)
                # Timestamp precision varies between Windows filesystems/runners.
                # Separate this deliberate mutation from the preceding rename;
                # still require an actual observed change, never just API success.
                time.sleep(0.05)
                restore=mutate(self.target)
                after,new_bytes=self.observe(self.target)
                self.assertEqual(old_bytes,new_bytes);self.assertEqual(old_bytes,self.second)
                self.assertEqual((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns),
                                 (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns))
                self.assertNotEqual(before.st_ctime_ns,after.st_ctime_ns)
                seen.update(metadata_changed=True,restore=restore)
            return original(path,data,*args,**kwargs)
        with patch.object(bound_output,'atomic_write',side_effect=write),self.assertRaisesRegex(GeofeedError,'feed changed: ctime'):
            publish_file(self.target,self.second,self.state,overlap_policy=LONGEST_PREFIX,max_relocated_fraction=1)
        self.assertTrue(seen['metadata_changed'])
        self.assertEqual(self.target.read_bytes(),self.second);self.assertEqual(policy.read_bytes(),old_policy)
        self.assertEqual((self.state/'before.csv').read_bytes(),self.first)
        with self.assertRaisesRegex(GeofeedError,'incomplete or mismatched'):
            publish_file(self.target,self.second,self.state,overlap_policy=LONGEST_PREFIX)
        if seen['restore'] is not None:seen['restore']();seen['restore']=None
        result=bound_output.recover_bound(self.target,self.state,'csv',digest(self.second))
        self.assertTrue(result['recovered']);self.assertEqual(self.target.read_bytes(),self.first)
        self.assertEqual(policy.read_bytes(),old_policy)
        print('WINDOWS IDENTITY OBSERVATION: '+json.dumps({'mutation':kind,'bytes_and_file_id_unchanged':True,
            'mtime_unchanged':True,'ctime_changed':True,'automatic_continuation_refused':True,
            'policy_preserved':True,'checked_recovery_verified':True,'pre_mutation_wait_seconds':0.05}))

    def test_real_attribute_round_trip_stops_and_checked_recovery_works(self):
        self.stop_after_candidate(self.toggle_attribute,'attribute-round-trip')

    def test_real_acl_protection_change_stops_and_checked_recovery_works(self):
        import ctypes
        from ctypes import wintypes
        advapi=ctypes.WinDLL('advapi32',use_last_error=True)
        advapi.GetNamedSecurityInfoW.argtypes=[wintypes.LPWSTR,ctypes.c_int,wintypes.DWORD,ctypes.c_void_p,
            ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p),ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p)]
        advapi.GetNamedSecurityInfoW.restype=wintypes.DWORD
        advapi.SetNamedSecurityInfoW.argtypes=[wintypes.LPWSTR,ctypes.c_int,wintypes.DWORD,ctypes.c_void_p,
            ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p];advapi.SetNamedSecurityInfoW.restype=wintypes.DWORD
        advapi.GetSecurityDescriptorControl.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ushort),ctypes.POINTER(wintypes.DWORD)]
        advapi.GetSecurityDescriptorControl.restype=wintypes.BOOL
        self.kernel.LocalFree.argtypes=[ctypes.c_void_p];self.kernel.LocalFree.restype=ctypes.c_void_p
        def mutate(path):
            dacl=ctypes.c_void_p();descriptor=ctypes.c_void_p();flags=ctypes.c_ushort();revision=wintypes.DWORD()
            error=advapi.GetNamedSecurityInfoW(str(path),1,4,None,None,ctypes.byref(dacl),None,ctypes.byref(descriptor))
            self.assertEqual(error,0)
            self.addCleanup(lambda:self.kernel.LocalFree(descriptor))
            self.assertTrue(advapi.GetSecurityDescriptorControl(descriptor,ctypes.byref(flags),ctypes.byref(revision)))
            was_protected=bool(flags.value & 0x1000)
            size=ctypes.cast(dacl,ctypes.POINTER(ctypes.c_ushort))[1]
            original_acl=ctypes.string_at(dacl,size)
            restored=False
            def verify(protected):
                current_dacl=ctypes.c_void_p();current_descriptor=ctypes.c_void_p()
                self.assertEqual(advapi.GetNamedSecurityInfoW(str(path),1,4,None,None,ctypes.byref(current_dacl),None,
                                                            ctypes.byref(current_descriptor)),0)
                try:
                    current_flags=ctypes.c_ushort();current_revision=wintypes.DWORD()
                    self.assertTrue(advapi.GetSecurityDescriptorControl(current_descriptor,ctypes.byref(current_flags),ctypes.byref(current_revision)))
                    self.assertEqual(bool(current_flags.value & 0x1000),protected)
                    if protected==was_protected:
                        current_size=ctypes.cast(current_dacl,ctypes.POINTER(ctypes.c_ushort))[1]
                        self.assertEqual(ctypes.string_at(current_dacl,current_size),original_acl)
                finally:self.kernel.LocalFree(current_descriptor)
            def set_protection(protected):
                result=advapi.SetNamedSecurityInfoW(str(path),1,4|(0x80000000 if protected else 0x20000000),None,None,dacl,None)
                self.assertEqual(result,0)
            def restore():
                nonlocal restored
                if not restored:
                    set_protection(was_protected);verify(was_protected);restored=True
            self.addCleanup(restore)
            set_protection(not was_protected)
            verify(not was_protected)
            return restore
        self.stop_after_candidate(mutate,'acl-protection')
