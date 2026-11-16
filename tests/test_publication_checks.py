"""Uploaded-state verification and preservation of real recovery history."""
import tempfile
import unittest
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
from isp_geofeed_generator.client import GeofeedError
from isp_geofeed_generator.publish import publish_file, publish_wordpress
from isp_geofeed_generator.records import publish_records_file
from test_publish import FakeWP, OLD, NEW


class PublicationChecks(unittest.TestCase):
    def test_identical_csv_does_not_replace_feed_or_recovery_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target=root/'feed.csv'
            publish_file(target,OLD,root)
            publish_file(target,NEW,root,max_relocated_fraction=1)
            before_stat=target.stat();backup=(root/'before.csv').read_bytes();backup_stat=(root/'before.csv').stat()
            result=publish_file(target,NEW,root)
            self.assertFalse(result['changed']);self.assertEqual(target.stat().st_mtime_ns,before_stat.st_mtime_ns)
            self.assertEqual(result['verification'],'local-bytes');self.assertFalse(result['recovery_backup_changed'])
            self.assertEqual((root/'before.csv').read_bytes(),backup)
            self.assertEqual((root/'before.csv').stat().st_mtime_ns,backup_stat.st_mtime_ns)

    def test_identical_json_keeps_previous_version_backup(self):
        records=[{'prefix':'11.22.33.0/24','location':{'latitude':41.9,'longitude':-88.7}}]
        changed=[{'prefix':'11.22.33.0/24','location':{'latitude':42,'longitude':-88.7}}]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target=root/'records.json'
            publish_records_file(target,records,root);publish_records_file(target,changed,root,max_relocated_fraction=1)
            backup=(root/'before-records.json').read_bytes();stamp=target.stat().st_mtime_ns
            self.assertFalse(publish_records_file(target,changed,root)['changed'])
            self.assertEqual(target.stat().st_mtime_ns,stamp)
            self.assertEqual((root/'before-records.json').read_bytes(),backup)

    def test_unchanged_wordpress_keeps_recovery_history_and_makes_no_put(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);wp=FakeWP()
            publish_wordpress(wp,NEW,root,max_relocated_fraction=1)
            backup=(root/'before.csv').read_bytes();stamp=(root/'last-good.csv').stat().st_mtime_ns
            self.assertFalse(publish_wordpress(wp,NEW,root)['changed'])
            self.assertEqual(len(wp.writes),1)
            self.assertEqual((root/'before.csv').read_bytes(),backup)
            self.assertEqual((root/'last-good.csv').stat().st_mtime_ns,stamp)

    def test_public_state_mismatch_stops_before_changed_publication(self):
        class StalePublic(FakeWP):
            def read_public(self):return b'11.22.33.0/24,US,US-IL,Stale City,\n'
        with tempfile.TemporaryDirectory() as tmp:
            wp=StalePublic()
            with self.assertRaises(GeofeedError):publish_wordpress(wp,NEW,tmp,max_relocated_fraction=1)
            self.assertEqual(wp.writes,[]);self.assertEqual(wp.csv,OLD)
            self.assertFalse((Path(tmp)/'before.csv').exists())

    def test_noop_cannot_report_success_after_authenticated_state_changes(self):
        class ChangesDuringPublicRead(FakeWP):
            def read_public(self):
                self.csv=NEW
                return OLD
        with tempfile.TemporaryDirectory() as tmp:
            wp=ChangesDuringPublicRead()
            with self.assertRaises(GeofeedError):publish_wordpress(wp,OLD,tmp)
            self.assertEqual(wp.writes,[]);self.assertEqual(wp.csv,NEW)

    def test_noop_with_bad_public_delivery_is_failure_and_preserves_backup(self):
        class BrokenPublic(FakeWP):
            def read_public(self):raise GeofeedError('Public delivery unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);backup=root/'before.csv';backup.write_bytes(b'recovery sentinel')
            wp=BrokenPublic()
            with self.assertRaises(GeofeedError):publish_wordpress(wp,OLD,root)
            self.assertEqual(backup.read_bytes(),b'recovery sentinel');self.assertEqual(wp.writes,[])

    def test_local_noop_readback_change_is_not_blindly_restored(self):
        from isp_geofeed_generator import local_output
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target=root/'feed.csv';target.write_bytes(OLD)
            read=local_output.read_output;calls=0
            def change(path,limit):
                nonlocal calls
                calls+=1
                if calls==2:target.write_bytes(NEW)
                return read(path,limit)
            with patch.object(local_output,'read_output',side_effect=change),self.assertRaisesRegex(GeofeedError,'unchanged-content'):
                publish_file(target,OLD,root)
            self.assertEqual(target.read_bytes(),NEW);self.assertFalse((root/'before.csv').exists())

    def test_target_lock_is_shared_across_state_directories_and_released_after_failure(self):
        from isp_geofeed_generator.local_output import output_lock
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target=root/'feed.csv';target.write_bytes(OLD)
            with output_lock(target):
                with self.assertRaisesRegex(GeofeedError,'destination output lock'):
                    publish_file(target,NEW,root/'other-state',max_relocated_fraction=1)
                self.assertEqual(target.read_bytes(),OLD)
            self.assertTrue(publish_file(target,NEW,root/'other-state',max_relocated_fraction=1)['changed'])

    def test_destination_lock_blocks_another_process_with_a_different_state_directory(self):
        from isp_geofeed_generator.local_output import output_lock
        code='''import sys
from isp_geofeed_generator.publish import publish_file
from isp_geofeed_generator.client import GeofeedError
try: publish_file(sys.argv[1],b'11.22.33.0/24,US,US-IL,New City,\\n',sys.argv[2],max_relocated_fraction=1)
except GeofeedError as exc:
    assert 'destination output lock' in str(exc)
    print('blocked')
else: raise AssertionError('Concurrent writer was not blocked')
'''
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target=root/'feed.csv';target.write_bytes(OLD)
            with output_lock(target):
                result=subprocess.run([sys.executable,'-c',code,str(target),str(root/'child-state')],
                    cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(result.stdout.strip(),'blocked')
            self.assertEqual(target.read_bytes(),OLD)

    def test_postwrite_state_change_cannot_be_reported_healthy_or_overwritten(self):
        external=b'11.22.33.0/24,US,US-IL,External,\n'
        class ChangedAfterPublicRead(FakeWP):
            def read_public(self):
                data=self.csv
                if self.writes and data==NEW:self.csv=external
                return data
        with tempfile.TemporaryDirectory() as tmp:
            wp=ChangedAfterPublicRead()
            with self.assertRaisesRegex(GeofeedError,'Recovery needs attention'):
                publish_wordpress(wp,NEW,tmp,max_relocated_fraction=1)
            self.assertEqual(len(wp.writes),1);self.assertEqual(wp.csv,external)

    def test_edit_before_atomic_replacement_is_not_overwritten(self):
        from isp_geofeed_generator import local_output
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target=root/'feed.csv';target.write_bytes(OLD)
            read=local_output.read_output;calls=0;external=b'11.22.33.0/24,US,US-IL,External,\n'
            def change(path,limit):
                nonlocal calls
                calls+=1
                if calls==2:target.write_bytes(external)
                return read(path,limit)
            with patch.object(local_output,'read_output',side_effect=change),self.assertRaisesRegex(GeofeedError,'before replacement'):
                publish_file(target,NEW,root,max_relocated_fraction=1)
            self.assertEqual(target.read_bytes(),external);self.assertEqual((root/'before.csv').read_bytes(),OLD)

    def test_failed_local_postwrite_verification_preserves_external_bytes_and_backup(self):
        from isp_geofeed_generator import local_output
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target=root/'feed.csv';target.write_bytes(OLD)
            read=local_output.read_output;calls=0;external=b'11.22.33.0/24,US,US-IL,External,\n'
            def change(path,limit):
                nonlocal calls
                calls+=1
                if calls==3:target.write_bytes(external)
                return read(path,limit)
            with patch.object(local_output,'read_output',side_effect=change),self.assertRaisesRegex(GeofeedError,'recovery needs attention'):
                publish_file(target,NEW,root,max_relocated_fraction=1)
            self.assertEqual(target.read_bytes(),external);self.assertEqual((root/'before.csv').read_bytes(),OLD)

    def test_oversized_existing_file_fails_without_overwrite_or_backup_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target=root/'feed.csv';target.write_bytes(b'x'*1_000_001)
            backup=root/'before.csv';backup.write_bytes(b'recovery sentinel')
            with self.assertRaisesRegex(GeofeedError,'size limit'):publish_file(target,NEW,root)
            self.assertEqual(target.stat().st_size,1_000_001);self.assertEqual(backup.read_bytes(),b'recovery sentinel')

    @unittest.skipUnless(os.name=='posix','Symlink creation requires privileges on Windows')
    def test_output_symlink_is_refused_without_touching_its_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);actual=root/'actual.csv';actual.write_bytes(OLD);link=root/'feed.csv';link.symlink_to(actual)
            with self.assertRaisesRegex(GeofeedError,'symlink'):publish_file(link,NEW,root,max_relocated_fraction=1)
            self.assertTrue(link.is_symlink());self.assertEqual(actual.read_bytes(),OLD)
