"""Real disposable WordPress/MariaDB/TLS workload. Never targets an existing site."""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
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
from urllib.request import urlopen
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
import contextlib
import yaml

FEED = '/wp-json/isp-geofeed-generator/v1/feed'
STATE = '/wp-json/isp-geofeed-generator/v1/state'
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
        self.publisher_headers = {}
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        self.socket = context.wrap_socket(self.socket, server_side=True)

    def arm(self, mode):
        with self.lock:
            self.mode, self.pending, self.faults = mode, False, []

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
            mode = proxy.mode
            if mode == 'failed-recovery' and proxy.pending and self.command in ('PUT', 'DELETE'):
                proxy.mode = None; proxy.faults.append('recovery-refused')
                self.send_error(503); return
        status, headers, data = proxy.forward(self.command, self.path, body, dict(self.headers))
        with proxy.lock:
            mode = proxy.mode
            if self.command == 'GET' and self.path == FEED and mode == 'preflight-mismatch':
                proxy.mode = None; proxy.faults.append('preflight-mismatch'); data = C
            elif self.command == 'PUT' and self.path == FEED and status == 200 and mode:
                proxy.pending = True
                if mode == 'lost-reply':
                    proxy.mode = None; proxy.faults.append('reply-dropped')
                    self.close_connection = True
                    return
            elif self.command == 'GET' and self.path == FEED and proxy.pending and mode in ('bad-readback', 'winner', 'failed-recovery'):
                if mode != 'failed-recovery': proxy.mode = None
                proxy.faults.append('public-mismatch')
                if mode == 'winner':
                    winner = json.dumps({'csv':C.decode(), 'expected_sha256':digest(B)}).encode()
                    result = proxy.forward('PUT', FEED, winner, {**proxy.publisher_headers, 'Content-Type':'application/json'})
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
        self.server = subprocess.Popen(['php','-d','opcache.enable=0','-d','opcache.enable_cli=0','-S',f'127.0.0.1:{self.backend}',
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

    def cli(self, csv, state):
        inventory=self.directory/'inventory.json'
        pools=[]
        for i,line in enumerate(csv.decode().splitlines()):
            prefix=line.split(',')[0]
            pools.append({'id':str(i+1),'ip_range':prefix,'subnet':{'subnet':prefix},'site_id':'1'})
        inventory.write_text(json.dumps({'pools':pools,'sites':[{'id':'1','addresses':[{'id':'1','country':'US','subdivision':'US_IL','city':'Example City'}]}]}))
        config={'source':{'type':'local_json','input_path':str(inventory),'allow_initial':True},
            'extensions':{'sources':['local_json']},'credentials':{'WP_APP_PASSWORD':'env:WP_APP_PASSWORD'},
            'allowed_prefixes':['11.22.0.0/16','2001:4860:1234::/48'],'bogons':bogon_files(self.directory),
            'state_dir':str(state),'publish':{'type':'wordpress'}}
        path=self.directory/'config.yaml';path.write_text(yaml.safe_dump(config))
        previous={name:os.environ.get(name) for name in ('WP_SITE_URL','WP_USERNAME','WP_APP_PASSWORD','SSL_CERT_FILE')}
        os.environ.update({'WP_SITE_URL':self.url,'WP_USERNAME':'publisher','WP_APP_PASSWORD':self.accounts['publisher'],
            'SSL_CERT_FILE':self.environment['SSL_CERT_FILE']})
        try:
            with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                result=main(['publish','--config',str(path)])
        finally:
            for name,value in previous.items():
                if value is None:os.environ.pop(name,None)
                else:os.environ[name]=value
        status=json.loads((state/'status.json').read_text())['data']
        check(status.get('healthy')==(result==0),'CLI health is present and matches actual result')
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

    def close(self):
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
            workload.start();workload.race_tests();workload.publication_tests()
            print('PASS: real WordPress database/auth/TLS/concurrency/recovery integration',flush=True)
        finally:workload.close()


if __name__=='__main__':run()
