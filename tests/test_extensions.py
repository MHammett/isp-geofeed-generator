import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from isp_geofeed_generator.adapters import SOURCES, TARGETS
from isp_geofeed_generator.client import GeofeedError
from isp_geofeed_generator.contracts import SourceAdapter, TargetAdapter
from isp_geofeed_generator.credentials import CredentialStore
from isp_geofeed_generator.extensions import load_extensions
from isp_geofeed_generator.cli import load_config
from isp_geofeed_generator.sdk import builtin_source, builtin_target
from test_feed import snapshot


class ExtensionTests(unittest.TestCase):
    def entry(self, name='local_source', value=None):
        point = Mock(); point.name = name
        point.load.return_value = value if value is not None else SourceAdapter(lambda s, c: None)
        return point

    def test_disabled_packages_are_never_discovered_or_imported(self):
        with patch('isp_geofeed_generator.extensions.metadata.entry_points') as entries:
            sources, targets = load_extensions(None, SOURCES, TARGETS)
        entries.assert_not_called()
        self.assertEqual(set(sources), set(SOURCES))
        self.assertEqual(set(targets), set(TARGETS))

    def test_only_explicitly_enabled_entry_point_is_loaded_without_global_mutation(self):
        chosen = self.entry(); other = self.entry('other')
        with patch('isp_geofeed_generator.extensions.metadata.entry_points', return_value=[chosen, other]):
            sources, _ = load_extensions({'sources': ['local_source']}, SOURCES, TARGETS)
        chosen.load.assert_called_once(); other.load.assert_not_called()
        self.assertIn('local_source', sources)
        self.assertNotIn('local_source', SOURCES)
        self.assertTrue(sources['local_source'].initial)

    def test_missing_duplicate_builtin_collision_and_bad_enable_lists_fail(self):
        for settings, entries in (({'sources': ['missing']}, []),
                                  ({'sources': ['local_source']}, [self.entry(), self.entry()]),
                                  ({'sources': ['sonar']}, [self.entry('sonar')]),
                                  ({'sources': ['local_source', 'local_source']}, [self.entry()]),
                                  ({'sources': ['../module.py']}, []), ({'paths': ['somewhere']}, [])):
            with patch('isp_geofeed_generator.extensions.metadata.entry_points', return_value=entries), self.assertRaises(GeofeedError):
                load_extensions(settings, SOURCES, TARGETS)
            for point in entries: point.load.assert_not_called()

    def test_wrong_version_contract_type_and_raw_import_error_fail_safely(self):
        for value in (SourceAdapter(lambda s, c: None, api_version=2), TargetAdapter(lambda s, c: None),
                      SourceAdapter(None), SourceAdapter(lambda s, c: None, initial='yes'),
                      SourceAdapter(lambda s, c: None, settings=frozenset({'type'}))):
            point = self.entry(value=value)
            with patch('isp_geofeed_generator.extensions.metadata.entry_points', return_value=[point]), self.assertRaisesRegex(GeofeedError, 'incompatible'):
                load_extensions({'sources': ['local_source']}, SOURCES, TARGETS)
        point = self.entry(); point.load.side_effect = RuntimeError('private import failure payload')
        with patch('isp_geofeed_generator.extensions.metadata.entry_points', return_value=[point]), self.assertRaises(GeofeedError) as result:
            load_extensions({'sources': ['local_source']}, SOURCES, TARGETS)
        self.assertNotIn('private import failure', str(result.exception))

    def test_extension_credentials_use_existing_store_rules(self):
        store = CredentialStore({'EXT_EXAMPLE_TOKEN': 'env:EXT_EXAMPLE_TOKEN'}, {'EXT_EXAMPLE_TOKEN': 'example-secret'})
        self.assertEqual(store.get('EXT_EXAMPLE_TOKEN'), 'example-secret')
        self.assertEqual(store.redact('error example-secret'), 'error [REDACTED]')
        for name in ('OTHER_TOKEN', 'EXT_../file', 'EXT_lowercase'):
            with self.assertRaises(GeofeedError): CredentialStore({name: 'env:'+name})
        with self.assertRaises(GeofeedError): CredentialStore({'EXT_EXAMPLE_TOKEN': 'literal secret'})

    def test_extension_settings_are_not_subject_to_another_platforms_rules(self):
        adapter = SourceAdapter(lambda s, c: None, settings=frozenset({'prefix_ids'}))
        point = self.entry(value=adapter)
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp)/'config.yaml'
            cfg.write_text('extensions: {sources: [local_source]}\nsource: {type: local_source, prefix_ids: own-format}\n')
            with patch('isp_geofeed_generator.extensions.metadata.entry_points', return_value=[point]):
                self.assertEqual(load_config(cfg)['source']['prefix_ids'], 'own-format')
            cfg.write_text('source: {type: netbox, prefix_ids: own-format}\n')
            with self.assertRaisesRegex(GeofeedError, 'must be a list'): load_config(cfg)

    def test_sdk_wrappers_reuse_builtins_without_requesting_unrelated_credentials(self):
        credentials = Mock()
        credentials.get.return_value = 'fake-token'
        with patch.dict('os.environ', {'GAIIA_URL': 'https://example.net/api/v1'}):
            source = builtin_source('gaiia', {'site_ids': ['example-site']}, credentials)
        self.assertTrue(callable(source.snapshot))
        credentials.get.assert_called_once_with('GAIIA_API_KEY')
        credentials.reset_mock()
        self.assertTrue(callable(builtin_target('file', {'path': 'example.csv'}, credentials).publish))
        credentials.get.assert_not_called()
        with self.assertRaises(GeofeedError): builtin_source('unknown', {}, credentials)
        with self.assertRaises(GeofeedError): builtin_target('file', {'unknown': 'value'}, credentials)

    def test_external_installed_extension_and_config_survive_a_core_update(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp); checkout = directory/'checkout'; installed = directory/'separate-site-packages'; private = directory/'operator-config'
            checkout.mkdir(); installed.mkdir(); private.mkdir()
            shutil.copytree(root/'isp_geofeed_generator', checkout/'isp_geofeed_generator', ignore=shutil.ignore_patterns('__pycache__'))
            shutil.copytree(root/'examples/local-extension/geofeed_local', installed/'geofeed_local')
            metadata = installed/'geofeed_local_example-0.1.0.dist-info'; metadata.mkdir()
            (metadata/'METADATA').write_text('Metadata-Version: 2.1\nName: geofeed-local-example\nVersion: 0.1.0\n')
            (metadata/'entry_points.txt').write_text('[isp_geofeed_generator.sources.v1]\nlocal_json = geofeed_local:SOURCE\n[isp_geofeed_generator.targets.v1]\nlocal_file = geofeed_local:TARGET\n')
            inventory = private/'inventory.json'; inventory.write_text(json.dumps(snapshot()))
            cfg = private/'config.yaml'; target = private/'feed.csv'
            base = ('extensions: {sources: [local_json], targets: [local_file]}\n'
                    f'source: {{type: local_json, input_path: {inventory.as_posix()}, allow_initial: SOURCE_OPT_IN}}\n'
                    f'publish: {{type: local_file, path: {target.as_posix()}, allow_initial: TARGET_OPT_IN}}\n'
                    f'state_dir: {private.as_posix()}/state\nallowed_prefixes: [11.22.33.0/24]\npool_sites: {{"101": "11"}}\n')
            environment = {**os.environ, 'PYTHONPATH': str(installed), 'PYTHONDONTWRITEBYTECODE': '1'}
            command = [sys.executable, '-m', 'isp_geofeed_generator', 'publish', '--config', str(cfg)]
            # Both source and target extensions start as initial support.
            for source_opt_in, target_opt_in, expected in (('false', 'true', 'Initial adapter'), ('true', 'false', 'Initial output adapter')):
                cfg.write_text(base.replace('SOURCE_OPT_IN', source_opt_in).replace('TARGET_OPT_IN', target_opt_in))
                result = subprocess.run(command, cwd=checkout, env=environment, capture_output=True, text=True)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(expected, result.stderr)
                self.assertFalse(target.exists())
            cfg.write_text(base.replace('SOURCE_OPT_IN', 'true').replace('TARGET_OPT_IN', 'true'))
            preserved = [cfg, inventory, installed/'geofeed_local/__init__.py', metadata/'entry_points.txt']
            before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in preserved}
            first = subprocess.run(command, cwd=checkout, env=environment, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertTrue(json.loads(first.stdout)['changed'])
            feed = target.read_bytes()
            # Replace the runtime with the next core build in a separate checkout.
            shutil.copytree(root/'isp_geofeed_generator', checkout/'isp_geofeed_generator', dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__'))
            (checkout/'isp_geofeed_generator/__init__.py').write_text('__version__ = "0.2.0+upgrade-test"\n')
            second = subprocess.run(command, cwd=checkout, env=environment, capture_output=True, text=True)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertFalse(json.loads(second.stdout)['changed'])
            self.assertEqual(target.read_bytes(), feed)
            self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in preserved})
