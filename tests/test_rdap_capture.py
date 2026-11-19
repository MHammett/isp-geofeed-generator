import contextlib
from datetime import datetime, timezone
from email.message import Message
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import ssl
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, HTTPSHandler

from isp_geofeed_generator import rdap_capture as module
from isp_geofeed_generator._capture_directory import create_directory, write_new
from isp_geofeed_generator.cli import main
from isp_geofeed_generator.client import GeofeedError
from isp_geofeed_generator.credentials import CredentialStore
from isp_geofeed_generator.registry_rdap import normalize_rdap

ARIN = 'https://rdap.arin.net/registry/'
PREFIXES = ('11.22.33.0/24', '2001:4860:1234::/126')


def bootstrap(prefix=PREFIXES[0]):
    return json.dumps({'version':'1.0','publication':'2026-01-01T00:00:00Z',
                       'services':[[[prefix],[ARIN]]]}).encode()


def reply(prefix=PREFIXES[0]):
    import ipaddress
    net = ipaddress.ip_network(prefix)
    return {'objectClassName':'ip network','handle':'PRIVATE HANDLE',
            'startAddress':str(net.network_address),'endAddress':str(net.broadcast_address),
            'ipVersion':'v'+str(net.version), 'name':'PRIVATE NAME',
            'entities':[{'vcardArray':['vcard',[['fn',{},'text','PRIVATE CONTACT']]]}],
            'rdapConformance':['rdap_level_0'], 'links':[{'rel':'geofeed',
                'value':'https://rdap.example/ip/object','href':'https://feed.example/geofeed.csv'}]}


