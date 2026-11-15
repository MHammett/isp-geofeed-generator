import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from isp_geofeed_generator.client import GeofeedError
from isp_geofeed_generator.credentials import CredentialStore, protected_file


class CredentialsTests(unittest.TestCase):
    def test_literal_secrets_in_config_are_rejected_without_echo(self):
        with self.assertRaises(GeofeedError) as error:CredentialStore({'SONAR_API_TOKEN':'private-value'})
        self.assertNotIn('private-value',str(error.exception))

    def test_resolved_credentials_are_redacted(self):
        store=CredentialStore(environ={'SONAR_API_TOKEN':'private-token'})
        self.assertEqual(store.get('SONAR_API_TOKEN'),'private-token')
        self.assertEqual(store.redact('failure private-token'),'failure [REDACTED]')

    def test_systemd_selection_does_not_fall_back_to_environment(self):
        store=CredentialStore(environ={'CREDENTIALS_DIRECTORY':'/missing','SONAR_API_TOKEN':'environment-token'})
        with patch('isp_geofeed_generator.credentials.protected_file',side_effect=GeofeedError('missing')):
            with self.assertRaisesRegex(GeofeedError,'missing'):store.get('SONAR_API_TOKEN')

    def test_windows_store_reference_contains_only_target_name(self):
        store=CredentialStore({'NETBOX_API_TOKEN':'wincred:example-target'},environ={})
        with patch('isp_geofeed_generator.credentials.windows_credential',return_value='example-token') as reader:
            self.assertEqual(store.get('NETBOX_API_TOKEN'),'example-token');reader.assert_called_once_with('example-target')

    def test_reject_empty_and_multiline_secret(self):
        for value in ('','first\nsecond','nul\x00data'):
            with self.assertRaises(GeofeedError):CredentialStore(environ={'SONAR_API_TOKEN':value}).get('SONAR_API_TOKEN')

    @unittest.skipUnless(os.name=='posix','POSIX ownership and mode check; Windows uses Credential Manager')
    def test_file_permissions_symlinks_and_size_are_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'credential';path.write_text('example-token\n');path.chmod(0o600)
            self.assertEqual(protected_file(path),'example-token')
            path.chmod(0o644)
            with self.assertRaisesRegex(GeofeedError,'permissions'):protected_file(path)
            path.chmod(0o600);link=Path(tmp)/'link';link.symlink_to(path)
            with self.assertRaises(GeofeedError):protected_file(link)
            path.write_bytes(b'x'*16385)
            with self.assertRaisesRegex(GeofeedError,'size'):protected_file(path)
