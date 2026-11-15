"""CI smoke check using installed wheels, outside the source checkout."""
import os
import subprocess
import sys
import tempfile

code = '''from pathlib import Path
import sys
import isp_geofeed_generator
from isp_geofeed_generator.extensions import load_extensions
from isp_geofeed_generator.adapters import SOURCES,TARGETS
assert Path(isp_geofeed_generator.__file__).is_relative_to(Path(sys.prefix)), 'Imported checkout instead of installed wheel'
sources,targets=load_extensions({'sources':['local_json'],'targets':['local_file']},SOURCES,TARGETS)
assert sources['local_json'].initial and targets['local_file'].initial
assert SOURCES['powercode'].initial and SOURCES['gaiia'].initial
print('PASS: installed core and separate input/output extension wheels')
'''
with tempfile.TemporaryDirectory() as directory:
    environment = dict(os.environ)
    environment.pop('PYTHONPATH', None)
    subprocess.run([sys.executable, '-c', code], cwd=directory, env=environment, check=True)
    subprocess.run([sys.executable, '-m', 'isp_geofeed_generator', '--help'], cwd=directory, env=environment, check=True, stdout=subprocess.DEVNULL)
