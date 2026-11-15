import tempfile
import unittest
from pathlib import Path
from isp_geofeed_generator.client import GeofeedError
from isp_geofeed_generator.feed import digest
from isp_geofeed_generator.publish import publish_file, publish_wordpress, WordPress

OLD = b'11.22.33.0/24,US,US-IL,Old City,\n'
NEW = b'11.22.33.0/24,US,US-IL,New City,\n'


class FakeWP:
    public_url = 'https://www.example.net/wp-json/isp-geofeed-generator/v1/feed'
    def __init__(self, csv=OLD, fail=False, lost_response=False, concurrent=False, rollback_fail=False):
        self.csv, self.fail, self.lost_response = csv, fail, lost_response
        self.concurrent, self.rollback_fail = concurrent, rollback_fail
        self.writes = []
    def state(self): return self.csv
    def replace(self, csv, expected):
        self.writes.append((csv, expected))
        if len(self.writes) > 1 and self.rollback_fail: raise GeofeedError('rollback failed')
        if self.concurrent:
            self.csv = b'11.22.33.0/24,US,US-IL,Concurrent,\n'
            raise GeofeedError('conflict')
        if self.csv != expected: raise GeofeedError('conflict')
        self.csv = csv
        if self.lost_response and len(self.writes) == 1: raise GeofeedError('lost response')
    def read_public(self):
        if self.fail and self.csv == NEW: return b'<html>cached</html>'
        return self.csv


class PublishTests(unittest.TestCase):
    def setUp(self): self.tmp = tempfile.TemporaryDirectory(); self.path = Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def test_publish_and_noop_both_verify_public_read(self):
        wp = FakeWP()
        self.assertTrue(publish_wordpress(wp, NEW, self.path)['changed'])
        self.assertFalse(publish_wordpress(wp, NEW, self.path)['changed'])
        self.assertEqual(len(wp.writes), 1)
        self.assertEqual((self.path / 'last-good.csv').read_bytes(), NEW)

    def test_failed_public_readback_rolls_back(self):
        wp = FakeWP(fail=True)
        with self.assertRaisesRegex(GeofeedError, 'restored'): publish_wordpress(wp, NEW, self.path)
        self.assertEqual(wp.csv, OLD)
        self.assertEqual(len(wp.writes), 2)
        self.assertFalse((self.path / 'last-good.csv').exists())

    def test_first_publication_can_be_rolled_back_to_absent(self):
        wp = FakeWP(csv=b'', fail=True)
        with self.assertRaisesRegex(GeofeedError, 'restored'): publish_wordpress(wp, NEW, self.path)
        self.assertEqual(wp.csv, b'')

    def test_lost_put_response_is_inspected_then_rolled_back(self):
        wp = FakeWP(lost_response=True)
        with self.assertRaisesRegex(GeofeedError, 'restored'): publish_wordpress(wp, NEW, self.path)
        self.assertEqual(wp.csv, OLD)
        self.assertEqual(wp.writes, [(NEW, OLD), (OLD, NEW)])

    def test_concurrent_writer_is_not_overwritten(self):
        wp = FakeWP(concurrent=True)
        with self.assertRaisesRegex(GeofeedError, 'concurrently'): publish_wordpress(wp, NEW, self.path)
        self.assertEqual(len(wp.writes), 1)
        self.assertIn(b'Concurrent', wp.csv)

    def test_failed_rollback_is_not_reported_healthy(self):
        wp = FakeWP(fail=True, rollback_fail=True)
        with self.assertRaisesRegex(GeofeedError, 'Recovery needs attention'): publish_wordpress(wp, NEW, self.path)

    def test_large_removal_stops_before_write(self):
        wp = FakeWP()
        with self.assertRaisesRegex(GeofeedError, 'removal'):
            publish_wordpress(wp, b'11.22.33.0/25,US,US-IL,City,\n', self.path)
        self.assertEqual(wp.writes, [])

    def test_local_publish_keeps_backup_and_enforces_guard(self):
        target = self.path / 'public' / 'geofeed.csv'
        publish_file(target, OLD, self.path)
        publish_file(target, NEW, self.path)
        self.assertEqual(target.read_bytes(), NEW)
        self.assertEqual((self.path / 'before.csv').read_bytes(), OLD)
        with self.assertRaises(GeofeedError): publish_file(target, b'', self.path)
        self.assertEqual(target.read_bytes(), NEW)

    def test_wordpress_state_hash_is_verified(self):
        class HTTP:
            def request(self, *a, **k): return {'csv': OLD.decode(), 'sha256': digest(NEW)}
        wp = WordPress('https://www.example.net', 'user', 'application password', http=HTTP())
        with self.assertRaisesRegex(GeofeedError, 'invalid'): wp.state()
