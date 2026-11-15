import pathlib
import subprocess

root = pathlib.Path(__file__).resolve().parents[1]
plan = subprocess.check_output(['bash', str(root / 'deploy-update.sh'), '--dry-run'], text=True)
actual = {line.split(' -> ')[0].split(' ', 3)[3] for line in plan.splitlines() if line.startswith('INSTALL ')}
expected = {str(p) for p in (root / 'isp_geofeed_generator').rglob('*.py')}
expected |= {str(p) for p in (root / 'tools').rglob('*.py')}
expected |= {str(root / 'requirements.txt')}
expected |= {str(p) for p in (root / 'systemd').iterdir() if p.suffix in ('.service', '.timer', '.slice')}
assert actual == expected, f'Deploy coverage differs: missing={expected-actual}, extra={actual-expected}'
assert 10 <= len(plan.splitlines()) <= 60
assert not any('/.venv/' in p or '/tests/' in p for p in actual)
print('PASS: portable deployment coverage')
