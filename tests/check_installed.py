"""CI smoke check using installed wheels, outside the source checkout."""
import os
import subprocess
import sys
import tempfile

code = '''from pathlib import Path
import sys
import subprocess
import isp_geofeed_generator
from isp_geofeed_generator.extensions import load_extensions
from isp_geofeed_generator.adapters import SOURCES,TARGETS
assert Path(isp_geofeed_generator.__file__).is_relative_to(Path(sys.prefix)), 'Imported checkout instead of installed wheel'
sources,targets=load_extensions({'sources':['local_json'],'targets':['local_file']},SOURCES,TARGETS)
assert sources['local_json'].initial and targets['local_file'].initial
assert SOURCES['powercode'].initial and SOURCES['gaiia'].initial
print('PASS: installed core and separate input/output extension wheels')
from isp_geofeed_generator.iso_codes import code_tables
assert tuple(map(len,code_tables()))==(249,5046)
for name in ('LICENSE.txt','COPYRIGHT.txt','sources.json'):
    assert (Path(isp_geofeed_generator.__file__).parent/'iso_data'/name).is_file()
print('PASS: installed ISO data, integrity checks and third-party notices')
from isp_geofeed_generator.client import Sonar,GeofeedError
from isp_geofeed_generator.splynx import Splynx
from isp_geofeed_generator.phpipam import PhpIPAM
class Replies:
    def __init__(self,rows):self.rows=iter(rows)
    def request(self,*args,**kwargs):return next(self.rows)
class ControllerSource(Sonar):
    def pages(self,root,*args,**kwargs):
        if root=='dhcp_servers':
            return [{'id':'3','enabled':True,'serves_all_pools':False,'ip_address':'private-record-value',
                     'ip_pools':{'page_info':{'total_count':1},'entities':[{'id':'101'}]}}]
        return []
sonar=ControllerSource('https://example.net','synthetic-token')
splynx=Splynx('https://example.net','key','secret',http=Replies([[],[{'id':'42','network':'private-record-value','mask':24}],[]]))
ipam=PhpIPAM('https://example.net','app','synthetic-token',http=Replies([
    {'success':True,'code':200,'data':[{'id':'12','subnet':'private-record-value','mask':24}]},
    {'success':True,'code':200,'data':[]}]))
for call,label in [(lambda:sonar.controller_candidates({'pools':[{'id':'101','subnet_id':'5'}],'sites':[]}), 'Sonar DHCP server 3'),
                   (splynx.snapshot,'Splynx IPv4 network 42'),(ipam.snapshot,'phpIPAM subnet 12')]:
    try:call()
    except GeofeedError as exc:
        assert label in str(exc) and 'private-record-value' not in str(exc)
    else:raise AssertionError('Malformed installed source was accepted')
print('PASS: installed Sonar/Splynx/phpIPAM errors name safe record IDs without field values')
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
wire=(root/'feed.csv').read_bytes()
assert b'\\r\\n' in wire and b'\\n' not in wire.replace(b'\\r\\n',b'')
print('PASS: installed external target publishes CRLF bytes')
generated=subprocess.run([sys.executable,'-m','isp_geofeed_generator','generate','--config',str(path)],capture_output=True,check=True)
assert generated.stdout==wire
print('PASS: installed generate stdout preserves exact candidate bytes')
data=json.loads((root/'state/status.json').read_text())['data']
assert {row['input'] for row in data['pools']}=={'customers','infrastructure'}
print('PASS: installed multi-input CLI with two instances of an external source and external target')
from isp_geofeed_generator.feed import digest
before=(root/'feed.csv').read_bytes()
for name in entries:
    inventory=root/(name+'.json');value=json.loads(inventory.read_text())
    value['sites'][0]['addresses'][0]['city']='Reviewed City'
    inventory.write_text(json.dumps(value))
assert main(['publish','--config',str(path)])==1
assert (root/'feed.csv').read_bytes()==before
candidate=root/'candidate.csv'
assert main(['generate','--config',str(path),'--output',str(candidate)])==0
assert main(['publish','--config',str(path),'--approve-location-changes',digest(candidate.read_bytes())])==0
assert (root/'feed.csv').read_bytes()==candidate.read_bytes()
print('PASS: installed external target enforces location guard and exact candidate approval')
feed=root/'feed.csv';backup=root/'state/before.csv'
stamp=feed.stat().st_mtime_ns;backup_stamp=backup.stat().st_mtime_ns;backup_bytes=backup.read_bytes()
assert main(['publish','--config',str(path)])==0
assert feed.stat().st_mtime_ns==stamp
assert backup.stat().st_mtime_ns==backup_stamp and backup.read_bytes()==backup_bytes
result=json.loads((root/'state/status.json').read_text())['data']
assert result['changed'] is False and result['verification']=='local-bytes'
assert result['recovery_backup_changed'] is False
print('PASS: installed external target verifies unchanged output without rewriting feed or recovery backup')
'''
with tempfile.TemporaryDirectory() as directory:
    environment = dict(os.environ)
    environment.pop('PYTHONPATH', None)
    subprocess.run([sys.executable, '-c', code], cwd=directory, env=environment, check=True)
    subprocess.run([sys.executable, '-m', 'isp_geofeed_generator', '--help'], cwd=directory, env=environment, check=True, stdout=subprocess.DEVNULL)