class Response:
    def __init__(self, data, *, status=200, media='application/rdap+json', encoding=None, length=None, failure=None):
        self.data = io.BytesIO(data); self.status = status; self.failure = failure; self.closed = False
        self.headers = Message(); self.headers['Content-Type'] = media
        if encoding is not None: self.headers['Content-Encoding'] = encoding
        self.headers['Content-Length'] = str(len(data)) if length is None else length
    def getcode(self): return self.status
    def read1(self, count):
        if self.failure: raise self.failure
        return self.data.read(count)
    def close(self): self.closed = True


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.source = self.root/'bootstrap.json'
        self.source.write_bytes(bootstrap()); self.dest = self.root/'capture'
        self.observed = datetime.now(timezone.utc).isoformat()
        self.private = self.root/'status.json'; self.private.write_bytes(b'PRIVATE failed status')
        self.before = (self.private.read_bytes(), self.private.stat().st_mtime_ns)

    def capture(self, response=None, prefix=PREFIXES[0], **kwargs):
        response = response or Response(json.dumps(reply(prefix)).encode())
        transport = Mock(); transport.open.return_value = response
        with patch.object(module, 'opener', return_value=transport):
            result = module.capture(self.source, prefix, self.observed, self.dest, **kwargs)
        self.assertEqual(transport.open.call_count, 1)
        return result, transport, response

    def test_dual_family_originals_dates_and_receipt_exist_before_parser(self):
        for index, prefix in enumerate(PREFIXES):
            self.dest = self.root/('capture'+str(index)); self.source.write_bytes(bootstrap(prefix))
            data = json.dumps(reply(prefix), indent=2).encode()
            def validate(raw, observed, **kwargs):
                self.assertTrue((self.dest/'receipt.json').is_file())
                self.assertEqual((self.dest/'response.body').read_bytes(), data)
                receipt = json.loads((self.dest/'receipt.json').read_bytes())
                self.assertEqual(receipt['validation'], 'not_measured')
                self.assertEqual(receipt['response_observed_at'], observed)
                self.assertEqual(receipt['saved_sha256'], hashlib.sha256(data).hexdigest())
                self.assertEqual((self.dest/'bootstrap.json').read_bytes(), self.source.read_bytes())
                self.assertTrue((self.dest/'request.json').is_file())
                self.assertFalse((self.dest/'validation.json').exists())
                return normalize_rdap(raw, observed, **kwargs)
            with patch.object(module, 'normalize_rdap', side_effect=validate):
                result, transport, response = self.capture(Response(data), prefix)
            request = transport.open.call_args.args[0]
            self.assertEqual(request.full_url, ARIN+'ip/'+prefix)
            self.assertEqual(request.get_method(), 'GET')
            self.assertEqual(request.get_header('Accept'), 'application/rdap+json')
            self.assertEqual(set(k.lower() for k in request.headers), {'accept','accept-encoding','connection','user-agent'})
            self.assertEqual(transport.open.call_args.kwargs, {'timeout':20})
            self.assertTrue(response.closed)
            self.assertEqual(result['response_sha256'], hashlib.sha256(data).hexdigest())
            self.assertEqual(result['rdap_validation'], 'accepted')
            self.assertEqual(result['registry_source'], 'captured_rdap')
            self.assertNotIn('PRIVATE', json.dumps(result)); self.assertNotIn('healthy', result)
            self.assertEqual(result['provider_ingestion'], 'not_measured')
        self.assertEqual((self.private.read_bytes(),self.private.stat().st_mtime_ns),self.before)

    def test_existing_directory_file_or_symlink_prevents_any_request(self):
        for kind in ('directory','file','symlink'):
            destination = self.root/kind
            if kind == 'directory': destination.mkdir(); (destination/'sentinel').write_bytes(b'PRIVATE')
            elif kind == 'file': destination.write_bytes(b'PRIVATE')
            else:
                try: destination.symlink_to(self.private)
                except OSError: continue
            with patch.object(module,'opener') as transport, self.assertRaisesRegex(GeofeedError,'never overwritten'):
                module.capture(self.source,PREFIXES[0],self.observed,destination)
            transport.assert_not_called()
        self.assertEqual(self.private.read_bytes(),self.before[0])

    def test_bad_bootstrap_prefix_language_or_destination_stops_before_network(self):
        for prefix, date, language in (('10.0.0.0/24',self.observed,None),
                                     ('11.22.33.1/24',self.observed,None),
                                     (PREFIXES[0],'2099-01-01T00:00:00Z',None),
                                     (PREFIXES[0],self.observed,'PRIVATE/../')):
            with patch.object(module,'opener') as transport, self.assertRaises(GeofeedError):
                module.capture(self.source,prefix,date,self.dest,rdap_language=language)
            transport.assert_not_called(); self.assertFalse(self.dest.exists())
        self.source.write_bytes(bootstrap().replace(ARIN.encode(),b'https://foreign.example/'))
        with patch.object(module,'opener') as transport, self.assertRaises(GeofeedError):
            module.capture(self.source,PREFIXES[0],self.observed,self.dest)
        transport.assert_not_called()

    def test_http_denials_referrals_and_rate_limits_are_saved_without_retry(self):
        for code in (301,302,307,308,401,403,404,429,500):
            self.dest = self.root/str(code)
            body = b'PRIVATE ERROR BODY'
            transport = Mock(); transport.open.return_value = Response(body,status=code)
            with patch.object(module,'opener',return_value=transport), self.assertRaisesRegex(GeofeedError,'http_status_refused') as error:
                module.capture(self.source,PREFIXES[0],self.observed,self.dest)
            self.assertEqual(transport.open.call_count,1)
            self.assertEqual((self.dest/'response.body').read_bytes(),body)
            receipt = json.loads((self.dest/'receipt.json').read_bytes())
            self.assertEqual(receipt['http_status'],code)
            self.assertNotIn('PRIVATE',str(error.exception))

    def test_timeout_and_partial_read_keep_attempt_evidence_with_no_retry(self):
        for index, failure in enumerate((URLError('PRIVATE timeout'), TimeoutError('PRIVATE'),
                                        OSError('PRIVATE'))):
            self.dest = self.root/('timeout'+str(index)); transport = Mock(); transport.open.side_effect = failure
            with patch.object(module,'opener',return_value=transport), self.assertRaises(GeofeedError) as error:
                module.capture(self.source,PREFIXES[0],self.observed,self.dest)
            self.assertEqual(transport.open.call_count,1)
            receipt = json.loads((self.dest/'receipt.json').read_bytes())
            self.assertIsNone(receipt['response_observed_at']); self.assertFalse(receipt['body_complete'])
            self.assertTrue((self.dest/'response.partial').exists()); self.assertNotIn('PRIVATE',str(error.exception))
        import http.client
        self.dest = self.root/'incomplete'
        with self.assertRaises(GeofeedError): self.capture(Response(b'',failure=http.client.IncompleteRead(b'PRIVATE partial',100)))
        self.assertEqual((self.dest/'response.partial').read_bytes(),b'PRIVATE partial')

    def test_valid_json_never_overrides_failed_http_status(self):
        for code in (302,403,429):
            self.dest=self.root/('valid-http'+str(code))
            with self.assertRaisesRegex(GeofeedError,'http_status_refused'):
                self.capture(Response(json.dumps(reply()).encode(),status=code))

    def test_http_error_exception_body_is_preserved_as_one_refused_response(self):
        body=b'PRIVATE redirect body';headers=Message();headers['Content-Length']=str(len(body))
        headers['Content-Type']='application/rdap+json';headers['Location']='https://foreign.example/PRIVATE'
        transport=Mock();transport.open.side_effect=HTTPError(ARIN,302,'PRIVATE',headers,io.BytesIO(body))
        with patch.object(module,'opener',return_value=transport),self.assertRaisesRegex(GeofeedError,'http_status_refused'):
            module.capture(self.source,PREFIXES[0],self.observed,self.dest)
        self.assertEqual(transport.open.call_count,1)
        self.assertEqual((self.dest/'response.body').read_bytes(),body)
        self.assertNotIn('foreign', (self.dest/'receipt.json').read_text())

    def test_media_encoding_lengths_and_body_budget_refuse_before_parser(self):
        for index, kwargs in enumerate(({'media':'text/html'}, {'encoding':'gzip'}, {'length':'99999'},
                                        {'length':'-1'}, {'length':'1'*100}, {'length':'\u0661'})):
            self.dest = self.root/('bad'+str(index))
            with patch.object(module,'normalize_rdap') as parser, self.assertRaises(GeofeedError):
                self.capture(Response(b'PRIVATE body',**kwargs))
            parser.assert_not_called()
        self.dest = self.root/'oversize'
        with patch.object(module,'MAX_BYTES',32), self.assertRaises(GeofeedError): self.capture(Response(b'x'*100))
        self.assertEqual((self.dest/'response.partial').read_bytes(),b'x'*32)
        self.assertFalse(json.loads((self.dest/'receipt.json').read_bytes())['body_complete'])
        self.dest = self.root/'time-budget'
        with patch.object(module.time,'monotonic',side_effect=[0,31,31]), self.assertRaises(GeofeedError): self.capture()
        self.assertEqual(json.loads((self.dest/'receipt.json').read_bytes())['read_error'],'read_budget')

    def test_invalid_truncated_redacted_and_wrong_scope_replies_remain_preserved(self):
        rows = [b'PRIVATE not JSON', b'{"objectClassName":"ip network","objectClassName":"ip network"}',
                json.dumps({**reply(),'remarks':[{'type':'object truncated due to server policy'}]}).encode(),
                json.dumps(reply('11.22.33.0/25')).encode(), json.dumps(reply(PREFIXES[1])).encode(),
                json.dumps({**reply(),'errorCode':404}).encode(),
                json.dumps({**reply(),'redacted':[{'prePath':'$.links','method':'removal'}]}).encode()]
        for index, data in enumerate(rows):
            self.dest = self.root/('invalid'+str(index))
            with self.assertRaises(GeofeedError): self.capture(Response(data))
            self.assertEqual((self.dest/'response.body').read_bytes(),data)
            self.assertEqual(json.loads((self.dest/'validation.json').read_bytes())['validation'],'refused')

    def test_declared_language_is_explicit_and_all_unselected_links_are_checked(self):
        row = reply(); base = row['links'][0]
        row['links'] = [{**base,'hreflang':'en'}, {**base,'hreflang':'fr','href':'https://other.example/feed.csv'}]
        data = json.dumps(row).encode()
        with self.assertRaises(GeofeedError): self.capture(Response(data))
        self.dest = self.root/'explicit'
        result,_,_ = self.capture(Response(data),rdap_language='en')
        self.assertEqual(result['rdap_link_selection'],'exact_language')
        self.dest = self.root/'unsafe'
        row['links'][1]['href']='http://user:PRIVATE@other.example/feed.csv'
        with self.assertRaises(GeofeedError): self.capture(Response(json.dumps(row).encode()),rdap_language='en')

    def test_real_redirect_is_blocked_and_unsafe_control_reaches_target(self):
        counts = {'entry':0,'target':0}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_GET(self):
                if self.path == '/entry':
                    counts['entry']+=1; self.send_response(302); self.send_header('Location','/target'); self.end_headers()
                else:
                    counts['target']+=1; self.send_response(200); self.end_headers(); self.wfile.write(b'control')
        server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            url = 'http://127.0.0.1:'+str(server.server_port)+'/entry'
            with self.assertRaises(HTTPError) as error: module.opener().open(url,timeout=3)
            error.exception.close(); self.assertEqual(counts,{'entry':1,'target':0})
            with patch.object(module,'NoRedirects',HTTPRedirectHandler):
                with module.opener().open(url,timeout=3) as response: self.assertEqual(response.read(),b'control')
            self.assertEqual(counts,{'entry':2,'target':1})
        finally: server.shutdown(); server.server_close(); thread.join(timeout=3)
        print('RDAP CAPTURE REDIRECT OBSERVATION: '+json.dumps({'blocked_requests':1,'blocked_target_hits':0,'unsafe_target_hits':1}))

    def test_default_transport_has_tls_verification_no_proxy_auth_or_cookies(self):
        with patch.dict(os.environ,{'HTTPS_PROXY':'http://user:PRIVATE@127.0.0.1:9','HTTP_PROXY':'http://127.0.0.1:9'}):
            transport = module.opener()
        for handler in transport.handlers:
            self.assertNotIn('Cookie',type(handler).__name__); self.assertNotIn('Auth',type(handler).__name__)
            if isinstance(handler,ProxyHandler): self.assertEqual(handler.proxies,{})
            if isinstance(handler,HTTPSHandler):
                self.assertEqual(handler._context.verify_mode,ssl.CERT_REQUIRED); self.assertTrue(handler._context.check_hostname)

    def test_storage_failure_does_not_retry_network_or_replace_existing_files(self):
        original = module.write_new; transport = Mock(); transport.open.return_value=Response(json.dumps(reply()).encode())
        def fail(path,data):
            if path.name=='receipt.json': raise OSError('PRIVATE storage error')
            return original(path,data)
        with patch.object(module,'opener',return_value=transport), patch.object(module,'write_new',side_effect=fail), self.assertRaisesRegex(GeofeedError,'storage failed'):
            module.capture(self.source,PREFIXES[0],self.observed,self.dest)
        self.assertEqual(transport.open.call_count,1); self.assertTrue((self.dest/'response.body').exists())
        with self.assertRaises(GeofeedError): self.capture()
        sentinel=self.root/'sentinel';sentinel.write_bytes(b'PRIVATE')
        with self.assertRaises(FileExistsError): write_new(sentinel,b'overwritten')
        self.assertEqual(sentinel.read_bytes(),b'PRIVATE')

    def test_cli_is_separate_from_config_credentials_publication_and_other_flags(self):
        args=['capture-rdap','--config',str(self.root/'missing.yaml'),'--bootstrap-records',str(self.source),
              '--bootstrap-observed-at',self.observed,'--rdap-prefix',PREFIXES[0],'--rdap-capture-dir',str(self.dest)]
        output,error=io.StringIO(),io.StringIO(); transport=Mock();transport.open.return_value=Response(json.dumps(reply()).encode())
        with patch.object(module,'opener',return_value=transport), \
                patch('isp_geofeed_generator.cli.load_config',side_effect=AssertionError('config read')), \
                patch.object(CredentialStore,'get',side_effect=AssertionError('credential read')), \
                patch('isp_geofeed_generator.cli.atomic_write',side_effect=AssertionError('publication write')), \
                contextlib.redirect_stdout(output),contextlib.redirect_stderr(error):
            self.assertEqual(main(args),0)
            self.assertEqual(main(args),1)  # Existing folder cannot repeat the request.
        self.assertEqual(transport.open.call_count,1)
        self.assertTrue(json.loads(output.getvalue())['capture_only']); self.assertNotIn('PRIVATE',output.getvalue()+error.getvalue())
        self.assertEqual((self.private.read_bytes(),self.private.stat().st_mtime_ns),self.before)
        for command in ('publish','check-registry','plan-rdap','generate'):
            with patch.object(module,'opener') as transport, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main([command,'--rdap-capture-dir',str(self.dest)]),1)
            transport.assert_not_called()
        for flag,value in (('--output','PRIVATE'),('--feed','PRIVATE'),('--reference-policy','longest_prefix')):
            with patch.object(module,'opener') as transport, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(args+[flag,value]),1)
            transport.assert_not_called()

    def test_native_directory_and_file_permissions_with_unsafe_control(self):
        import stat
        directory=create_directory(self.dest);file=directory/'payload';write_new(file,b'PRIVATE')
        def verify(path, is_directory):
            if os.name=='posix':
                self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o700 if is_directory else 0o600)
                self.assertEqual(path.stat().st_uid,os.geteuid())
            else:
                import ctypes as c
                from ctypes import wintypes as w
                api=c.WinDLL('advapi32',use_last_error=True);kernel=c.WinDLL('kernel32',use_last_error=True)
                api.GetNamedSecurityInfoW.argtypes=[w.LPCWSTR,c.c_int,w.DWORD,c.c_void_p,c.c_void_p,c.c_void_p,c.c_void_p,c.POINTER(c.c_void_p)]
                api.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes=[c.c_void_p,w.DWORD,w.DWORD,c.POINTER(c.c_void_p),c.c_void_p]
                kernel.LocalFree.argtypes=[c.c_void_p]
                descriptor,text=c.c_void_p(),c.c_void_p()
                try:
                    self.assertEqual(api.GetNamedSecurityInfoW(str(path),1,4,None,None,None,None,c.byref(descriptor)),0)
                    self.assertTrue(api.ConvertSecurityDescriptorToStringSecurityDescriptorW(descriptor,1,4,c.byref(text),None))
                    value=c.wstring_at(text)
                    if is_directory:self.assertTrue(value.startswith('D:P'))
                    import re
                    entries=[ace.split(';') for ace in re.findall(r'\(([^)]+)\)',value)]
                    self.assertEqual(len(entries),2)
                    self.assertTrue(all(ace[0]=='A' and ace[2]=='FA' for ace in entries))
                    trustees={ace[5] for ace in entries}
                    self.assertIn('SY',trustees)
                    import csv,subprocess
                    account=list(csv.reader(subprocess.check_output([str(Path(os.environ['SystemRoot'])/'System32/whoami.exe'),
                        '/user','/fo','csv','/nh']).decode(errors='replace').splitlines()))
                    self.assertEqual(len(account),1);self.assertEqual(len(account[0]),2)
                    user=account[0][1]
                    self.assertTrue(user.startswith('S-1-'))
                    self.assertTrue(trustees=={'SY', 'SY' if user=='S-1-5-18' else user},
                                    'DACL trustees must be current user and SYSTEM only')
                finally:
                    if text:kernel.LocalFree(text)
                    if descriptor:kernel.LocalFree(descriptor)
        verify(directory,True);verify(file,False)
        unsafe=self.root/'unsafe';unsafe.mkdir()
        if os.name=='posix':unsafe.chmod(0o755)
        with self.assertRaises(AssertionError):verify(unsafe,True)
        self.assertEqual(file.read_bytes(),b'PRIVATE')
        print('RDAP CAPTURE PERMISSION OBSERVATION: '+json.dumps({'platform':os.name,
            'restricted_directory':True,'restricted_file':True,'unsafe_control_refused':True}))

    def test_private_guard_removals_fail_assertions_with_intact_controls(self):
        text=Path(module.__file__).read_text()
        controls=[('http-status',"elif receipt['http_status'] != 200:",'elif False:',
                   'test_valid_json_never_overrides_failed_http_status'),
                  ('whole-prefix',"if (requested.version != start.version or int(requested.network_address) < int(start)\n                    or int(requested.broadcast_address) > int(end)):",'if False:',
                   'test_invalid_truncated_redacted_and_wrong_scope_replies_remain_preserved'),
                  ('preserve-before-parse',"    save('receipt.json', receipt)","    # Receipt intentionally omitted in this private control.",
                   'test_dual_family_originals_dates_and_receipt_exist_before_parser')]
        def run(method):
            result=unittest.TestResult();CaptureTests(method).run(result);return result
        positive='test_dual_family_originals_dates_and_receipt_exist_before_parser'
        for name,find,replacement,method in controls:
            self.assertTrue(run(positive).wasSuccessful());self.assertTrue(run(method).wasSuccessful())
            self.assertEqual(text.count(find),1)
            private=types.ModuleType('isp_geofeed_generator._private_capture_control');private.__package__='isp_geofeed_generator'
            exec(compile(text.replace(find,replacement),'<private capture control>','exec'),private.__dict__)
            private.opener=lambda:module.opener()
            if name=='preserve-before-parse':private.normalize_rdap=lambda *a,**kw:module.normalize_rdap(*a,**kw)
            with patch.object(module,'capture',private.capture):result=run(method)
            self.assertEqual(result.errors,[]);self.assertGreater(len(result.failures),0)
            self.assertTrue(run(positive).wasSuccessful());self.assertTrue(run(method).wasSuccessful())
            print('RDAP CAPTURE MUTATION OBSERVATION: '+json.dumps({'mutation':name,
                'assertion_failures':len(result.failures),'errors':0,'intact_before_after':True}))
