import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from isp_geofeed_generator.cli import load_config, main, run_lock
from isp_geofeed_generator.client import GeofeedError
from test_feed import snapshot


class CliTests(unittest.TestCase):
    def test_bad_config_and_unknown_keys_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'config.yaml'
            for content in ('[]', 'unknown: value', 'max_removed_fraction: 2', 'pool_sites: []'):
                p.write_text(content)
                with self.assertRaises(GeofeedError): load_config(p)

    def test_workload_generate_and_publish_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            cfg = p / 'config.yaml'
            cfg.write_text(f'source: {{type: sonar}}\nstate_dir: {p.as_posix()}/state\nallowed_prefixes: [11.22.33.0/24]\npool_sites: {{"101": "11"}}\npublish:\n  type: file\n  path: {p.as_posix()}/public/feed.csv\n')
            with patch.dict('os.environ', {'SONAR_API_TOKEN': 'example-token'}), patch('isp_geofeed_generator.adapters.Sonar') as sonar:
                sonar.return_value.snapshot.return_value = snapshot()
                sonar.return_value.for_publication.side_effect = lambda value: value
                self.assertEqual(main(['generate', '--config', str(cfg), '--output', str(p/'candidate.csv')]), 0)
                self.assertFalse((p/'public/feed.csv').exists())
                self.assertEqual(main(['publish', '--config', str(cfg)]), 0)
            self.assertEqual((p/'candidate.csv').read_bytes(), (p/'public/feed.csv').read_bytes())

    def test_lock_excludes_second_run_and_releases(self):
        with tempfile.TemporaryDirectory() as tmp:
            with run_lock(tmp):
                with self.assertRaises(GeofeedError):
                    with run_lock(tmp): self.fail('second run entered')
            with run_lock(tmp): pass
