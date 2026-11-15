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
import json,time,yaml
from isp_geofeed_generator.cli import main
root=Path.cwd()
entries={}
for name,prefix in [('customers','11.22.33.0/24'),('infrastructure','11.22.34.0/24')]:
    inventory=root/(name+'.json')
    inventory.write_text(json.dumps({'pools':[{'id':'1','ip_range':prefix,'subnet':{'subnet':prefix}}],
        'sites':[{'id':'1','addresses':[{'id':'1','country':'US','subdivision':'US_IL','city':'Example City'}]}]}))
    entries[name]={'source':{'type':'local_json','input_path':str(inventory),'allow_initial':True},'pool_sites':{'1':'1'}}
bogons={}
for version,rows in [(4,['0.0.0.0/8','10.0.0.0/8','127.0.0.0/8','224.0.0.0/4']),
                     (6,['::/128','fc00::/7','ff00::/8'])]:
    path=root/('synthetic-bogons-'+str(version)+'.txt')
    path.write_text('# last updated '+str(int(time.time()))+'\\n'+'\\n'.join(rows)+'\\n')
    bogons['ipv'+str(version)+'_file']=str(path)
config={'inputs':entries,'allowed_prefixes':['11.22.0.0/16'],'bogons':bogons,'state_dir':str(root/'state'),
        'extensions':{'sources':['local_json'],'targets':['local_file']},
        'publish':{'type':'local_file','path':str(root/'feed.csv'),'allow_initial':True}}
path=root/'config.yaml';path.write_text(yaml.safe_dump(config))
assert main(['publish','--config',str(path)])==0
assert len((root/'feed.csv').read_text().splitlines())==2
data=json.loads((root/'state/status.json').read_text())['data']
assert {row['input'] for row in data['pools']}=={'customers','infrastructure'}
print('PASS: installed multi-input CLI with two instances of an external source and external target')
'''
with tempfile.TemporaryDirectory() as directory:
    environment = dict(os.environ)
    environment.pop('PYTHONPATH', None)
    subprocess.run([sys.executable, '-c', code], cwd=directory, env=environment, check=True)
    subprocess.run([sys.executable, '-m', 'isp_geofeed_generator', '--help'], cwd=directory, env=environment, check=True, stdout=subprocess.DEVNULL)
