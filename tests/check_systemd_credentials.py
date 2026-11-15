"""Root-only synthetic tests on a disposable Linux systemd host. No production keys."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import stat
import subprocess
import tempfile
import uuid


def run(args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, timeout=60, **kwargs)
    if result.returncode:
        # Workloads contain only synthetic data; never include arbitrary host logs.
        raise RuntimeError(f'Test command failed ({Path(args[0]).name}): {result.stderr[-1500:]} {result.stdout[-1500:]}')
    return result.stdout


def main():
    if os.geteuid() != 0 or not Path('/run/systemd/system').is_dir():
        raise RuntimeError('NOT MEASURED: requires root on a disposable host running systemd')
    for binary in ('systemd-run', 'systemd-creds', 'setfacl', 'runuser'):
        if not shutil.which(binary):
            raise RuntimeError('NOT MEASURED: missing '+binary)
    uid = pwd.getpwnam('nobody').pw_uid
    version = run(['systemd', '--version']).splitlines()[0]
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='isp-geofeed-systemd-') as tmp:
        stage = Path(tmp); stage.chmod(0o755)
        shutil.copytree(root/'isp_geofeed_generator', stage/'isp_geofeed_generator', ignore=shutil.ignore_patterns('__pycache__'))
        for item in (stage/'isp_geofeed_generator').rglob('*'):
            item.chmod(0o755 if item.is_dir() else 0o644)
        secret = 'synthetic-systemd-fixture-only'
        plain = stage/'input'; plain.write_text(secret); plain.chmod(0o400)
        expected = hashlib.sha256(secret.encode()).hexdigest()
        worker = stage/'worker.py'
        worker.write_text('''import hashlib,json,os,stat,sys
from pathlib import Path
from isp_geofeed_generator.credentials import CredentialStore,protected_file
from isp_geofeed_generator.client import GeofeedError
expected=sys.argv[1]
path=Path(os.environ['CREDENTIALS_DIRECTORY'])/'SONAR_API_TOKEN'
info=path.stat()
legacy_rejected=False
try: protected_file(path)
except GeofeedError: legacy_rejected=True
value=CredentialStore({'SONAR_API_TOKEN':'systemd:SONAR_API_TOKEN'}).get('SONAR_API_TOKEN')
assert hashlib.sha256(value.encode()).hexdigest()==expected
if info.st_uid==0 and info.st_mode & stat.S_IRGRP: assert legacy_rejected
print(json.dumps({'service_uid':os.getuid(),'root_owned':info.st_uid==0,'mode':oct(stat.S_IMODE(info.st_mode)),
                  'ordinary_file_guard_rejected':legacy_rejected,'credential_value_verified':True}))
'''); worker.chmod(0o644)
        # Reproduce the exact ACL layout independently of manager version/fallback.
        fixture = stage/'acl-fixture'; fixture.write_text(secret); fixture.chmod(0o400)
        run(['setfacl', '-m', f'u:{uid}:r', str(fixture)])
        direct = stage/'direct.py'
        direct.write_text('''import os,sys
from pathlib import Path
from isp_geofeed_generator.credentials import protected_file
from isp_geofeed_generator.client import GeofeedError
path=Path(sys.argv[1]); allowed=sys.argv[2]=='allow'
try: protected_file(path)
except GeofeedError: pass
else: raise AssertionError('Ordinary file guard unexpectedly accepted root ACL fixture')
try: value=protected_file(path,systemd=True)
except GeofeedError:
    assert not allowed
else:
    assert allowed and value=='synthetic-systemd-fixture-only'
print('PASS: protected-file ACL control '+sys.argv[2])
'''); direct.chmod(0o644)
        def check_fixture(allow):
            print(run(['runuser', '-u', 'nobody', '--', '/usr/bin/python3', str(direct), str(fixture), 'allow' if allow else 'deny']).strip())
        check_fixture(True)
        run(['setfacl', '-m', 'g::r', str(fixture)]); check_fixture(False)
        run(['setfacl', '-m', 'g::---', str(fixture)])
        other = pwd.getpwnam('daemon').pw_uid
        run(['setfacl', '-m', f'u:{other}:r', str(fixture)]); check_fixture(False)
        run(['setfacl', '-x', f'u:{other}', str(fixture)])
        fixture.chmod(0o444); check_fixture(False)
        # Genuine services, unencrypted and encrypted, with a different UID from PID 1.
        encrypted = stage/'encrypted'
        run(['systemd-creds', 'encrypt', '--with-key=host', '--name=SONAR_API_TOKEN', str(plain), str(encrypted)])
        for directive, path in [('LoadCredential', plain), ('LoadCredentialEncrypted', encrypted)]:
            unit = 'isp-geofeed-credential-test-'+uuid.uuid4().hex
            output = run(['systemd-run', '--quiet', '--wait', '--pipe', '--collect', '--unit='+unit,
                          '--property=User=nobody', '--property=NoNewPrivileges=yes',
                          '--property='+directive+'=SONAR_API_TOKEN:'+str(path),
                          '/usr/bin/python3', str(worker), expected])
            result = json.loads(output)
            assert result['service_uid'] == uid and result['credential_value_verified']
            print(json.dumps({'directive': directive, **result}))
        print(json.dumps({'systemd': version, 'root_service_workloads': 2, 'acl_negative_controls': 3}))
        print('PASS: real systemd plain/encrypted service credentials and strict file/ACL controls')


if __name__ == '__main__':
    main()
