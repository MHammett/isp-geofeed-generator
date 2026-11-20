"""Prove restore tests detect removed guards using only private code copies."""
import argparse
import inspect
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]


def python_controls():
    import test_wordpress_policy as cases
    from isp_geofeed_generator import wordpress_policy as policy

    name = 'test_restore_checks_history_even_when_current_bytes_policy_and_id_match'

    def run():
        output = io.StringIO()
        result = unittest.TextTestRunner(stream=output).run(cases.WordPressPolicyTests(name))
        assert result.testsRun == 1, output.getvalue()
        return result, output.getvalue()

    result, output = run()
    assert result.wasSuccessful(), output
    original = inspect.getsource(policy.restore)
    for guard in ('restored.previous!=current.csv', 'restored.previous_policy!=current.policy'):
        assert original.count(guard) == 1, 'Python guard changed; inspect mutation target'
        namespace = dict(vars(policy))
        exec(compile(original.replace(guard, 'False'), '<restore-control-mutation>', 'exec'), namespace)
        with patch.object(cases, 'restore', namespace['restore']):
            result, output = run()
        assert not result.errors and len(result.failures) == 1, output
        assert 'GeofeedError not raised' in result.failures[0][1], output
        print('RESTORE MUTATION OBSERVATION: ' + json.dumps({
            'language': 'python', 'guard': guard, 'assertion_failures': 1, 'errors': 0}))
    result, output = run()
    assert result.wasSuccessful(), output
    print('PASS: Python restore history controls detect both removed guards without changing runtime code')


def php_controls(php):
    relative = Path('wordpress/isp-geofeed-generator/isp-geofeed-generator.php')
    original = (ROOT / relative).read_bytes()
    with tempfile.TemporaryDirectory(prefix='geofeed-restore-controls-') as directory:
        stage = Path(directory)
        shutil.copytree(ROOT / 'wordpress/isp-geofeed-generator', stage / 'wordpress/isp-geofeed-generator')
        (stage / 'tests/fixtures').mkdir(parents=True)
        for name in ('test_wordpress.php', 'test_wordpress_v2.php', 'test_wordpress_delivery.php'):
            shutil.copyfile(ROOT / 'tests' / name, stage / 'tests' / name)
        shutil.copytree(ROOT / 'examples/wordpress-delivery-hook', stage / 'examples/wordpress-delivery-hook')
        for name in ('conformance.json', 'special-prefixes.json'):
            shutil.copyfile(ROOT / 'tests/fixtures' / name, stage / 'tests/fixtures' / name)

        def run():
            return subprocess.run([php, 'tests/test_wordpress_v2.php'], cwd=stage,
                                  capture_output=True, text=True, timeout=30)

        result = run()
        assert result.returncode == 0 and 'offline WordPress policy-v2 checks' in result.stdout, result.stdout + result.stderr
        for guard, label in (
            (b"$csv !== $before['previous_csv']", 'restore refuses different bytes with matching prior policy'),
            (b"$policy !== $before['previous_overlap_policy']", 'restore refuses matching empty bytes with wrong prior policy'),
        ):
            assert original.count(guard) == 1, 'PHP guard changed; inspect mutation target'
            (stage / relative).write_bytes(original.replace(guard, b'false'))
            result = run()
            assert result.returncode == 1 and result.stderr.strip() == 'FAIL: ' + label, result.stdout + result.stderr
            print('RESTORE MUTATION OBSERVATION: ' + json.dumps({
                'language': 'php', 'guard': guard.decode(), 'exit_code': result.returncode, 'failed_check': label}))
        (stage / relative).write_bytes(original)
        result = run()
        assert result.returncode == 0, result.stdout + result.stderr
        def delivery():
            return subprocess.run([php, 'tests/test_wordpress_delivery.php'], cwd=stage,
                                  capture_output=True, text=True, timeout=30)
        result = delivery()
        assert result.returncode == 0, result.stdout + result.stderr
        unchanged = b"if ($before['csv'] === $csv) { return true; }"
        assert original.count(unchanged) == 1, 'Delivery guard changed; inspect mutation target'
        (stage / relative).write_bytes(original.replace(unchanged, b'if (false) { return true; }'))
        result = delivery()
        assert result.returncode == 1 and result.stderr.strip() == 'FAIL: empty-feed policy flip commits without delivery notification', result.stdout + result.stderr
        print('DELIVERY SKIP MUTATION OBSERVATION: ' + json.dumps({'exit_code': result.returncode,
              'failed_check': 'empty-feed policy flip commits without delivery notification'}))
        (stage / relative).write_bytes(original)
        result = delivery()
        assert result.returncode == 0, result.stdout + result.stderr
    assert (ROOT / relative).read_bytes() == original, 'Checkout plugin unexpectedly changed'
    print('PASS: PHP restore baseline controls detect both removed guards without changing checkout')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-php', action='store_true')
    args = parser.parse_args()
    python_controls()
    php = shutil.which('php')
    if php:
        php_controls(php)
    else:
        print('PHP restore controls NOT MEASURED: PHP CLI is unavailable')
        if args.require_php:
            raise SystemExit(1)
