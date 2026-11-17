"""Real disposable WordPress/MariaDB/TLS workload. Never targets an existing site."""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import HTTPSHandler, build_opener, urlopen
from urllib.parse import parse_qs, urlsplit
import zipfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DISPOSABLE = (sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true'
              and os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted')
if __name__ == '__main__' and not DISPOSABLE:
    raise SystemExit('requires disposable GitHub-hosted Linux runner; not measured elsewhere')
sys.path.insert(0, str(ROOT / 'tests'))
from bogon_fixture import files as bogon_files
from isp_geofeed_generator.cli import main
from isp_geofeed_generator.feed import digest
from isp_geofeed_generator.client import GeofeedError, JsonHTTP, NoRedirects
from isp_geofeed_generator.publish import WordPress
from isp_geofeed_generator.feed import render_csv,csv_records
from isp_geofeed_generator.envelope import csv_body,wrap_csv
from isp_geofeed_generator.overlap import REJECT,LONGEST_PREFIX
import contextlib
import yaml

FEED = '/wp-json/isp-geofeed-generator/v1/feed'
STATE = '/wp-json/isp-geofeed-generator/v1/state'
FEED_V2 = '/wp-json/isp-geofeed-generator/v2/feed'
STATE_V2 = '/wp-json/isp-geofeed-generator/v2/state'
POLICY_V2 = '/wp-json/isp-geofeed-generator/v2/policy'
A = b'11.22.33.0/24,US,US-IL,Example City,\r\n2001:4860:1234::/126,US,US-IL,Example City,\r\n'
B = A.replace(b'2001:', b'11.22.34.0/24,US,US-IL,Example City,\r\n2001:', 1)
C = A.replace(b'2001:', b'11.22.35.0/24,US,US-IL,Example City,\r\n2001:', 1)


def check(condition, label):
    if not condition:
        raise AssertionError(label)


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def stage_core(directory):
    pin = json.loads((HERE / 'core.json').read_text())
    with urlopen(pin['url'], timeout=60) as response:
        archive = response.read(pin['max_archive_bytes'] + 1)
    check(len(archive) <= pin['max_archive_bytes'], 'core archive size')
    check(hashlib.sha256(archive).hexdigest() == pin['sha256'], 'core archive hash')
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        members = zipped.infolist()
        check(len(members) < 10000 and sum(m.file_size for m in members) <= pin['max_expanded_bytes'], 'expanded core budget')
        for member in members:
            name = PurePosixPath(member.filename)
            check(name.parts and name.parts[0] == 'wordpress' and '..' not in name.parts
                  and '\\' not in member.filename and not name.is_absolute()
                  and (member.external_attr >> 16) & 0o170000 != 0o120000, 'safe core archive member')
        zipped.extractall(directory)
    return directory / 'wordpress', pin['version']


class Proxy(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, backend, nonce, cert, key):
        super().__init__(('127.0.0.1', 0), Handler)
        self.backend, self.nonce = backend, nonce
        self.mode, self.lock, self.faults = None, threading.Lock(), []
        self.pending = False
        self.request_sizes = []
        self.publisher_headers = {}
        self.last_policy_commit = None
        self.nested_winner = None
        self.policy_admin_headers = {}
        self.control = None
        self.cached_feed = None
        self.after_oom = None
        self.before_restore = None
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        self.socket = context.wrap_socket(self.socket, server_side=True)

    def arm(self, mode):
        with self.lock:
            self.mode, self.pending, self.faults, self.request_sizes = mode, False, [], []

    def forward(self, method, path, body=b'', headers=None):
        headers = dict(headers or {})
        # Never trust a client's proxy marker, forwarding headers or hop headers.
        for name in list(headers):
            if name.lower() in {'x-geofeed-test-proxy', 'x-forwarded-proto', 'connection', 'transfer-encoding', 'content-length'}:
                del headers[name]
        headers['X-Geofeed-Test-Proxy'] = self.nonce
        headers['Content-Length'] = str(len(body))
        connection = http.client.HTTPConnection('127.0.0.1', self.backend, timeout=20)
        try:
            connection.request(method, path, body, headers)
            response = connection.getresponse()
            data = response.read(8_000_001)
            check(len(data) <= 8_000_000, 'proxy response budget')
            return response.status, dict(response.getheaders()), data
        finally:
            connection.close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self): self.handle_request()
    def do_PUT(self): self.handle_request()
    def do_DELETE(self): self.handle_request()

    def handle_request(self):
        proxy = self.server
        length = int(self.headers.get('Content-Length', '0'))
        if not 0 <= length <= 4_000_000:
            self.send_error(413); return
        body = self.rfile.read(length)
        with proxy.lock:
            observation={'method':self.command,'path':self.path,'bytes':length,
                         'authenticated':bool(self.headers.get('Authorization'))}
            proxy.request_sizes.append(observation)
            if self.command=='PUT' and self.path in (FEED,FEED_V2) and proxy.before_restore is not None:
                callback=proxy.before_restore;proxy.before_restore=None
                callback(self.path,json.loads(body))
            mode = proxy.mode
            if mode == 'failed-recovery' and proxy.pending and self.command in ('PUT', 'DELETE'):
                proxy.mode = None; proxy.faults.append('recovery-refused')
                self.send_error(503); return
        status, headers, data = proxy.forward(self.command, self.path, body, dict(self.headers))
        with proxy.lock:
            observation['origin_status']=status
            for name,value in headers.items():
                if name.lower()=='x-geofeed-test-max-packet' and len(value)<=10 and value.isdigit():
                    observation['session_packet_budget']=int(value)
                if name.lower()=='x-geofeed-test-memory-limit' and value in ('64M','256M'):
                    observation['php_memory_limit']=value
            if self.command=='PUT' and self.path in (FEED,FEED_V2) and status==503:
                try:
                    error=json.loads(data)
                except (ValueError,UnicodeError):
                    error=None
                if isinstance(error,dict) and error.get('code')=='geofeed_db':
                    observation['origin_error']='geofeed_db'  # Fixed code only, no raw server message.
            mode = proxy.mode
            if self.command=='PUT' and self.path in (FEED,FEED_V2) and status==500 and mode=='after-commit-oom':
                proxy.mode=None;mode=None
                check(callable(proxy.after_oom),'after-commit failure has an explicit inspection callback')
                proxy.after_oom(self.path,json.loads(body))
                proxy.faults.append('after-commit-oom-inspected')
            probe_path=self.path.startswith(FEED+'?isp_geofeed_probe=')
            if self.command=='GET' and self.path==FEED and mode=='purge-cache':
                marker=proxy.control/'purged.sha256'
                purged=marker.read_text() if marker.exists() else None
                actual=b'' if status==404 else data
                if purged!=digest(actual):
                    status=200;data=proxy.cached_feed;proxy.faults.append('purge-cache-stale')
                else:proxy.faults.append('purge-cache-refreshed')
            elif self.command=='GET' and (self.path==FEED or probe_path) and mode in (
                    'cache-canonical-stale','cache-both-stale','cache-canonical-unavailable'):
                if self.path==FEED:
                    data=C
                    if mode=='cache-canonical-unavailable':status=503
                    proxy.faults.append('cache-canonical-unavailable' if status==503 else 'cache-canonical-stale')
                elif mode=='cache-both-stale':
                    data=C;proxy.faults.append('cache-probe-stale')
            elif self.command == 'GET' and self.path == FEED and mode == 'preflight-mismatch':
                proxy.mode = None; proxy.faults.append('preflight-mismatch'); data = C
            elif self.command == 'PUT' and self.path in (FEED,FEED_V2) and status == 200 and mode:
                proxy.pending = True
                if self.path==FEED_V2:proxy.last_policy_commit=json.loads(body)
                if mode=='policy-winner':
                    previous=proxy.last_policy_commit
                    config={'protocol_version':2,'required_overlap_policy':REJECT,
                        'expected_sha256':digest(previous['csv'].encode()),'expected_overlap_policy':LONGEST_PREFIX,
                        'expected_required_overlap_policy':LONGEST_PREFIX,'expected_publication_id':previous['publication_id'],
                        'publication_id':secrets.token_hex(16)}
                    result=proxy.forward('PUT',POLICY_V2,json.dumps(config).encode(),{**proxy.policy_admin_headers,'Content-Type':'application/json'})
                    check(result[0]==200,'injected real administrative policy winner committed')
                    proxy.mode=None;proxy.faults.append('policy-winner-committed')
                if mode == 'lost-reply':
                    proxy.mode = None; proxy.faults.append('reply-dropped')
                    self.close_connection = True
                    return
            elif self.command == 'GET' and self.path == FEED and proxy.pending and mode in ('bad-readback', 'winner', 'failed-recovery'):
                if mode != 'failed-recovery': proxy.mode = None
                proxy.faults.append('public-mismatch')
                if mode == 'winner':
                    if proxy.nested_winner is not None:
                        previous=proxy.last_policy_commit
                        winner=json.dumps({**previous,'csv':proxy.nested_winner.decode(),'operation':'publish',
                            'expected_sha256':digest(previous['csv'].encode()),'expected_overlap_policy':LONGEST_PREFIX,
                            'expected_publication_id':previous['publication_id'],'publication_id':secrets.token_hex(16)}).encode()
                        endpoint=FEED_V2
                    else:
                        winner = json.dumps({'csv':C.decode(), 'expected_sha256':digest(B)}).encode();endpoint=FEED
                    result = proxy.forward('PUT', endpoint, winner, {**proxy.publisher_headers, 'Content-Type':'application/json'})
                    check(result[0] == 200, 'injected real concurrent writer committed')
                    proxy.faults.append('winner-committed')
                data = C
        self.send_response(status)
        for name, value in headers.items():
            if name.lower() not in {'content-length', 'transfer-encoding', 'connection', 'server', 'date'}:
                self.send_header(name, value)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class Workload:
    def __init__(self, directory):
        self.directory = directory
        self.control = directory / 'control'; self.control.mkdir(mode=0o700)
        self.webroot, self.version = stage_core(directory)
        self.backend = port()
        self.db = 'geofeed_wp_' + secrets.token_hex(6)
        self.user = 'gf_wp_' + secrets.token_hex(6)
        password, nonce = secrets.token_hex(24), secrets.token_hex(24)
        self.secrets = [password, nonce]
        cert, key = directory / 'cert.pem', directory / 'key.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-keyout',str(key),'-out',str(cert),
            '-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost,IP:127.0.0.1'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.proxy = Proxy(self.backend, nonce, str(cert), str(key))
        self.proxy.control = self.control
        self.url = f'https://127.0.0.1:{self.proxy.server_port}'
        self.context = ssl.create_default_context(cafile=cert)
        self.environment = {**os.environ,'GEOFEED_WP_CONTROL':str(self.control),
            'GEOFEED_WP_FIXTURE':str(directory/'fixture.json'),'PHP_CLI_SERVER_WORKERS':'4','SSL_CERT_FILE':str(cert)}
        config = {'database':self.db,'db_user':self.user,'db_password':password,'proxy_nonce':nonce,
                  'url':self.url,'root':str(self.webroot),'admin_password':secrets.token_hex(24)}
        self.secrets.append(config['admin_password'])
        (directory/'fixture.json').write_text(json.dumps(config)); (directory/'fixture.json').chmod(0o600)
        shutil.copyfile(HERE/'config.php', self.webroot/'wp-config.php')
        shutil.copyfile(HERE/'router.php', self.webroot/'test-router.php')
        mu = self.webroot/'wp-content/mu-plugins'; mu.mkdir(exist_ok=True)
        shutil.copyfile(HERE/'hooks.php', mu/'geofeed-integration.php')
        plugin = self.webroot/'wp-content/plugins/isp-geofeed-generator'
        shutil.copytree(ROOT/'wordpress/isp-geofeed-generator', plugin)
        self.plugin = plugin/'isp-geofeed-generator.php'; self.original = self.plugin.read_text()
        self.server = None; self.database_created = False
        self.log = (directory/'php.log').open('wb')

    def sql(self, statement):
        result = subprocess.run(['sudo','mariadb','--batch'],input=statement.encode(),capture_output=True,timeout=30)
        check(result.returncode == 0, 'disposable local database command')

    def packet_budget(self, desired=None):
        check(DISPOSABLE,'packet changes require the disposable GitHub-hosted Linux runner')
        statement='SELECT @@GLOBAL.max_allowed_packet;'
        if desired is not None:
            check(type(desired) is int and 1024<=desired<=1073741824,'bounded numeric fixture packet setting')
            statement=f'SET GLOBAL max_allowed_packet = {desired}; '+statement
        result=subprocess.run(['sudo','mariadb','--no-defaults','--protocol=socket','--batch','--skip-column-names'],
            input=statement.encode(),capture_output=True,timeout=30)
        if result.returncode:
            message=result.stderr.decode(errors='replace')[-4000:]
            for secret in self.secrets:message=message.replace(secret,'[REDACTED]')
            raise AssertionError('disposable packet command failed: '+message)
        value=result.stdout.strip()
        check(len(value)<=10 and value.isdigit(),'packet setting was actually measured')
        measured=int(value)
        if desired is not None:check(measured==desired,'global packet setting matches requested fixture budget')
        return measured

    def fixture(self, action, value=None):
        result = subprocess.run(['php',str(HERE/'fixture.php'),action],env=self.environment,
            input=json.dumps(value or {}).encode(),capture_output=True,timeout=60)
        if result.returncode:
            message = result.stderr.decode(errors='replace')[-4000:]
            for secret in self.secrets: message = message.replace(secret,'[REDACTED]')
            raise AssertionError('fixture '+action+' failed: '+message)
        return json.loads(result.stdout)

    def start(self):
        password = self.secrets[0]
        self.sql(f"CREATE DATABASE `{self.db}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;\n"
                 f"CREATE USER '{self.user}'@'localhost' IDENTIFIED BY '{password}';\n"
                 f"GRANT ALL ON `{self.db}`.* TO '{self.user}'@'localhost';")
        self.database_created = True
        installed = self.fixture('install')
        check(installed['wordpress'] == self.version, 'installed pinned WordPress version')
        self.accounts = installed.pop('accounts')
        self.secrets.extend(self.accounts.values())
        print('VERSIONS: '+json.dumps(installed),flush=True)
        self.proxy.publisher_headers = self.auth('publisher')
        self.proxy.policy_admin_headers = self.auth('policy_admin')
        self.server = subprocess.Popen(['php','-d','memory_limit=256M','-d','opcache.enable=0','-d','opcache.enable_cli=0','-S',f'127.0.0.1:{self.backend}',
            '-t',str(self.webroot),str(self.webroot/'test-router.php')],env=self.environment,
            stdout=self.log,stderr=self.log,start_new_session=True)
        self.thread = threading.Thread(target=self.proxy.serve_forever,daemon=True); self.thread.start()
        deadline = time.monotonic()+10
        while True:
            try:
                with socket.create_connection(('127.0.0.1',self.backend),timeout=1):break
            except OSError:
                check(self.server.poll() is None and time.monotonic()<deadline,'PHP backend became ready')
                time.sleep(.1)
        ready = self.request('GET',STATE,account='publisher')
        check(ready[0] == 200, 'authenticated WordPress readiness; no authentication retry')
        headers={k.lower():v for k,v in ready[1].items()}
        check(headers.get('x-geofeed-test-sapi')=='cli-server' and headers.get('x-geofeed-test-opcache')=='0',
              'HTTP PHP worker has opcode caching disabled for mutation controls')
        check(headers.get('x-geofeed-test-memory-limit')=='256M','real HTTP bootstrap uses finite 256 MiB PHP memory')

    def auth(self, account):
        return {'Authorization':'Basic '+base64.b64encode((account+':'+self.accounts[account]).encode()).decode()}

    def request(self, method, path, csv=None, expected=b'', account=None, direct=False, extra=None):
        headers = self.auth(account) if account else {}
        headers.update(extra or {})
        data = None
        if csv is not None:
            data = json.dumps({'csv':csv.decode(),'expected_sha256':digest(expected)}).encode()
            headers['Content-Type']='application/json'
        connection = (http.client.HTTPConnection('127.0.0.1',self.backend,timeout=20) if direct else
            http.client.HTTPSConnection('127.0.0.1',self.proxy.server_port,context=self.context,timeout=20))
        try:
            connection.request(method,path,data,headers)
            response=connection.getresponse()
            return response.status,dict(response.getheaders()),response.read()
        finally: connection.close()

    def snapshot(self):
        snapshot=self.fixture('snapshot')
        return snapshot, json.loads(snapshot['raw']) if snapshot['raw'] is not None else {'csv':'','previous_csv':''}

    def reset(self, csv=None, previous=b''):
        self.proxy.arm(None)
        (self.control/'mode').write_text('')
        self.fixture('reset',None if csv is None else {'csv':csv.decode(),'previous_csv':previous.decode()})
        (self.control/'writes.log').write_text('')
        (self.control/'write-sizes.log').write_text('')
        for name in self.control.glob('arrived-*'): name.unlink()

    def race(self, mode, candidates):
        (self.control/'mode').write_text(mode)
        expected=b'' if mode=='first' else A
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                pending=[executor.submit(self.request,'PUT',FEED,csv,expected,'publisher') for csv in candidates]
                responses=[future.result(timeout=30) for future in pending]
            return responses,self.snapshot()[1]
        finally: (self.control/'mode').write_text('')

    @staticmethod
    def race_valid(responses, doc, candidates, previous):
        if sorted(r[0] for r in responses) != [200,409]: return False
        winner=candidates[next(i for i,r in enumerate(responses) if r[0]==200)]
        return doc['csv'].encode()==winner and doc['previous_csv'].encode()==previous

    def race_tests(self):
        lower=A.replace(b'Example City',b'example city'); upper=A.replace(b'Example City',b'EXAMPLE CITY')
        mutations=[('first','INSERT IGNORE INTO {$wpdb->options}','REPLACE INTO {$wpdb->options}',[A,C]),
                   ('update','AND BINARY option_value = BINARY %s','AND option_value = %s',[lower,upper])]
        for mode,find,replace,candidates in mutations:
            check(self.original.count(find)==1,'mutation targets one SQL guard')
            try:
                self.plugin.write_text(self.original.replace(find,replace))
                # Keep the prior-history field identical for the case-only mutant.
                # Otherwise a history change alone would reject the second write.
                self.reset(None if mode=='first' else A,b'' if mode=='first' else A)
                if mode=='update':check(self.snapshot()[0]['collation'].endswith('_ci'),'case-insensitive database precondition')
                responses,doc=self.race(mode,candidates)
                statuses=sorted(r[0] for r in responses)
                verbs=[line.split()[0] for line in (self.control/'writes.log').read_text().splitlines()]
                print('RACE OBSERVATION: '+json.dumps({'mode':mode,'unsafe':True,'statuses':[r[0] for r in responses],
                    'candidate_hashes':[digest(c) for c in candidates],'stored_hash':digest(doc['csv'].encode()),
                    'previous_hash':digest(doc['previous_csv'].encode()),'sql_verbs':(self.control/'writes.log').read_text().splitlines(),
                    'barrier_workers':len(list(self.control.glob('arrived-*')))}),flush=True)
                check(verbs==(['REPLACE','REPLACE'] if mode=='first' else ['UPDATE','UPDATE']),
                      'workers executed the intended mutated SQL rather than cached code')
                check(statuses==([200,409] if mode=='first' else [200,200]),'negative control reached real competing database writes')
                check(not self.race_valid(responses,doc,candidates,b'' if mode=='first' else A),'unsafe mutation must fail race check')
                print('PASS: real WordPress '+mode+' race detects unsafe SQL mutation',flush=True)
            finally: self.plugin.write_text(self.original)
            self.reset(None if mode=='first' else A,b'' if mode=='first' else A)
            if mode=='update':check(self.snapshot()[0]['collation'].endswith('_ci'),'case-insensitive database precondition')
            responses,doc=self.race(mode,candidates)
            check(self.race_valid(responses,doc,candidates,b'' if mode=='first' else A),'guarded '+mode+' race preserves winner and prior bytes')
            check(len(list(self.control.glob('arrived-*')))==2,'two real PHP workers reached race barrier')
            print('PASS: real WordPress '+mode+' race preserves one winner',flush=True)
        check(self.plugin.read_text()==self.original,'original plugin restored after mutation controls')

    def cli(self, csv, state, *, overlap_policy=REJECT, approve=False, command='publish', expected=None, probe_cache=False):
        inventory=self.directory/'inventory.json'
        pools=[]
        locations={}
        body_policy=LONGEST_PREFIX if csv.startswith(b'# isp-geofeed-generator v2 ') else REJECT
        for i,line in enumerate(csv_body(csv,body_policy).decode().splitlines()):
            prefix,country,region,city,_=line.split(',')
            location=(country,region,city)
            if location not in locations:locations[location]=str(len(locations)+1)
            pools.append({'id':str(i+1),'ip_range':prefix,'subnet':{'subnet':prefix},'site_id':locations[location]})
        sites=[{'id':sid,'addresses':[{'id':'1','country':country,'subdivision':region.replace('-','_'),'city':city}]}
               for (country,region,city),sid in locations.items()]
        inventory.write_text(json.dumps({'pools':pools,'sites':sites}))
        config={'source':{'type':'local_json','input_path':str(inventory),'allow_initial':True},
            'extensions':{'sources':['local_json']},'credentials':{'WP_APP_PASSWORD':'env:WP_APP_PASSWORD'},
            'allowed_prefixes':['11.22.0.0/16','2001:4860:1234::/48'],'bogons':bogon_files(self.directory),
            'state_dir':str(state),'publish':{'type':'wordpress'}}
        if overlap_policy!=REJECT:config['overlap_policy']=overlap_policy
        if command=='configure-wordpress-policy':
            config['credentials']['WP_POLICY_ADMIN_APP_PASSWORD']='env:WP_POLICY_ADMIN_APP_PASSWORD'
        path=self.directory/'config.yaml';path.write_text(yaml.safe_dump(config))
        if command=='inspect-wordpress':inventory.unlink() # The inspection must work without its configured source file.
        previous={name:os.environ.get(name) for name in ('WP_SITE_URL','WP_USERNAME','WP_APP_PASSWORD','SSL_CERT_FILE',
                                                       'WP_POLICY_ADMIN_USERNAME','WP_POLICY_ADMIN_APP_PASSWORD')}
        os.environ.update({'WP_SITE_URL':self.url,'WP_USERNAME':'publisher','WP_APP_PASSWORD':self.accounts['publisher'],
            'SSL_CERT_FILE':self.environment['SSL_CERT_FILE']})
        if command=='configure-wordpress-policy':
            os.environ.update({'WP_POLICY_ADMIN_USERNAME':'policy_admin','WP_POLICY_ADMIN_APP_PASSWORD':self.accounts['policy_admin']})
        else:
            os.environ.pop('WP_POLICY_ADMIN_USERNAME',None);os.environ.pop('WP_POLICY_ADMIN_APP_PASSWORD',None)
        try:
            output=io.StringIO()
            with contextlib.redirect_stdout(output),contextlib.redirect_stderr(io.StringIO()):
                    args=[command,'--config',str(path)]
                    if approve:args+=['--approve-location-changes',digest(csv)]
                    if expected:args+=['--expected-current-sha256',expected]
                    if probe_cache:args+=['--probe-cache']
                    result=main(args)
        finally:
            for name,value in previous.items():
                if value is None:os.environ.pop(name,None)
                else:os.environ[name]=value
        if command=='inspect-wordpress':
            status=json.loads(output.getvalue());check(status.get('inspection_only') is True and 'healthy' not in status,'inspection cannot claim full publication health')
        else:
            status=json.loads((state/'status.json').read_text())['data']
            check(status.get('healthy')==((result==0) if command=='publish' else False),'CLI health is present and matches actual operation')
        return result,status

    def publication_tests(self):
        self.reset()
        for account,extra in [(None,{}),('reader',{}),('publisher',{'Authorization':'Basic '+base64.b64encode(b'publisher:wrong-password').decode()})]:
            check(self.request('PUT',FEED,A,account=account,extra=extra)[0] in (401,403),'unauthorized write refused')
        check(self.request('GET',STATE)[0] in (401,403),'anonymous stored state refused')
        check(self.request('PUT',FEED,A,account='publisher',direct=True,extra={'X-Forwarded-Proto':'https'})[0] in (401,403),'forged forwarding header cannot authorize HTTP')
        check(self.snapshot()[0]['raw'] is None,'denied writes keep absent state')
        print('PASS: real WordPress application-password role and direct-HTTP refusals',flush=True)
        state=self.directory/'successful-cli'
        check(self.cli(A,state)[0]==0,'CLI first publication')
        check(self.cli(B,state)[0]==0,'CLI changed publication')
        before=self.snapshot()[0]['raw']
        backups={name:((state/name).read_bytes(),(state/name).stat().st_mtime_ns) for name in ('before.csv','last-good.csv')}
        mutations=(self.control/'writes.log').read_bytes()
        result,status=self.cli(B,state)
        check(result==0 and status['changed'] is False,'CLI unchanged result')
        check(self.snapshot()[0]['raw']==before and (self.control/'writes.log').read_bytes()==mutations,'unchanged real database document and zero write attempts')
        for name,prior in backups.items():check(((state/name).read_bytes(),(state/name).stat().st_mtime_ns)==prior,'unchanged local recovery history')
        public=self.request('GET',FEED)
        headers={k.lower():v for k,v in public[1].items()}
        check(public[0]==200 and public[2]==B and headers.get('content-type','').startswith('text/csv')
              and 'no-store' in headers.get('cache-control','') and headers.get('x-content-type-options')=='nosniff','real unauthenticated CSV bytes and headers')
        print('PASS: real WordPress CLI first/change/no-op and unchanged database/recovery history',flush=True)
        for bad in (A.replace(b',US,',b',XX,'),A+A,A.replace(b'11.22.33.0/24',b'10.0.0.0/24')):
            check(self.request('PUT',FEED,bad,B,'publisher')[0]==400,'real REST malformed/ISO/bogon input refusal')
        check(self.snapshot()[0]['raw']==before,'invalid payloads preserve real database state')
        print('PASS: real WordPress invalid payloads preserve stored feed',flush=True)
        self.reset(A);self.proxy.arm('preflight-mismatch')
        target=self.directory/'preflight';target.mkdir()
        (target/'before.csv').write_bytes(b'prior-history');(target/'last-good.csv').write_bytes(A)
        writes=(self.control/'writes.log').read_bytes()
        result,status=self.cli(B,target)
        check(result==1 and status['healthy'] is False and 'no write attempted' in status['error'],'public preflight mismatch is unhealthy')
        check(self.snapshot()[1]['csv'].encode()==A and (self.control/'writes.log').read_bytes()==writes,'preflight mismatch makes no database writes')
        check((target/'before.csv').read_bytes()==b'prior-history' and (target/'last-good.csv').read_bytes()==A,'preflight mismatch preserves recovery history')
        print('PASS: real WordPress stale public preflight refuses writes and keeps recovery history',flush=True)
        expected_faults={'bad-readback':['public-mismatch'],'lost-reply':['reply-dropped'],
            'winner':['public-mismatch','winner-committed'],'failed-recovery':['public-mismatch','recovery-refused']}
        for mode,expected,healthy_recovery in [('bad-readback',A,True),('lost-reply',A,True),('winner',C,False),('failed-recovery',B,False)]:
            self.reset(A);self.proxy.arm(mode)
            target=self.directory/mode;target.mkdir()
            (target/'last-good.csv').write_bytes(A)
            result,status=self.cli(B,target)
            check(result==1 and status['healthy'] is False,'fault must be unhealthy: '+mode)
            check(self.snapshot()[1]['csv'].encode()==expected,'fault stored bytes: '+mode)
            check(self.request('GET',FEED)[2]==expected,'fault unauthenticated public bytes: '+mode)
            check((target/'before.csv').read_bytes()==A and (target/'last-good.csv').read_bytes()==A,'fault keeps recovery baseline: '+mode)
            check(('Previous feed retained/restored' in status['error'])==healthy_recovery,'honest recovery result: '+mode)
            check(self.proxy.faults==expected_faults[mode],'all intended fault injections actually ran: '+mode)
            print('PASS: real WordPress '+mode+' stored/public/recovery workload',flush=True)

    def https_guard_tests(self):
        flag=self.control/'allow-http-application-passwords'
        authenticated=self.control/'http-auth.log'
        find='return is_ssl() && ('
        check(self.original.count(find)==1,'HTTPS mutation targets one plugin permission guard')
        def direct():
            return self.request('PUT',FEED,B,A,'publisher',direct=True,extra={'X-Forwarded-Proto':'https'})
        def refused(response,prior,writes):
            return (response[0]==403 and json.loads(response[2]).get('code')=='rest_forbidden'
                    and self.snapshot()[0]['raw']==prior and (self.control/'writes.log').read_bytes()==writes)
        try:
            flag.write_text('test-only core HTTP availability; verify real password')
            self.reset(A);authenticated.write_text('')
            prior=self.snapshot()[0]['raw'];writes=(self.control/'writes.log').read_bytes()
            response=direct()
            check(refused(response,prior,writes),'plugin HTTPS guard refuses authenticated direct HTTP without writes')
            check(authenticated.read_text().splitlines()==['http publisher'],'core really authenticated publisher over HTTP before plugin refusal')
            print('PASS: real WordPress plugin HTTPS guard refuses core-authenticated HTTP',flush=True)
            self.plugin.write_text(self.original.replace(find,'return ('))
            response=direct()
            doc=self.snapshot()[1]
            check(response[0]==200 and doc['csv'].encode()==B and doc['previous_csv'].encode()==A,
                  'unsafe permission mutation really publishes over direct HTTP')
            check(not refused(response,prior,writes) and (self.control/'writes.log').read_bytes()!=writes,
                  'HTTPS refusal check detects removed plugin guard')
            print('HTTPS OBSERVATION: '+json.dumps({'unsafe_status':response[0],'stored_hash':digest(doc['csv'].encode()),
                'candidate_hash':digest(B),'authenticated_http_publishers':authenticated.read_text().splitlines().count('http publisher')}),flush=True)
            print('PASS: real WordPress plugin HTTPS control detects removed guard',flush=True)
            self.plugin.write_text(self.original);self.reset(A);authenticated.write_text('')
            prior=self.snapshot()[0]['raw'];writes=(self.control/'writes.log').read_bytes()
            check(refused(direct(),prior,writes),'restored plugin HTTPS guard blocks direct HTTP and preserves feed')
            check(authenticated.read_text().splitlines()==['http publisher'],'restored guard still reaches core-authenticated user')
            check(self.request('PUT',FEED,B,A,'publisher')[0]==200 and self.snapshot()[1]['csv'].encode()==B,
                  'restored plugin still permits real authenticated HTTPS publication')
            print('PASS: real WordPress restored HTTPS guard blocks HTTP and allows HTTPS',flush=True)
            admin=WordPress(self.url,'policy_admin',self.accounts['policy_admin'])
            admin.http.opener=build_opener(NoRedirects(),HTTPSHandler(context=self.context))
            def direct_policy():
                before=admin.policy_state()
                body=json.dumps({'protocol_version':2,'required_overlap_policy':LONGEST_PREFIX,
                    'expected_sha256':digest(before.csv),'expected_overlap_policy':before.policy,
                    'expected_required_overlap_policy':before.required,'expected_publication_id':before.publication_id,
                    'publication_id':secrets.token_hex(16)}).encode()
                connection=http.client.HTTPConnection('127.0.0.1',self.backend,timeout=20)
                try:
                    connection.request('PUT',POLICY_V2,body,{**self.auth('policy_admin'),'Content-Type':'application/json','X-Forwarded-Proto':'https'})
                    response=connection.getresponse();data=response.read();return response.status,data
                finally:connection.close()
            self.reset(A);authenticated.write_text('');prior=self.snapshot()[0]['raw'];writes=(self.control/'writes.log').read_bytes()
            check(direct_policy()[0]==403 and self.snapshot()[0]['raw']==prior and (self.control/'writes.log').read_bytes()==writes,'administrative plugin HTTPS guard refuses a core-authenticated HTTP administrator')
            check(authenticated.read_text().splitlines().count('http administrator')==1,'core really authenticated HTTP administrator')
            admin_find="return is_ssl() && current_user_can('manage_options');"
            check(self.original.count(admin_find)==1,'administrative HTTPS mutation targets one guard')
            self.plugin.write_text(self.original.replace(admin_find,"return current_user_can('manage_options');"))
            unsafe=direct_policy()
            check(unsafe[0]==200 and admin.policy_state().required==LONGEST_PREFIX and self.snapshot()[0]['raw']!=prior,'removed administrative HTTPS guard really changes stored policy over HTTP')
            print('POLICY HTTPS OBSERVATION: '+json.dumps({'unsafe_status':unsafe[0],'required_policy':admin.policy_state().required,
                'authenticated_http_administrators':authenticated.read_text().splitlines().count('http administrator')}),flush=True)
            self.plugin.write_text(self.original);self.reset(A)
            prior=self.snapshot()[0]['raw'];writes=(self.control/'writes.log').read_bytes()
            check(direct_policy()[0]==403 and self.snapshot()[0]['raw']==prior and (self.control/'writes.log').read_bytes()==writes,'restored administrative guard again refuses HTTP')
            admin.configure_policy(LONGEST_PREFIX,admin.policy_state(),secrets.token_hex(16))
            check(admin.policy_state().required==LONGEST_PREFIX and admin.policy_state().csv==A,'restored administrative guard permits authenticated HTTPS configuration')
            print('PASS: real WordPress administrative HTTPS guard detects mutation and restores HTTP refusal',flush=True)
        finally:
            self.plugin.write_text(self.original)
            flag.unlink(missing_ok=True)
        check(self.plugin.read_text()==self.original and not flag.exists(),'HTTP control and mutation removed')

    def nested_policy_tests(self):
        self.reset()
        client=WordPress(self.url,'publisher',self.accounts['publisher'])
        client.http.opener=build_opener(NoRedirects(),HTTPSHandler(context=self.context))
        admin=WordPress(self.url,'policy_admin',self.accounts['policy_admin'])
        admin.http.opener=build_opener(NoRedirects(),HTTPSHandler(context=self.context))
        rows=csv_records(A)
        child={'prefix':'11.22.33.0/25','location':{'country':'US','region':'US-IL','city':'Override City'}}
        n_a=render_csv(rows,overlap_policy=LONGEST_PREFIX)
        n_b=render_csv([rows[0],child,*rows[1:]],overlap_policy=LONGEST_PREFIX)
        n_c=render_csv(csv_records(C),overlap_policy=LONGEST_PREFIX)
        n_d=render_csv([{**r,'location':{**r['location'],'city':'Other City'}} for r in rows],overlap_policy=LONGEST_PREFIX)
        def configure_server(policy=LONGEST_PREFIX):
            admin.configure_policy(policy,admin.policy_state(),secrets.token_hex(16))
        try:
            result,status=self.cli(n_a,self.directory/'nested-setup',overlap_policy=LONGEST_PREFIX)
            check(result==1 and 'configured for reject' in status['error'],'real protocol capability is separate from instance policy')
            check(self.snapshot()[0]['raw'] is None and not (self.directory/'nested-setup/before.csv').exists(),'configuration refusal before write/history')
            try:client.configure_policy(LONGEST_PREFIX,client.policy_state(),secrets.token_hex(16))
            except GeofeedError as exc:check('administration refused' in str(exc),'ordinary publisher cannot configure policy')
            else:raise AssertionError('publisher was allowed to change server policy')
            check(self.snapshot()[0]['raw'] is None,'publisher policy refusal keeps empty database')
            result,status=self.cli(n_a,self.directory/'policy-admin-setup',overlap_policy=LONGEST_PREFIX,
                                   command='configure-wordpress-policy',expected=digest(b''))
            check(result==0 and status['configured_policy'] is True and status['healthy'] is False,'real administrator CLI initializes database-bound policy')
            check(client.policy_state().required==LONGEST_PREFIX,'real server policy is configured in stored state')
            raw=self.snapshot()[0]['raw'];writes=(self.control/'writes.log').read_bytes()
            result,status=self.cli(n_a,self.directory/'policy-admin-setup',overlap_policy=LONGEST_PREFIX,
                                   command='configure-wordpress-policy',expected=digest(b''))
            check(result==0 and status['changed'] is False and self.snapshot()[0]['raw']==raw and (self.control/'writes.log').read_bytes()==writes,'unchanged policy configuration makes zero geofeed SQL writes')
            result,status=self.cli(A,self.directory/'strict-client-nested-site')
            check(result==1 and 'configured for longest_prefix' in status['error'] and not (self.directory/'strict-client-nested-site/before.csv').exists(),'new strict client diagnoses nested instance before replacing backups')
            check(self.request('PUT',FEED,A,account='publisher')[0]==409 and self.snapshot()[0]['raw']==raw,'old writer refused on empty nested site')
            print('PASS: real WordPress separate administrator policy setup, unchanged configuration and publisher refusal',flush=True)
            check(self.request('GET',STATE_V2)[0] in (401,403),'anonymous v2 state refused')
            state=self.directory/'nested-cli'
            check(self.cli(n_a,state,overlap_policy=LONGEST_PREFIX)[0]==0,'real nested first CLI publication')
            original=self.snapshot()[0]['raw'];writes=(self.control/'writes.log').read_bytes()
            before=client.policy_state()
            check(before.previous==b'' and before.previous_policy==REJECT,'empty baseline isolates restore policy check')
            try:client.replace_policy(b'',LONGEST_PREFIX,before,secrets.token_hex(16),'restore')
            except GeofeedError as exc:check(str(exc).startswith('HTTP 409'),'matching empty recovery bytes with wrong policy refused')
            else:raise AssertionError('publisher restored matching bytes with wrong prior policy')
            check(self.snapshot()[0]['raw']==original and (self.control/'writes.log').read_bytes()==writes,'wrong restore policy preserves stored data and history without SQL')
            print('PASS: real WordPress restore refuses matching baseline bytes with wrong policy',flush=True)
            result,status=self.cli(n_b,state,overlap_policy=LONGEST_PREFIX)
            check(result==1 and 'location changes' in status['error'] and self.snapshot()[0]['raw']==original,'real nested guard refuses override move')
            check((self.control/'writes.log').read_bytes()==writes,'guarded override makes zero geofeed SQL writes')
            check(self.cli(n_b,state,overlap_policy=LONGEST_PREFIX,approve=True)[0]==0,'exact approved nested override CLI publication')
            snapshot,doc=self.snapshot()
            check(doc['csv'].encode()==n_b and doc['previous_csv'].encode()==n_a and doc['overlap_policy']==doc['previous_overlap_policy']==LONGEST_PREFIX,'real nested current/prior policy stored together')
            paths=[state/name for name in ('before.csv','before-policy.json','last-good.csv')]
            stamps={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in paths};writes=(self.control/'writes.log').read_bytes()
            check(self.cli(n_b,state,overlap_policy=LONGEST_PREFIX)[0]==0 and self.snapshot()[0]['raw']==snapshot['raw'],'nested unchanged run preserves raw document')
            check((self.control/'writes.log').read_bytes()==writes and {p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in paths}==stamps,'nested no-op preserves SQL and private history')
            result,status=self.cli(n_a,state,overlap_policy=LONGEST_PREFIX)
            check(result==1 and 'location changes' in status['error'] and self.snapshot()[0]['raw']==snapshot['raw'] and
                  (self.control/'writes.log').read_bytes()==writes and {p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in paths}==stamps,'parent fallback guard preserves real data, policy and recovery history')
            print('PASS: real WordPress nested parent-fallback guard preserves data policy and history',flush=True)
            check(self.request('PUT',FEED,C,n_b,'publisher')[0]==409 and self.request('GET',FEED)[2]==n_b,'old writer cannot overwrite existing nested state')
            print('PASS: real WordPress nested CLI policy, exact approval, old-client refusal and unchanged history',flush=True)
            before=client.policy_state();raw=self.snapshot()[0]['raw'];writes=(self.control/'writes.log').read_bytes()
            for bad in (wrap_csv(A.replace(b',US,',b',XX,')),wrap_csv(A+A),wrap_csv(A.replace(b'11.22.33.0/24',b'8.0.0.0/6'))):
                try:client.replace_policy(bad,LONGEST_PREFIX,before,secrets.token_hex(16))
                except GeofeedError as exc:check(str(exc).startswith('HTTP 400'),'real v2 invalid payload refusal')
                else:raise AssertionError('real v2 accepted invalid payload')
            from dataclasses import replace as changed_snapshot
            for stale in (changed_snapshot(before,required=REJECT),changed_snapshot(before,publication_id='0'*32),changed_snapshot(before,policy=REJECT)):
                try:client.replace_policy(n_d,LONGEST_PREFIX,stale,secrets.token_hex(16))
                except GeofeedError as exc:check(str(exc).startswith('HTTP 409'),'real stale policy/owner refusal')
                else:raise AssertionError('real v2 accepted stale policy or owner')
            check(self.snapshot()[0]['raw']==raw and (self.control/'writes.log').read_bytes()==writes,'v2 refusal controls keep exact data and history')
            configure_server(REJECT);configured=self.snapshot()[0]['raw']
            try:client.replace_policy(n_d,LONGEST_PREFIX,before,secrets.token_hex(16))
            except GeofeedError as exc:check(str(exc).startswith('HTTP 409'),'actual administrator switch conflicts with publisher snapshot')
            else:raise AssertionError('real v2 accepted a changed server policy')
            check(self.snapshot()[0]['raw']==configured and client.policy_state().csv==before.csv,'stale publisher preserves administrative winner')
            configure_server()
            print('PASS: real WordPress nested invalid payload and stale policy/owner refusals',flush=True)
            self.reset()
            before=admin.policy_state();identities=[secrets.token_hex(16),secrets.token_hex(16)]
            (self.control/'mode').write_text('first')
            def initialize(index):
                try:admin.configure_policy(LONGEST_PREFIX,before,identities[index]);return 200
                except GeofeedError as exc:
                    if str(exc).startswith('HTTP 409'):return 409
                    raise
            try:
                with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(initialize,range(2)))
            finally:(self.control/'mode').write_text('')
            check(sorted(statuses)==[200,409] and len(list(self.control.glob('arrived-*')))==2,'first administrative INSERT IGNORE preserves one policy owner')
            check(client.policy_state().publication_id==identities[statuses.index(200)],'administrative winner identity is preserved')
            for mode,candidates in [('first-feed',[n_a,n_c]),('update',[n_b,n_d])]:
                for name in self.control.glob('arrived-*'):name.unlink()
                before=client.policy_state();identities=[secrets.token_hex(16),secrets.token_hex(16)]
                (self.control/'mode').write_text('update')
                def write(index):
                    try:client.replace_policy(candidates[index],LONGEST_PREFIX,before,identities[index]);return 200
                    except GeofeedError as exc:
                        if str(exc).startswith('HTTP 409'):return 409
                        raise
                try:
                    with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(write,range(2)))
                finally:(self.control/'mode').write_text('')
                check(sorted(statuses)==[200,409] and len(list(self.control.glob('arrived-*')))==2,'two real v2 PHP workers preserve exactly one writer')
                winner=statuses.index(200);after=client.policy_state()
                check(after.csv==candidates[winner] and after.publication_id==identities[winner] and after.previous==before.csv and after.previous_policy==before.policy,'v2 race preserves winner ID and complete prior policy')
            print('PASS: real WordPress nested first/update races preserve one owner and policy history',flush=True)
            for name in self.control.glob('arrived-*'):name.unlink()
            before=client.policy_state();ids=[secrets.token_hex(16),secrets.token_hex(16)]
            (self.control/'mode').write_text('update')
            def competing(index):
                try:
                    if index==0:client.replace_policy(n_c,LONGEST_PREFIX,before,ids[0])
                    else:admin.configure_policy(REJECT,before,ids[1])
                    return 200
                except GeofeedError as exc:
                    if str(exc).startswith('HTTP 409'):return 409
                    raise
            try:
                with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(competing,range(2)))
            finally:(self.control/'mode').write_text('')
            observed=client.policy_state();winner=statuses.index(200) if 200 in statuses else -1
            check(sorted(statuses)==[200,409] and len(list(self.control.glob('arrived-*')))==2 and observed.publication_id==ids[winner],'policy and feed use the same real database CAS')
            check((winner==0 and observed.csv==n_c and observed.required==LONGEST_PREFIX) or
                  (winner==1 and observed.csv==before.csv and observed.required==REJECT),'no mixed policy/data winner')
            print('PASS: real WordPress administrator versus publisher race preserves one complete state',flush=True)
            for mode in ('bad-readback','lost-reply','winner','failed-recovery','policy-winner'):
                self.reset();target=self.directory/('nested-'+mode)
                configure_server()
                check(self.cli(n_a,target,overlap_policy=LONGEST_PREFIX)[0]==0,'nested fault baseline publication')
                self.proxy.nested_winner=n_c;self.proxy.arm(mode)
                result,status=self.cli(n_b,target,overlap_policy=LONGEST_PREFIX,approve=True)
                observed=client.policy_state()
                expected=n_c if mode=='winner' else n_b if mode in ('failed-recovery','policy-winner') else n_a
                check(result==1 and status['healthy'] is False and observed.csv==expected and observed.policy==LONGEST_PREFIX,'nested fault has explicit unhealthy stored policy outcome: '+mode)
                check(self.request('GET',FEED)[2]==expected and (target/'before.csv').read_bytes()==n_a,'nested fault public bytes and baseline retained')
                check(self.proxy.faults==({'bad-readback':['public-mismatch'],'lost-reply':['reply-dropped'],
                    'winner':['public-mismatch','winner-committed'],'failed-recovery':['public-mismatch','recovery-refused'],
                    'policy-winner':['policy-winner-committed']}[mode]),'nested fault really fired: '+mode)
                if mode=='failed-recovery':
                    self.proxy.arm(None)
                    result,status=self.cli(n_b,target,overlap_policy=LONGEST_PREFIX,command='recover-wordpress',expected=digest(n_b))
                    check(result==0 and status['recovered'] is True and status['healthy'] is False and client.policy_state().csv==n_a,'manual real WordPress recovery restores exact owned baseline without marking publication healthy')
                    prior=((target/'status.json').read_bytes(),(target/'status.json').stat().st_mtime_ns)
                    result,inspection=self.cli(n_a,target,overlap_policy=LONGEST_PREFIX,command='inspect-wordpress')
                    check(result==0 and inspection['public_matches_stored'] and inspection['policy_state_stable'] and
                          ((target/'status.json').read_bytes(),(target/'status.json').stat().st_mtime_ns)==prior,'read-only inspection leaves failed publication status untouched')
                if mode=='policy-winner':
                    original=self.snapshot()[0]['raw'];self.proxy.arm(None)
                    result,status=self.cli(n_b,target,overlap_policy=LONGEST_PREFIX,command='recover-wordpress',expected=digest(n_b))
                    check(result==1 and self.snapshot()[0]['raw']==original and client.policy_state().required==REJECT,'manual recovery refuses an administrative owner of identical candidate bytes')
                print('PASS: real WordPress nested '+mode+' stored/public/policy recovery workload',flush=True)
            # Restore a legacy baseline after a real strict-to-nested upgrade fault.
            self.reset(A);configure_server();self.proxy.arm('bad-readback');self.proxy.nested_winner=n_c
            result,status=self.cli(n_a,self.directory/'nested-upgrade-recovery',overlap_policy=LONGEST_PREFIX)
            observed=client.policy_state()
            check(result==1 and observed.csv==A and observed.policy==REJECT and self.request('GET',FEED)[2]==A,'failed upgrade restores prior strict bytes and policy')
            print('PASS: real WordPress failed nested upgrade restores strict baseline policy',flush=True)
            self.reset();configure_server();self.proxy.arm('bad-readback')
            result,status=self.cli(n_a,self.directory/'nested-empty-recovery',overlap_policy=LONGEST_PREFIX)
            observed=client.policy_state()
            check(result==1 and observed.csv==b'' and observed.policy==REJECT and self.request('GET',FEED)[0]==404,'failed first nested publication restores empty strict state through DELETE')
            print('PASS: real WordPress failed first nested publish restores empty strict baseline',flush=True)
            self.reset();configure_server();target=self.directory/'nested-strict-migration'
            check(self.cli(n_a,target,overlap_policy=LONGEST_PREFIX)[0]==0 and self.cli(n_b,target,overlap_policy=LONGEST_PREFIX,approve=True)[0]==0,'strict migration baseline')
            result,status=self.cli(n_b,self.directory/'admin-strict-migration',command='configure-wordpress-policy',expected=digest(n_b))
            check(result==0 and client.policy_state().required==REJECT and client.policy_state().csv==n_b,'administrator changes accepted policy without changing feed')
            raw=self.snapshot()[0]['raw'];writes=(self.control/'writes.log').read_bytes()
            result,status=self.cli(A,target)
            check(result==1 and 'location changes' in status['error'] and self.snapshot()[0]['raw']==raw and
                  (self.control/'writes.log').read_bytes()==writes,'strict migration still guards parent fallback move')
            check(self.cli(A,target,approve=True)[0]==0 and client.policy_state().policy==REJECT and self.request('GET',FEED)[2]==A,'approved strict migration verifies exact bytes and policy')
            before=client.policy_state();raw=self.snapshot()[0]['raw'];writes=(self.control/'writes.log').read_bytes()
            check(before.previous==n_b and before.previous_policy==LONGEST_PREFIX and before.required==REJECT,'strict migration retains one exact nested baseline')
            try:client.replace_policy(n_d,LONGEST_PREFIX,before,secrets.token_hex(16),'restore')
            except GeofeedError as exc:check(str(exc).startswith('HTTP 409'),'invented nested recovery bytes refused after strict downgrade')
            else:raise AssertionError('publisher bypassed strict policy with invented recovery bytes')
            check(self.snapshot()[0]['raw']==raw and (self.control/'writes.log').read_bytes()==writes,'wrong restore bytes preserve stored data and history without SQL')
            print('PASS: real WordPress restore refuses different bytes with matching prior policy',flush=True)
            check(self.cli(A,target)[0]==0 and self.snapshot()[0]['raw']==raw,'unchanged strict publication retains nested baseline')
            client.replace_policy(n_b,LONGEST_PREFIX,client.policy_state(),secrets.token_hex(16),'restore')
            observed=client.policy_state()
            check(observed.csv==n_b and observed.policy==LONGEST_PREFIX and observed.required==REJECT and observed.previous==A and
                  self.request('GET',FEED)[2]==n_b,'publisher can restore exact prior nested feed while accepted policy remains strict')
            check(self.request('PUT',FEED,C,n_b,'publisher')[0]==409,'old strict writer refused after nested baseline restoration')
            check(self.cli(A,target,approve=True)[0]==0,'approved strict publication works after exact nested restoration')
            check(self.request('PUT',FEED,C,A,'publisher')[0]==200 and client.policy_state().required==REJECT and client.policy_state().csv==C,'legacy strict writes preserve the stored policy binding')
            before=client.policy_state();raw=self.snapshot()[0]['raw'];writes=(self.control/'writes.log').read_bytes()
            check(before.previous==A and before.previous_policy==REJECT,'later changed strict publication evicts nested history')
            try:client.replace_policy(n_b,LONGEST_PREFIX,before,secrets.token_hex(16),'restore')
            except GeofeedError as exc:check(str(exc).startswith('HTTP 409'),'evicted nested baseline cannot be restored')
            else:raise AssertionError('publisher restored a nested baseline no longer retained')
            check(self.snapshot()[0]['raw']==raw and (self.control/'writes.log').read_bytes()==writes,'evicted baseline refusal preserves strict data and history without SQL')
            print('PASS: real WordPress publisher recovery exception keeps exact retained baseline and expires after changed publication',flush=True)
            print('PASS: real WordPress approved strict migration and legacy strict compatibility',flush=True)
        finally:
            self.proxy.nested_winner=None;self.proxy.arm(None)

    def delivery_hook_tests(self):
        flag=self.control/'delivery-mode';log=self.control/'delivery.log';marker=self.control/'purged.sha256'
        client=WordPress(self.url,'publisher',self.accounts['publisher'])
        client.http.opener=build_opener(NoRedirects(),HTTPSHandler(context=self.context))
        admin=WordPress(self.url,'policy_admin',self.accounts['policy_admin'])
        admin.http.opener=build_opener(NoRedirects(),HTTPSHandler(context=self.context))
        rows=csv_records(A)
        nested_first=render_csv(rows,overlap_policy=LONGEST_PREFIX)
        nested_second=render_csv([rows[0],{'prefix':'11.22.33.0/25','location':{'country':'US','region':'US-IL','city':'Override City'}},*rows[1:]],overlap_policy=LONGEST_PREFIX)
        def events():return [json.loads(line) for line in log.read_text().splitlines()]
        for version,policy,first,second,needle in (
            (1,REJECT,A,B,"$result = isp_geofeed_generator_delivery_hook($before, $csv, 'reject', 'publish', $request->get_method(), 1);"),
            (2,LONGEST_PREFIX,nested_first,nested_second,"$result = isp_geofeed_generator_delivery_hook($before, $csv, $policy, $input['operation'], $request->get_method(), 2);"),
        ):
            def prepare(label,mode='success'):
                flag.write_text('');self.plugin.write_text(self.original);self.reset()
                if version==2:admin.configure_policy(policy,admin.policy_state(),secrets.token_hex(16))
                state=self.directory/('delivery-'+str(version)+'-'+label)
                check(self.cli(first,state,overlap_policy=policy)[0]==0,'delivery hook baseline is a verified normal publication')
                log.write_text('');marker.write_text(digest(first));flag.write_text(mode)
                self.proxy.cached_feed=first;self.proxy.arm('purge-cache')
                return state
            try:
                state=prepare('missing-notification')
                check(self.original.count(needle)==1,'notification mutation targets exactly one API callback')
                self.plugin.write_text(self.original.replace(needle,'$result = true;'))
                result,status=self.cli(second,state,overlap_policy=policy,approve=True)
                check(result==1 and not status['healthy'] and not events() and 'purge-cache-stale' in self.proxy.faults and
                      client.policy_state().csv==first and client.read_public(overlap_policy=policy)==first,'removed notification leaves real cached bytes stale, fails publication and restores baseline')
                print('DELIVERY HOOK OBSERVATION: '+json.dumps({'api_version':version,'scenario':'missing-notification',
                    'healthy':status['healthy'],'hook_events':len(events()),'stale_control_fired':True}),flush=True)
                self.plugin.write_text(self.original)
                state=prepare('success')
                result,status=self.cli(second,state,overlap_policy=policy,approve=True)
                observed=events()
                check(result==0 and status['healthy'] and len(observed)==1 and marker.read_text()==digest(second) and
                      client.read_public(overlap_policy=policy)==second,'real installed callback purges held canonical bytes before verified public read-back')
                event=observed[0]
                check(event=={'schema_version':1,'api_version':version,'url':self.url+FEED,'sha256':digest(second),
                    'previous_sha256':digest(first),'overlap_policy':policy,'operation':'publish','method':'PUT'},'real hook event has only fixed public metadata')
                raw=self.snapshot()[0]['raw'];writes=(self.control/'writes.log').read_bytes()
                private=[p for p in (state/'before.csv',state/'before-policy.json',state/'last-good.csv') if p.exists()]
                prior={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in private}
                check(self.cli(second,state,overlap_policy=policy)[0]==0 and len(events())==1 and self.snapshot()[0]['raw']==raw and
                      (self.control/'writes.log').read_bytes()==writes and {p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in private}==prior,'unchanged publication does not retry purge or rewrite history')
                if version==1:client.replace(first,second)
                else:client.replace_policy(first,policy,client.policy_state(),secrets.token_hex(16),'restore')
                check(len(events())==2 and events()[-1]['operation']==('restore' if version==2 else 'publish') and
                      client.read_public(overlap_policy=policy)==first,'conditional restore purges its own committed baseline')
                if version==1:client.replace(b'',first)
                else:client.replace_policy(b'',policy,client.policy_state(),secrets.token_hex(16))
                check(len(events())==3 and events()[-1]['method']=='DELETE' and events()[-1]['sha256']==digest(b'') and
                      client.read_public(overlap_policy=policy)==b'','changed deletion purges the canonical empty-feed response')
                print('DELIVERY HOOK OBSERVATION: '+json.dumps({'api_version':version,'scenario':'success-noop-restore-delete',
                    'changed_healthy':status['healthy'],'hook_events':len(events()),'public_empty':True}),flush=True)
                for mode in ('fail','no-effect'):
                    state=prepare(mode,mode)
                    prior=((state/'last-good.csv').read_bytes(),(state/'last-good.csv').stat().st_mtime_ns)
                    result,status=self.cli(second,state,overlap_policy=policy,approve=True)
                    observed=events()
                    check(result==1 and not status['healthy'] and len(observed)==2 and
                          [event['sha256'] for event in observed]==[digest(second),digest(first)] and
                          client.policy_state().csv==first and client.read_public(overlap_policy=policy)==first,'failed or ineffective purge cannot report healthy and uses only conditional recovery')
                    check((state/'before.csv').read_bytes()==first and
                          ((state/'last-good.csv').read_bytes(),(state/'last-good.csv').stat().st_mtime_ns)==prior and
                          'PRIVATE' not in status['error'],'failure preserves private baseline and last-good history without leaking callback details')
                    if mode=='fail':check('503' in status['error'],'post-commit callback exception returned HTTP 503')
                    else:check('purge-cache-stale' in self.proxy.faults,'ineffective successful callback really left public bytes stale')
                    print('DELIVERY HOOK OBSERVATION: '+json.dumps({'api_version':version,'scenario':mode,
                        'healthy':status['healthy'],'hook_events':len(observed),'stored_and_public_restored':True}),flush=True)
            finally:
                self.plugin.write_text(self.original);flag.write_text('');self.proxy.cached_feed=None;self.proxy.arm(None)
        print('PASS: real WordPress delivery hooks preserve CAS, public verification, no-op history and conditional recovery',flush=True)

    def cache_inspection_tests(self):
        self.reset(A)
        state=self.directory/'cache-inspection';state.mkdir()
        (state/'status.json').write_bytes(b'previous failed publication')
        (state/'before.csv').write_bytes(C);(state/'last-good.csv').write_bytes(A)
        prior={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in state.iterdir()}
        stored=self.snapshot()[0]['raw'];writes=(self.control/'writes.log').read_bytes()
        cases=[('cache-canonical-stale','canonical_differs_probe_matches',False,True,['cache-canonical-stale']),
               ('cache-both-stale','both_differ_same_bytes',False,False,['cache-canonical-stale','cache-probe-stale']),
               ('cache-canonical-unavailable','canonical_unavailable_probe_matches',None,True,['cache-canonical-unavailable']),
               (None,'both_match',True,True,[])]
        try:
            for mode,finding,canonical,probe,faults in cases:
                self.proxy.arm(mode)
                result,report=self.cli(A,state,command='inspect-wordpress',probe_cache=True)
                observed=list(self.proxy.request_sizes)
                check(result==(0 if finding=='both_match' else 1) and report['delivery_finding']==finding and
                      report['public_matches_stored']==canonical and report['cache_probe_matches_stored']==probe and
                      report['policy_state_stable'] is True,'real diagnostic distinguishes canonical, probe and unavailable observations')
                check(self.proxy.faults==faults,'cache diagnostic control really fired')
                check(len(observed)==4 and all(r['method']=='GET' for r in observed),'exactly two state and two public GETs; no write or retry')
                check(sum(r['path']==STATE_V2 for r in observed)==2,'authenticated state brackets public observations')
                public=[r for r in observed if urlsplit(r['path']).path==FEED]
                check(len(public)==2 and public[0]['path']==FEED and all(not r['authenticated'] for r in public),'both public observations are anonymous')
                query=parse_qs(urlsplit(public[1]['path']).query)
                check(set(query)=={'isp_geofeed_probe'} and len(query['isp_geofeed_probe'])==1 and
                      len(query['isp_geofeed_probe'][0])==32 and set(query['isp_geofeed_probe'][0])<=set('0123456789abcdef'),'fresh probe stays on exact configured feed route')
                check(not (self.directory/'inventory.json').exists(),'input inventory was unavailable during actual CLI inspection')
                check(self.snapshot()[0]['raw']==stored and (self.control/'writes.log').read_bytes()==writes and
                      {p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in state.iterdir()}==prior,'read-only diagnostic preserves feed, SQL, failed status and recovery history')
                print('CACHE INSPECTION OBSERVATION: '+json.dumps({'mode':mode,'delivery_finding':finding,
                    'canonical_matches':canonical,'probe_matches':probe,'exit_code':result,'get_requests':len(observed),
                    'state_stable':report['policy_state_stable'],'faults':self.proxy.faults}),flush=True)
            print('PASS: real WordPress cache inspection distinguishes stale canonical and probe responses without writes or health changes',flush=True)
        finally:self.proxy.arm(None)

    def capacity_tests(self):
        self.reset()
        city='測'*60
        start=ipaddress.ip_address('11.22.0.0')
        def row(index):return f'{start+index}/32,US,US-IL,{city},\r\n'.encode()
        rows=[];size=0
        while size<980000:
            value=row(len(rows));rows.append(value);size+=len(value)
        old=b''.join(rows);new=old+row(len(rows))
        check(980000<=len(old)<len(new)<1000000,'near-limit synthetic feeds stay below CSV limit')
        state=self.directory/'large-unicode'
        check(self.cli(old,state)[0]==0,'near-limit Unicode first CLI publication')
        check(self.cli(new,state)[0]==0,'near-limit Unicode changed CLI publication')
        snapshot,doc=self.snapshot()
        check(doc['csv'].encode()==new and doc['previous_csv'].encode()==old,'large real database holds current and previous exact feeds')
        response=self.request('GET',STATE,account='publisher')
        check(response[0]==200 and len(response[2])>2000000,'large real state response exercises former 2 MB budget')
        headers={k.lower():v for k,v in response[1].items()}
        uploads=[value['bytes'] for value in self.proxy.request_sizes if value['method']=='PUT' and value['path']==FEED]
        statement_sizes=[int(line.split()[1]) for line in (self.control/'write-sizes.log').read_text().splitlines()]
        print('CAPACITY: '+json.dumps({'records':len(rows)+1,'csv_bytes':len(new),'upload_json_bytes':max(uploads),
            'state_json_bytes':len(response[2]),'largest_sql_bytes':max(statement_sizes),
            'database_max_allowed_packet':snapshot['max_allowed_packet'],
            'http_post_max_size':headers.get('x-geofeed-test-post-max'),
            'http_memory_limit':headers.get('x-geofeed-test-memory-limit')}),flush=True)
        check(max(uploads)>1000000 and max(statement_sizes)>len(new),'measured wrapping/SQL growth')
        prior= snapshot['raw'];writes=(self.control/'writes.log').read_bytes()
        backups={name:((state/name).read_bytes(),(state/name).stat().st_mtime_ns) for name in ('before.csv','last-good.csv')}
        result,status=self.cli(new,state)
        check(result==0 and status['changed'] is False and self.snapshot()[0]['raw']==prior,'large no-op keeps real database document')
        check((self.control/'writes.log').read_bytes()==writes,'large no-op makes zero geofeed SQL write attempts')
        for name,expected in backups.items():check(((state/name).read_bytes(),(state/name).stat().st_mtime_ns)==expected,'large no-op keeps recovery history')
        print('PASS: real WordPress near-limit Unicode first/change/no-op workload',flush=True)
        transport=JsonHTTP(max_bytes=2000000)
        transport.opener=build_opener(NoRedirects(),HTTPSHandler(context=self.context))
        limited=WordPress(self.url,'publisher',self.accounts['publisher'],http=transport)
        try:limited.state()
        except GeofeedError as exc:check('Response exceeds size limit' in str(exc),'old response budget fails at expected guard')
        else:raise AssertionError('2 MB state budget accepted larger real state response')
        check(self.snapshot()[0]['raw']==prior and (self.control/'writes.log').read_bytes()==writes,'small client budget cannot change stored feed')
        print('PASS: real WordPress old 2 MB state budget refuses large response without writes',flush=True)
        oversized=list(rows)+[row(len(rows))];total=len(new)
        while total<=1000000:
            value=row(len(oversized));oversized.append(value);total+=len(value)
        too_large=b''.join(oversized)
        check(len(too_large)>1000000 and len({line.split(b',')[0] for line in too_large.splitlines()})==len(oversized),'oversize control has unique canonical records')
        check(self.request('PUT',FEED,too_large,new,'publisher')[0]==400,'real REST refuses oversized otherwise-valid CSV')
        check(self.snapshot()[0]['raw']==prior and self.request('GET',FEED)[2]==new,'oversize upload preserves stored and public feeds')
        check((self.control/'writes.log').read_bytes()==writes,'oversize upload makes zero geofeed SQL write attempts')
        print('PASS: real WordPress oversize CSV refusal preserves large stored/public feed',flush=True)

    def steady_capacity_tests(self):
        for character,width in (('測',3),('\U0001f600',4)):
            city=character*60
            check(len(character.encode())==width,'capacity fixture UTF-8 width')
            start=ipaddress.ip_address('11.22.0.0')
            def row(index):return f'{start+index}/32,US,US-IL,{city},\r\n'.encode()
            rows=[];size=0
            while size<980000:
                value=row(len(rows));rows.append(value);size+=len(value)
            bodies=[b''.join(rows+[row(len(rows)+i) for i in range(extra)]) for extra in range(6)]
            check(all(980000<=len(body)<1000000 for body in bodies),'all steady capacity bodies near CSV limit')
            for version,policy in ((1,REJECT),(2,LONGEST_PREFIX)):
                self.reset()
                state=self.directory/f'steady-unicode-{width}-v{version}'
                feeds=[wrap_csv(body) if version==2 else body for body in bodies]
                path=FEED_V2 if version==2 else FEED
                if version==2:
                    admin=WordPress(self.url,'policy_admin',self.accounts['policy_admin'])
                    admin.http.opener=build_opener(NoRedirects(),HTTPSHandler(context=self.context))
                    admin.configure_policy(policy,admin.policy_state(),secrets.token_hex(16))
                stages=[]
                for index,feed in enumerate(feeds[:4]):
                    self.proxy.arm(None)
                    before_sizes=(self.control/'write-sizes.log').read_text().splitlines()
                    result,status=self.cli(feed,state,overlap_policy=policy)
                    check(result==0 and status['changed'] is True,'near-limit first and three changed CLI publications')
                    snapshot,doc=self.snapshot()
                    previous=feeds[index-1] if index else b''
                    check(doc['csv'].encode()==feed and doc['previous_csv'].encode()==previous,
                          'steady capacity stores exact current and previous feeds')
                    response=self.request('GET',STATE_V2 if version==2 else STATE,account='publisher')
                    check(response[0]==200 and json.loads(response[2])['csv'].encode()==feed,
                          'steady capacity authenticated state is readable')
                    sizes=(self.control/'write-sizes.log').read_text().splitlines()[len(before_sizes):]
                    uploads=[value['bytes'] for value in self.proxy.request_sizes if value['method']=='PUT' and value['path']==path]
                    check(len(sizes)==len(uploads)==1,'one SQL write and one HTTP PUT per changed capacity publication')
                    stages.append({'stage':index,'csv_bytes':len(feed),'upload_json_bytes':uploads[0],
                        'state_json_bytes':len(response[2]),'sql_bytes':int(sizes[0].split()[1])})
                check(stages[2]['sql_bytes']>stages[1]['sql_bytes']>stages[0]['sql_bytes'],
                      'populated conditional history really increases measured SQL')
                check(stages[2]['sql_bytes']>8*1024*1024,'steady Unicode SQL exceeds an 8 MiB packet budget')
                prior=snapshot['raw'];writes=(self.control/'writes.log').read_bytes()
                backups={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in state.iterdir() if p.name!='status.json'}
                self.proxy.arm(None)
                result,status=self.cli(feeds[3],state,overlap_policy=policy)
                check(result==0 and status['changed'] is False and self.snapshot()[0]['raw']==prior and
                      (self.control/'writes.log').read_bytes()==writes,'steady capacity no-op preserves database without SQL')
                check({p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in state.iterdir() if p.name!='status.json'}==backups,
                      'steady capacity no-op preserves all private recovery files and modification times')
                check(not any(value['method'] in ('PUT','DELETE') for value in self.proxy.request_sizes),
                      'steady capacity no-op makes no HTTP writes')
                self.proxy.arm('bad-readback')
                result,status=self.cli(feeds[4],state,overlap_policy=policy)
                restored=self.snapshot()[1]
                recovery_message='Previous feed and policy retained/restored' if version==2 else 'Previous feed retained/restored'
                check(result==1 and status['healthy'] is False and recovery_message in status['error'],
                      'near-limit failed read-back stays unhealthy after verified recovery')
                check(restored['csv'].encode()==feeds[3] and restored['previous_csv'].encode()==feeds[4] and
                      self.request('GET',FEED)[2]==feeds[3],'near-limit recovery restores exact stored/public baseline')
                check((state/'before.csv').read_bytes()==feeds[3] and (state/'last-good.csv').read_bytes()==feeds[3],
                      'near-limit recovery preserves exact private baseline')
                check(self.proxy.faults==['public-mismatch'],'near-limit public mismatch control actually fired')
                puts=[value for value in self.proxy.request_sizes if value['method']=='PUT' and value['path']==path]
                check(len(puts)==2,'near-limit failure makes one publish and one conditional restore, without blind retries')
                if version==2:
                    check(restored['overlap_policy']==restored['previous_overlap_policy']==LONGEST_PREFIX and
                          restored['required_overlap_policy']==LONGEST_PREFIX,'near-limit recovery preserves all policy fields')
                print('STEADY CAPACITY: '+json.dumps({'api_version':version,'unicode_utf8_bytes':width,
                    'records':len(rows)+3,'stages':stages,'database_max_allowed_packet':snapshot['max_allowed_packet'],
                    'no_op_http_writes':0,'no_op_sql_writes':0,'recovery_puts':len(puts),
                    'recovery_public_verified':True,'recovery_healthy':status['healthy']}),flush=True)
                print('PASS: real WordPress populated-history Unicode capacity and conditional recovery',flush=True)
                self.proxy.arm(None)
                self.packet_limit_test(feeds[4],feeds[3],state,policy,version,width)
                self.memory_limit_test(feeds[5],feeds[4],state,policy,version,width)

    def packet_limit_test(self, candidate, baseline, state, policy, version, width):
        check(DISPOSABLE,'packet failure workload is disposable-only')
        original=self.packet_budget();limit=8*1024*1024
        before,doc=self.snapshot()
        check(original>limit and len(before['raw'].encode())<limit,'baseline fits below smaller fixture budget')
        check(doc['csv'].encode()==baseline and self.request('GET',FEED)[2]==baseline,'exact baseline before packet control')
        path=FEED_V2 if version==2 else FEED
        state_path=STATE_V2 if version==2 else STATE
        flag=self.control/'packet-probe';flag.write_text('enabled')
        try:
            self.packet_budget(limit)
            response=self.request('GET',state_path,account='publisher')
            headers={key.lower():value for key,value in response[1].items()}
            check(response[0]==200 and int(headers.get('x-geofeed-test-max-packet','0'))==limit,
                  'real HTTP database session uses the lowered packet budget and reads the baseline')
            self.proxy.arm(None)
            count=len((self.control/'write-sizes.log').read_text().splitlines())
            result,status=self.cli(candidate,state,overlap_policy=policy)
            puts=[value for value in self.proxy.request_sizes if value['method'] in ('PUT','DELETE')]
            sizes=(self.control/'write-sizes.log').read_text().splitlines()[count:]
            print('PACKET ATTEMPT: '+json.dumps({'api_version':version,'unicode_utf8_bytes':width,
                'budget':limit,'exit_code':result,'healthy':status['healthy'],
                'origin_statuses':[value.get('origin_status') for value in puts],
                'origin_errors':[value.get('origin_error') for value in puts],
                'query_filter_calls':len(sizes)}),flush=True)
            check(result==1 and status['healthy'] is False and 'max_allowed_packet' in status['error'],
                  'real packet rejection stays unhealthy and gives safe database-size guidance')
            check(len(puts)==1 and puts[0]['path']==path and puts[0].get('origin_status')==503
                  and puts[0].get('session_packet_budget')==limit
                  and puts[0].get('origin_error')=='geofeed_db','one runner PUT receives real plugin database failure without HTTP retry')
            check(len(sizes)==1 and sizes[0].startswith('UPDATE '),'one failed call through the geofeed query filter')
            failed_size=int(sizes[0].split()[1])
            check(limit<failed_size<original,'actual prepared statement exceeds lowered budget and fits original budget')
            # Read-only diagnosis at the failing budget, before restoring the setting.
            check(self.packet_budget()==limit and self.snapshot()[0]['raw']==before['raw']
                  and self.request('GET',FEED)[2]==baseline,'packet failure preserves exact database/public baseline and history')
            check((state/'before.csv').read_bytes()==baseline and (state/'last-good.csv').read_bytes()==baseline,
                  'packet failure keeps the exact private recovery baseline')
            if version==2:
                metadata=json.loads((state/'before-policy.json').read_text())
                check(metadata['before_policy']==metadata['before_required_policy']==policy and
                      metadata['before_publication_id']==doc['publication_id'] and metadata['before_sha256']==digest(baseline),
                      'packet failure keeps private policy and owner recovery metadata')
            check(all(secret not in json.dumps(status) for secret in self.secrets),'packet status does not expose credentials')
        finally:
            # Restore even if a check fails; the whole runner is also disposable.
            self.packet_budget(original)
        check(self.packet_budget()==original and self.snapshot()[0]['raw']==before['raw']
              and self.request('GET',FEED)[2]==baseline,'restored budget is measured before an explicit new publication')
        self.proxy.arm(None)
        count=len((self.control/'write-sizes.log').read_text().splitlines())
        result,status=self.cli(candidate,state,overlap_policy=policy)
        after=self.snapshot()[1]
        puts=[value for value in self.proxy.request_sizes if value['method'] in ('PUT','DELETE')]
        sizes=(self.control/'write-sizes.log').read_text().splitlines()[count:]
        check(result==0 and status['healthy'] is True and status['changed'] is True,
              'same candidate succeeds after diagnosed packet budget is restored')
        check(len(puts)==len(sizes)==1 and puts[0]['path']==path and puts[0]['origin_status']==200
              and puts[0].get('session_packet_budget')==original,
              'explicit corrected-budget publication has one successful PUT and query-filter call')
        check(int(sizes[0].split()[1])==failed_size,'positive control executes the same-sized prepared statement')
        check(after['csv'].encode()==candidate and after['previous_csv'].encode()==baseline
              and self.request('GET',FEED)[2]==candidate,'corrected budget verifies exact current, history and public bytes')
        check((state/'before.csv').read_bytes()==baseline and (state/'last-good.csv').read_bytes()==candidate,
              'corrected budget records verified private recovery history')
        if version==2:
            check(after['overlap_policy']==after['previous_overlap_policy']==after['required_overlap_policy']==policy,
                  'corrected budget preserves all policy fields')
        print('PACKET LIMIT OBSERVATION: '+json.dumps({'api_version':version,'unicode_utf8_bytes':width,
            'low_budget_bytes':limit,'restored_budget_bytes':original,'prepared_sql_bytes':failed_size,
            'failed_http_status':503,'failed_plugin_code':'geofeed_db','failure_healthy':False,
            'failed_http_session_budget':limit,'corrected_http_session_budget':puts[0]['session_packet_budget'],
            'failure_runner_puts':1,'failure_query_filter_calls':1,'raw_driver_attempts':'not_measured',
            'baseline_preserved':True,'same_candidate_after_correction_healthy':status['healthy'],
            'corrected_runner_puts':len(puts),'corrected_query_filter_calls':len(sizes)}),flush=True)
        print('PASS: real WordPress packet-limit refusal preserves baseline and same-candidate correction succeeds',flush=True)
        flag.unlink(missing_ok=True)

    def memory_observations(self):
        path=self.control/'memory-observations.log'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def memory_small_tests(self):
        check(DISPOSABLE,'memory controls require the disposable runner')
        flag=self.control/'memory-probe'
        try:
            for version,policy in ((1,REJECT),(2,LONGEST_PREFIX)):
                self.reset();flag.unlink(missing_ok=True)
                state=self.directory/f'memory-small-v{version}'
                if version==2:
                    admin=WordPress(self.url,'policy_admin',self.accounts['policy_admin'])
                    admin.http.opener=build_opener(NoRedirects(),HTTPSHandler(context=self.context))
                    admin.configure_policy(policy,admin.policy_state(),secrets.token_hex(16))
                before=wrap_csv(A) if version==2 else A
                candidate=wrap_csv(B) if version==2 else B
                check(self.cli(before,state,overlap_policy=policy)[0]==0,'small memory-control baseline')
                flag.write_text('64M');self.proxy.arm(None)
                count=len(self.memory_observations())
                result,status=self.cli(candidate,state,overlap_policy=policy)
                observations=self.memory_observations()[count:]
                puts=[value for value in self.proxy.request_sizes if value['method']=='PUT']
                print('MEMORY SMALL ATTEMPT: '+json.dumps({'api_version':version,'exit_code':result,
                    'healthy':status['healthy'],'origin_statuses':[value.get('origin_status') for value in puts],
                    'php_observations':observations}),flush=True)
                check(result==0 and status['healthy'] is True and status['changed'] is True,
                      'small real CLI publication works at the low memory budget')
                check(len(observations)==len(puts)==1 and puts[0]['origin_status']==200
                      and observations[0]['api_version']==version and observations[0]['memory_limit']=='64M'
                      and observations[0]['oom'] is False and observations[0]['peak_allocated_bytes']>0,
                      'low-budget positive control really executes with finite memory and no OOM')
                check(self.snapshot()[1]['csv'].encode()==candidate and self.request('GET',FEED)[2]==candidate,
                      'low-budget small control verifies actual stored and public workload')
                print('MEMORY SMALL OBSERVATION: '+json.dumps(observations[0]),flush=True)
        finally:flag.unlink(missing_ok=True)

    def memory_limit_test(self, candidate, baseline, state, policy, version, width):
        check(DISPOSABLE,'memory failure controls require the disposable runner')
        flag=self.control/'memory-probe'
        before,doc=self.snapshot()
        check(doc['csv'].encode()==baseline and self.request('GET',FEED)[2]==baseline,'exact baseline before memory control')
        path=FEED_V2 if version==2 else FEED
        try:
            flag.write_text('64M');self.proxy.arm(None)
            count=len(self.memory_observations())
            writes=len((self.control/'write-sizes.log').read_text().splitlines())
            result,status=self.cli(candidate,state,overlap_policy=policy)
            observations=self.memory_observations()[count:]
            puts=[value for value in self.proxy.request_sizes if value['method'] in ('PUT','DELETE')]
            query_calls=len((self.control/'write-sizes.log').read_text().splitlines())-writes
            print('MEMORY ATTEMPT: '+json.dumps({'api_version':version,'unicode_utf8_bytes':width,
                'exit_code':result,'healthy':status['healthy'],'origin_statuses':[value.get('origin_status') for value in puts],
                'query_filter_calls':query_calls,'php_observations':observations}),flush=True)
            check(result==1 and status['healthy'] is False,'real PHP exhaustion leaves runner unhealthy')
            check(len(puts)==1 and puts[0]['path']==path and puts[0].get('origin_status') in (500,503),
                  'real memory failure makes one runner PUT without an HTTP retry')
            check(len(observations)==1 and observations[0]['api_version']==version
                  and observations[0]['memory_limit']=='64M' and observations[0]['oom'] is True
                  and observations[0]['peak_allocated_bytes']>0,
                  'PHP shutdown metadata proves actual memory exhaustion, not a simulated 500')
            failed=observations[0];failed_http=puts[0]['origin_status']
            # Diagnose with normal-budget GETs before correcting the PUT budget.
            check(self.snapshot()[0]['raw']==before['raw'] and self.request('GET',FEED)[2]==baseline,
                  'real memory exhaustion preserves exact stored/public baseline and history')
            check((state/'before.csv').read_bytes()==baseline and (state/'last-good.csv').read_bytes()==baseline,
                  'memory failure keeps private CSV recovery baseline')
            if version==2:
                metadata=json.loads((state/'before-policy.json').read_text())
                check(metadata['before_policy']==metadata['before_required_policy']==policy
                      and metadata['before_publication_id']==doc['publication_id'] and metadata['before_sha256']==digest(baseline),
                      'memory failure keeps private baseline policy and owner metadata')
            check(all(secret not in json.dumps(status) for secret in self.secrets),'memory status does not expose credentials')
        finally:flag.write_text('256M')
        check(flag.read_text()=='256M' and self.snapshot()[0]['raw']==before['raw']
              and self.request('GET',FEED)[2]==baseline,'corrected fixture budget and unchanged baseline checked before new publication')
        self.proxy.arm(None);count=len(self.memory_observations())
        result,status=self.cli(candidate,state,overlap_policy=policy)
        observations=self.memory_observations()[count:]
        puts=[value for value in self.proxy.request_sizes if value['method'] in ('PUT','DELETE')]
        after=self.snapshot()[1]
        check(result==0 and status['healthy'] is True and status['changed'] is True,
              'same candidate succeeds at corrected finite memory budget')
        check(len(observations)==len(puts)==1 and puts[0]['origin_status']==200
              and puts[0].get('php_memory_limit')=='256M' and observations[0]['memory_limit']=='256M'
              and observations[0]['oom'] is False and observations[0]['peak_allocated_bytes']>0,
              'corrected real PUT reports finite memory and an observed peak without exhaustion')
        check(after['csv'].encode()==candidate and after['previous_csv'].encode()==baseline
              and self.request('GET',FEED)[2]==candidate,'corrected finite-budget publication verifies exact current/history/public bytes')
        check((state/'before.csv').read_bytes()==baseline and (state/'last-good.csv').read_bytes()==candidate,
              'corrected finite-budget run records verified private history')
        if version==2:
            check(after['overlap_policy']==after['previous_overlap_policy']==after['required_overlap_policy']==policy,
                  'corrected finite-memory run preserves all policy fields')
        print('MEMORY LIMIT OBSERVATION: '+json.dumps({'api_version':version,'unicode_utf8_bytes':width,
            'low_memory_limit':failed['memory_limit'],'failed_peak_allocated_bytes':failed['peak_allocated_bytes'],
            'failed_hard_limit_percent':failed['hard_limit_percent'],
            'actual_php_oom':failed['oom'],'failed_http_status':failed_http,'failure_healthy':False,'failure_runner_puts':1,
            'failure_query_filter_calls':query_calls,'baseline_preserved':True,
            'corrected_memory_limit':observations[0]['memory_limit'],'corrected_peak_allocated_bytes':observations[0]['peak_allocated_bytes'],
            'corrected_hard_limit_percent':observations[0]['hard_limit_percent'],
            'corrected_oom':observations[0]['oom'],'same_candidate_after_correction_healthy':status['healthy'],
            'corrected_runner_puts':len(puts)}),flush=True)
        print('PASS: real WordPress PHP exhaustion preserves baseline and same-candidate finite-memory correction succeeds',flush=True)
        flag.unlink(missing_ok=True)

    def after_commit_oom_tests(self):
        check(DISPOSABLE,'after-commit memory tests require the disposable runner')
        check(not (self.control/'memory-probe').exists(),'previous memory controls were removed')
        for version in (1,2):
            convert=wrap_csv if version==2 else lambda value:value
            for scenario in ('recover','publisher-inspection','publisher-restore'):
                self.after_commit_oom_case(version,convert(A),convert(B),convert(C),'small',scenario)
            if version==2:
                for scenario in ('admin-inspection','admin-restore'):
                    self.after_commit_oom_case(version,convert(A),convert(B),convert(C),'small',scenario)
        city='\U0001f600'*60;start=ipaddress.ip_address('11.22.0.0');rows=[];size=0
        def row(index):return f'{start+index}/32,US,US-IL,{city},\r\n'.encode()
        while size<980000:
            value=row(len(rows));rows.append(value);size+=len(value)
        first=b''.join(rows);second=first+row(len(rows))
        check(980000<=len(first)<len(second)<1000000,'after-commit Unicode candidates stay near the CSV limit')
        for version in (1,2):
            convert=wrap_csv if version==2 else lambda value:value
            self.after_commit_oom_case(version,convert(first),convert(second),None,'near-limit','recover')
        print('PASS: real WordPress after-commit OOM recovery and competing-owner protection',flush=True)

    def after_commit_oom_case(self, version, first, candidate, winner, size_label, scenario):
        check(DISPOSABLE,'after-commit memory cases require the disposable runner')
        policy=LONGEST_PREFIX if version==2 else REJECT
        path=FEED_V2 if version==2 else FEED
        flag=self.control/'after-commit-oom';proof_path=self.control/'after-commit-oom.log'
        flag.unlink(missing_ok=True);self.reset()
        if version==2:
            admin=WordPress(self.url,'policy_admin',self.accounts['policy_admin'])
            admin.http.opener=build_opener(NoRedirects(),HTTPSHandler(context=self.context))
            admin.configure_policy(policy,admin.policy_state(),secrets.token_hex(16))
        state=self.directory/f'after-commit-{version}-{size_label}-{scenario}'
        check(self.cli(first,state,overlap_policy=policy)[0]==0,'verified normal baseline before after-commit fault')
        before=self.snapshot()[1]
        last_good=((state/'last-good.csv').read_bytes(),(state/'last-good.csv').stat().st_mtime_ns)
        proof_count=len(proof_path.read_text().splitlines()) if proof_path.exists() else 0
        memory_count=len(self.memory_observations())
        query_count=len((self.control/'write-sizes.log').read_text().splitlines())
        nonce=secrets.token_hex(16);seen={}

        def inject_winner():
            current=seen['committed_doc'];identity=secrets.token_hex(16)
            if scenario.startswith('admin-'):
                payload={'protocol_version':2,'required_overlap_policy':REJECT,'expected_sha256':digest(candidate),
                    'expected_overlap_policy':policy,'expected_required_overlap_policy':policy,
                    'expected_publication_id':current['publication_id'],'publication_id':identity}
                endpoint=POLICY_V2;headers=self.proxy.policy_admin_headers
            elif version==2:
                payload={'protocol_version':2,'csv':winner.decode(),'overlap_policy':policy,'operation':'publish',
                    'expected_sha256':digest(candidate),'expected_overlap_policy':policy,
                    'expected_required_overlap_policy':policy,'expected_publication_id':current['publication_id'],
                    'publication_id':identity}
                endpoint=FEED_V2;headers=self.proxy.publisher_headers
            else:
                payload={'csv':winner.decode(),'expected_sha256':digest(candidate)}
                endpoint=FEED;headers=self.proxy.publisher_headers
            response=self.proxy.forward('PUT',endpoint,json.dumps(payload).encode(),{**headers,'Content-Type':'application/json'})
            check(response[0]==200,'real competing writer/admin commit after original OOM')
            snapshot,doc=self.snapshot();seen['winner_raw']=snapshot['raw'];seen['winner_doc']=doc
            check(doc['csv'].encode()==(candidate if scenario.startswith('admin-') else winner),'real competing actor stores intended exact bytes')
            if version==2:check(doc['publication_id']==identity,'competing actor has a new real publication identity')
            if scenario.startswith('admin-'):
                check(doc['required_overlap_policy']==REJECT and doc['overlap_policy']==policy,
                      'administrative winner changes policy/owner while preserving identical candidate bytes')
            self.proxy.faults.append('competing-'+scenario)

        def capture_commit(endpoint,payload):
            check(endpoint==path and payload['csv'].encode()==candidate,'actual failed response belongs to intended publication')
            proofs=[json.loads(line) for line in proof_path.read_text().splitlines()[proof_count:]]
            memories=self.memory_observations()[memory_count:]
            check(len(proofs)==len(memories)==1,'exactly one consumed fault and one PHP shutdown record before response')
            proof=proofs[0];memory=memories[0];snapshot,doc=self.snapshot()
            check(proof['nonce']==nonce and proof['one_shot_consumed'] is True and not flag.exists(),
                  'one-shot fault was consumed before exhaustion')
            check(proof['api_version']==version and proof['sha256']==digest(candidate)
                  and proof['previous_sha256']==digest(first) and doc['csv'].encode()==candidate
                  and doc['previous_csv'].encode()==first,'candidate and history really committed before OOM and before runner inspection')
            check(proof['publication_id']==doc.get('publication_id') and proof['overlap_policy']==policy
                  and proof['previous_overlap_policy']==policy and proof['required_overlap_policy']==policy,
                  'commit proof binds actual server policy and publication identity')
            if version==2:check(proof['publication_id']==payload['publication_id'],'server committed the runner candidate identity')
            check(memory['api_version']==version and memory['oom'] is True
                  and int(memory['memory_limit'])==proof['oom_limit_bytes']
                  and 0<proof['allocated_before_fault_bytes']<proof['oom_limit_bytes']<=192*1024*1024,
                  'real PHP fatal follows a measured bounded limit above current allocation')
            seen.update(proof=proof,memory=memory,committed_doc=doc,committed_raw=snapshot['raw'])
            if scenario.endswith('-inspection'):inject_winner()
            elif scenario.endswith('-restore'):
                def before_restore(endpoint,payload):
                    check(endpoint==path and payload['csv'].encode()==first and payload['expected_sha256']==digest(candidate),
                          'injection occurs before a justified restore, never a blind publication retry')
                    if version==2:check(payload['operation']=='restore','v2 recovery uses the restore operation')
                    inject_winner()
                self.proxy.before_restore=before_restore

        self.proxy.after_oom=capture_commit;self.proxy.arm('after-commit-oom')
        flag.write_text(json.dumps({'nonce':nonce,'api_version':version,'candidate_sha256':digest(candidate),'before_sha256':digest(first)}))
        try:
            result,status=self.cli(candidate,state,overlap_policy=policy)
            check(result==1 and status['healthy'] is False and '500' in status['error'],
                  'actual after-commit HTTP 500 keeps the publication unhealthy')
            check('proof' in seen and self.proxy.faults[0]=='after-commit-oom-inspected',
                  'real candidate was inspected before the failed response reached the runner')
            puts=[value for value in self.proxy.request_sizes if value['method'] in ('PUT','DELETE')]
            statuses=[value.get('origin_status') for value in puts]
            expected=[500,200] if scenario=='recover' else [500,409] if scenario.endswith('-restore') else [500]
            check(statuses==expected and all(value['path']==path for value in puts),
                  'one failed publication and only the justified conditional restore; no blind retries')
            check(len((self.control/'write-sizes.log').read_text().splitlines())-query_count==2,
                  'only candidate plus restore or competing actor reaches the query filter')
            snapshot,doc=self.snapshot()
            if scenario=='recover':
                check(doc['csv'].encode()==first and doc['previous_csv'].encode()==candidate
                      and self.request('GET',FEED)[2]==first and 'retained/restored' in status['error'],
                      'real after-commit crash conditionally restores exact stored/public baseline and history')
                if version==2:
                    check(doc['overlap_policy']==doc['previous_overlap_policy']==doc['required_overlap_policy']==policy
                          and doc['publication_id']!=seen['proof']['publication_id'],'restore owns a fresh policy-bound identity')
            else:
                check(snapshot['raw']==seen['winner_raw'] and self.request('GET',FEED)[2]==seen['winner_doc']['csv'].encode()
                      and 'Recovery needs attention' in status['error'],'other actor state stays byte-exact and recovery stops')
                check(self.proxy.before_restore is None,'restore-race injection actually ran when requested')
            check((state/'before.csv').read_bytes()==first
                  and ((state/'last-good.csv').read_bytes(),(state/'last-good.csv').stat().st_mtime_ns)==last_good,
                  'failed after-commit run preserves private baseline and last-good modification time')
            if version==2:
                metadata=json.loads((state/'before-policy.json').read_text())
                check(metadata['before_publication_id']==before['publication_id'] and metadata['before_sha256']==digest(first)
                      and metadata['candidate_publication_id']==seen['proof']['publication_id'],
                      'private recovery metadata binds original baseline and failed candidate owner')
            check(len(proof_path.read_text().splitlines())-proof_count==1 and not flag.exists(),
                  'restore and competing writes do not fire the consumed fault again')
            if scenario=='recover':
                normal_count=len(self.memory_observations());self.proxy.arm(None)
                normal,normal_status=self.cli(candidate,state,overlap_policy=policy)
                observed=self.memory_observations()[normal_count:];after=self.snapshot()[1]
                check(normal==0 and normal_status['healthy'] is True and normal_status['changed'] is True
                      and len(observed)==1 and observed[0]['oom'] is False and observed[0]['memory_limit']=='256M'
                      and after['csv'].encode()==candidate and after['previous_csv'].encode()==first
                      and self.request('GET',FEED)[2]==candidate,'same candidate passes normally after fault removal and verified recovery')
            print('AFTER COMMIT OOM OBSERVATION: '+json.dumps({'api_version':version,'size':size_label,'scenario':scenario,
                'candidate_bytes':len(candidate),'commit_sha256':seen['proof']['sha256'],
                'commit_publication_id':seen['proof']['publication_id'],'allocated_before_fault_bytes':seen['proof']['allocated_before_fault_bytes'],
                'peak_before_fault_bytes':seen['proof']['peak_before_fault_bytes'],'oom_limit_bytes':seen['proof']['oom_limit_bytes'],
                'fatal_peak_allocated_bytes':seen['memory']['peak_allocated_bytes'],'actual_php_oom':True,
                'one_shot_consumed':True,'runner_http_statuses':statuses,'failure_healthy':status['healthy'],
                'query_filter_calls':2,'baseline_restored':scenario=='recover','competing_actor_preserved':scenario!='recover',
                'same_candidate_normal_verified':scenario=='recover'}),flush=True)
        finally:
            flag.unlink(missing_ok=True);self.proxy.after_oom=None;self.proxy.before_restore=None;self.proxy.arm(None)

    def close(self):
        (self.control/'packet-probe').unlink(missing_ok=True)
        (self.control/'memory-probe').unlink(missing_ok=True)
        (self.control/'after-commit-oom').unlink(missing_ok=True)
        if self.server:
            try:os.killpg(self.server.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            try:self.server.wait(timeout=10)
            except subprocess.TimeoutExpired:os.killpg(self.server.pid,signal.SIGKILL);self.server.wait(timeout=5)
        if hasattr(self,'thread'):self.proxy.shutdown();self.thread.join(timeout=5)
        self.proxy.server_close();self.log.close()
        if self.database_created:
            self.sql(f"DROP DATABASE `{self.db}`; DROP USER '{self.user}'@'localhost';")


def run():
    check(DISPOSABLE,'requires disposable GitHub-hosted Linux runner; not measured elsewhere')
    for program in ('php','mariadb','openssl','sudo'):check(shutil.which(program),'missing prerequisite: '+program)
    with tempfile.TemporaryDirectory(prefix='geofeed-wordpress-',dir=os.environ['RUNNER_TEMP']) as directory:
        workload=Workload(Path(directory))
        try:
            workload.start();workload.race_tests();workload.publication_tests();workload.https_guard_tests();workload.memory_small_tests();workload.capacity_tests();workload.steady_capacity_tests();workload.nested_policy_tests();workload.delivery_hook_tests();workload.cache_inspection_tests();workload.after_commit_oom_tests()
            print('PASS: real WordPress database/auth/TLS/concurrency/recovery integration',flush=True)
        finally:workload.close()


if __name__=='__main__':run()
