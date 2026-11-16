"""Wire-format migration and bounded large-feed transport workloads."""
import io
import contextlib
import ipaddress
import json
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch

from isp_geofeed_generator.client import GeofeedError, JsonHTTP
from isp_geofeed_generator.feed import build, change_guard, digest, parse_feed
from isp_geofeed_generator.publish import WordPress, publish_file, publish_wordpress
from test_feed import config, snapshot
from test_publish import FakeWP, OLD
from bogon_fixture import policy


class Response(io.BytesIO):
    def __init__(self, data, content_type='application/json'):
        super().__init__(data)
        self.headers=Message();self.headers['Content-Type']=content_type


def large_unicode_feed():
    city='é'*100
    start=int(ipaddress.IPv4Address('11.0.0.0'))
    return ''.join(f'{ipaddress.IPv4Address(start+i*256)}/24,US,US-IL,{city},\r\n'
                   for i in range(4000)).encode()


class CompatibilityTests(unittest.TestCase):
    def test_generate_stdout_preserves_utf8_and_crlf_under_windows_text_translation(self):
        from isp_geofeed_generator.cli import main
        fixture=snapshot();fixture['sites'][0]['addresses'][0]['city']='Example é'
        expected=build(fixture,config())[0]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cfg=root/'config.yaml'
            cfg.write_text(f'source: {{type: sonar}}\nstate_dir: {root.as_posix()}/state\nallowed_prefixes: [11.22.33.0/24]\npool_sites: {{"101": "11"}}\n')
            raw=io.BytesIO();stream=io.TextIOWrapper(raw,encoding='ascii',newline='\r\n')
            errors=io.StringIO()
            with patch.dict('os.environ',{'SONAR_API_TOKEN':'synthetic-token'}), \
                 patch('isp_geofeed_generator.adapters.Sonar') as sonar, \
                 patch('isp_geofeed_generator.cli.load_policy',side_effect=lambda c:policy()), \
                 contextlib.redirect_stdout(stream),contextlib.redirect_stderr(errors):
                sonar.return_value.snapshot.return_value=fixture
                sonar.return_value.for_publication.side_effect=lambda value:value
                self.assertEqual(main(['generate','--config',str(cfg)]),0,errors.getvalue())
            stream.flush()
            self.assertEqual(raw.getvalue(),expected)
            self.assertIn(digest(raw.getvalue()),errors.getvalue())
            stream.close()

    def test_generated_csv_uses_only_crlf_row_endings(self):
        data,_=build(snapshot(),config())
        self.assertIn(b'\r\n',data)
        self.assertNotIn(b'\n',data.replace(b'\r\n',b''))
        self.assertTrue(parse_feed(data))

    def test_legacy_lf_and_crlf_compare_without_a_location_or_withdrawal_change(self):
        current=OLD.replace(b'\n',b'\r\n')
        self.assertEqual(parse_feed(OLD),parse_feed(current))
        change_guard(OLD,current,max_removed_fraction=0,max_relocated_fraction=0)
        with self.assertRaisesRegex(GeofeedError,'location'):
            change_guard(OLD,current.replace(b'Old City',b'Other City'))

    def test_mixed_bare_cr_and_embedded_control_endings_are_refused(self):
        second=b'11.22.34.0/24,US,US-IL,City,\n'
        for bad in (OLD.replace(b'\n',b'\r\n')+second,OLD.replace(b'\n',b'\r'),
                    OLD.replace(b'Old City',b'Old\rCity'),OLD.replace(b'\n',b'\r\r\n'),
                    OLD.replace(b'\n',b'\r\n')+b'\r\n'):
            with self.subTest(data=bad),self.assertRaises(GeofeedError):parse_feed(bad)

    def test_local_line_ending_migration_writes_once_and_keeps_exact_lf_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target=root/'feed.csv';target.write_bytes(OLD)
            current=OLD.replace(b'\n',b'\r\n')
            self.assertTrue(publish_file(target,current,root)['changed'])
            stamp=target.stat().st_mtime_ns;backup=(root/'before.csv').read_bytes()
            self.assertEqual(backup,OLD)
            self.assertFalse(publish_file(target,current,root)['changed'])
            self.assertEqual(target.stat().st_mtime_ns,stamp)
            self.assertEqual((root/'before.csv').read_bytes(),backup)

    def test_wordpress_line_ending_migration_keeps_exact_hashes_and_becomes_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            wp=FakeWP();current=OLD.replace(b'\n',b'\r\n')
            self.assertTrue(publish_wordpress(wp,current,tmp)['changed'])
            self.assertEqual(wp.writes,[(current,OLD)])
            self.assertFalse(publish_wordpress(wp,current,tmp)['changed'])
            self.assertEqual(len(wp.writes),1)
            self.assertEqual((Path(tmp)/'before.csv').read_bytes(),OLD)

    def test_large_unicode_current_and_previous_feeds_fit_bounded_state_read(self):
        csv=large_unicode_feed()
        self.assertLess(len(csv),1_000_000)
        payload=json.dumps({'csv':csv.decode(),'previous_csv':csv.decode(),'sha256':digest(csv)}).encode()
        self.assertGreater(len(payload),4_000_000)
        self.assertGreater(len(json.dumps({'csv':csv.decode(),'expected_sha256':digest(OLD)}).encode()),1_048_576)
        class Opener:
            def open(self,*args,**kwargs):return Response(payload)
        wp=WordPress('https://site.example.net','user','synthetic-password')
        wp.http.opener=Opener()
        self.assertEqual(wp.state(),csv)

    def test_state_transport_still_refuses_oversized_responses(self):
        class Opener:
            def open(self,*args,**kwargs):return Response(b' '*8_000_001)
        wp=WordPress('https://site.example.net','user','synthetic-password')
        wp.http.opener=Opener()
        with self.assertRaisesRegex(GeofeedError,'size limit'):wp.state()

    def test_http_size_and_storage_failures_are_sanitized_inspected_and_not_retried(self):
        for code,clue in ((413,'request-body'),(503,'max_allowed_packet')):
            class Opener:
                def __init__(self):self.calls=[]
                def open(self,request,**kwargs):
                    self.calls.append(request)
                    if request.get_method()=='PUT':
                        raise HTTPError(request.full_url,code,'private upstream detail',{},io.BytesIO(b'private database body'))
                    if request.full_url.endswith('/state'):
                        return Response(json.dumps({'csv':OLD.decode(),'previous_csv':'','sha256':digest(OLD)}).encode())
                    return Response(OLD,'text/csv')
            opener=Opener();http=JsonHTTP();http.opener=opener
            wp=WordPress('https://site.example.net','user','synthetic-password',http=http)
            with tempfile.TemporaryDirectory() as tmp,self.assertRaises(GeofeedError) as caught:
                publish_wordpress(wp,OLD.replace(b'Old City',b'New City'),tmp,max_relocated_fraction=1)
            message=str(caught.exception)
            self.assertIn(clue,message);self.assertIn('retained/restored',message)
            self.assertNotIn('private',message);self.assertNotIn('synthetic-password',message)
            self.assertEqual(sum(r.get_method()=='PUT' for r in opener.calls),1)
            self.assertEqual([r.get_method() for r in opener.calls],['GET','GET','PUT','GET','GET'])
            for request in opener.calls:
                if request.full_url.endswith('/feed') and request.get_method()=='GET':
                    self.assertIsNone(request.get_header('Authorization'))

    def test_unrelated_write_failures_keep_their_existing_diagnostic(self):
        class HTTP:
            def request(self,*args,**kwargs):raise GeofeedError('HTTP 409; no retry was made')
        wp=WordPress('https://site.example.net','user','synthetic-password',http=HTTP())
        with self.assertRaisesRegex(GeofeedError,'^HTTP 409; no retry was made$'):wp.replace(OLD,b'')
