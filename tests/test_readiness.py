"""Proxy-safe pagination, preflight failures and narrowly scoped systemd ACLs."""
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from isp_geofeed_generator.client import GeofeedError
from isp_geofeed_generator.netbox import NetBox
from isp_geofeed_generator.publish import WordPress, publish_wordpress
from isp_geofeed_generator.credentials import CredentialStore
from test_sources import HTTP, page
from test_publish import OLD


def acl(uid=1001):
    # Linux POSIX ACL xattr ABI: read-only owner + one service UID; no group/other.
    return struct.pack('<I', 2)+b''.join(struct.pack('<HHI', *entry) for entry in
        [(1,4,0xffffffff),(2,4,uid),(4,0,0xffffffff),(16,4,0xffffffff),(32,0,0xffffffff)])


class ReadinessTests(unittest.TestCase):
    def test_proxy_next_host_is_ignored_and_requests_stay_on_configured_origin(self):
        http=HTTP([page([{'id':1}],2,'http://internal.invalid/unrelated/?offset=999'),page([{'id':2}],2)])
        source=NetBox('https://configured.example.net','fake-token',http=http)
        self.assertEqual(len(source.pages('/ipam/prefixes/')),2)
        self.assertEqual([c[0] for c in http.calls],['https://configured.example.net/api/ipam/prefixes/?limit=100&offset=0',
                                                     'https://configured.example.net/api/ipam/prefixes/?limit=100&offset=1'])
        self.assertTrue(all(c[1]['headers']['Authorization']=='Token fake-token' for c in http.calls))

    def test_next_metadata_and_incomplete_pages_still_fail(self):
        for following in (True, [], {}, '', 7):
            with self.assertRaises(GeofeedError):
                NetBox('https://example.net','token',http=HTTP([page([{'id':1}],1,following)])).pages('/ipam/prefixes/')
        with self.assertRaises(GeofeedError):
            NetBox('https://example.net','token',http=HTTP([page([],2,'https://internal.invalid/')])).pages('/ipam/prefixes/')

    def test_state_refusal_explains_https_proxy_auth_and_performs_no_write(self):
        for status in (401,403):
            class Denied:
                def __init__(self): self.calls=[]
                def request(self,url,**kwargs):
                    self.calls.append((url,kwargs));raise GeofeedError(f'HTTP {status}; private upstream body')
            http=Denied();publisher=WordPress('https://site.example.net','user','fake-password',http=http)
            with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(GeofeedError,'HTTPS') as caught:
                publish_wordpress(publisher,OLD,tmp)
                self.fail('Denied preflight must not publish')
            self.assertNotIn('private',str(caught.exception));self.assertIn('permissions',str(caught.exception))
            self.assertEqual(len(http.calls),1);self.assertTrue(http.calls[0][0].endswith('/state'))
            self.assertNotIn('body',http.calls[0][1])

    def test_systemd_only_uses_acl_aware_file_path(self):
        store=CredentialStore({'SONAR_API_TOKEN':'systemd:SONAR_API_TOKEN'},environ={'CREDENTIALS_DIRECTORY':'/private'})
        with patch('isp_geofeed_generator.credentials.protected_file',return_value='synthetic-token') as reader:
            self.assertEqual(store.get('SONAR_API_TOKEN'),'synthetic-token')
            self.assertEqual(reader.call_args.kwargs,{'systemd':True})

    def test_state_diagnostic_can_also_be_used_during_recovery(self):
        class Denied:
            def request(self,*args,**kwargs):raise GeofeedError('HTTP 403; private body')
        wp=WordPress('https://site.example.net','user','fake-password',http=Denied())
        with self.assertRaisesRegex(GeofeedError,'HTTPS') as caught:wp.state()
        self.assertNotIn('no write',str(caught.exception))
        self.assertNotIn('private',str(caught.exception))

    def test_only_exact_readonly_service_acl_is_accepted(self):
        from isp_geofeed_generator.credentials import systemd_read_acl
        with patch('os.getxattr',return_value=acl(),create=True):self.assertTrue(systemd_read_acl(42,1001))
        for value in (b'',acl(1002),acl()+b'x',struct.pack('<I',1)+acl()[4:],
                      acl()[:20]+struct.pack('<HHI',4,4,0xffffffff)+acl()[28:],
                      acl()+struct.pack('<HHI',2,4,1002),
                      acl()[:-8]+struct.pack('<HHI',32,4,0xffffffff),
                      acl()[:12]+struct.pack('<HHI',2,6,1001)+acl()[20:]):
            with patch('os.getxattr',return_value=value,create=True):self.assertFalse(systemd_read_acl(42,1001))
        with patch('os.getxattr',side_effect=OSError('unsupported'),create=True):self.assertFalse(systemd_read_acl(42,1001))
