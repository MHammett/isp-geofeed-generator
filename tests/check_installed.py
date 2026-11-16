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
assert SOURCES['billmax'].initial
assert SOURCES['infoblox_nios'].initial
print('PASS: installed core and separate input/output extension wheels')
from isp_geofeed_generator.sdk import TARGET_API_VERSION, REJECT, LONGEST_PREFIX, require_target_policy, GeofeedError
_,v2targets=load_extensions({'targets_v2':['local_file_v2']},SOURCES,TARGETS)
descriptor=v2targets['local_file_v2']
assert descriptor.api_version==TARGET_API_VERSION==2
require_target_policy(descriptor,REJECT)
try:require_target_policy(descriptor,LONGEST_PREFIX)
except GeofeedError:pass
else:raise AssertionError('Version-2 discovery silently enabled nesting')
v2path=Path.cwd()/'v2-example.csv'
v2=descriptor({'path':str(v2path)},None)
v2bytes=b'11.22.33.0/24,US,US-IL,A,\\r\\n'
assert v2.publish(v2bytes,Path.cwd()/'v2-state',overlap_policy=REJECT)['changed'] is True
assert v2path.read_bytes()==v2bytes
assert v2.publish(v2bytes,Path.cwd()/'v2-state',overlap_policy=REJECT)['changed'] is False
print('PASS: installed version-2 target discovery, explicit strict policy and unchanged publication')
from isp_geofeed_generator.iso_codes import code_tables
assert tuple(map(len,code_tables()))==(249,5046)
for name in ('LICENSE.txt','COPYRIGHT.txt','sources.json'):
    assert (Path(isp_geofeed_generator.__file__).parent/'iso_data'/name).is_file()
print('PASS: installed ISO data, integrity checks and third-party notices')
from isp_geofeed_generator._effective import compare_effective
from isp_geofeed_generator.feed import parse_feed
from isp_geofeed_generator.client import GeofeedError
parent={'prefix':'11.22.33.0/24','location':{'country':'US','region':'US-IL','city':'A'}}
child={'prefix':'11.22.33.0/25','location':{'country':'US','region':'US-IL','city':'B'}}
change=compare_effective([parent],[child,parent])[4]
assert (change.old,change.new,change.retained,change.removed,change.relocated)==(256,256,256,0,128)
assert change.decimal_counts()['relocated']=='128'
try:parse_feed(b'11.22.33.0/24,US,US-IL,A,\\r\\n11.22.33.0/25,US,US-IL,B,\\r\\n')
except GeofeedError:pass
else:raise AssertionError('Internal analysis enabled nested publication')
print('PASS: installed effective interval analysis with strict publication refusal')
from isp_geofeed_generator.client import Sonar,GeofeedError
from isp_geofeed_generator.splynx import Splynx
from isp_geofeed_generator.phpipam import PhpIPAM
class Replies:
    def __init__(self,rows):self.rows=iter(rows)
    def request(self,*args,**kwargs):return next(self.rows)
from isp_geofeed_generator.billmax import BillMax
from isp_geofeed_generator.feed import build
billmax=BillMax('https://example.net/api/billmaxCoreApi/v1','synthetic-key',{'ap_ids':['7']},http=Replies([
    [{'id':'7','networkMask':'11.22.33.0/24','_pop':[{'id':12,'country':'US','stateProvince':'US-IL','city':'Example City'}]}]]))
value,_=build(billmax.for_publication(billmax.snapshot()),{'allowed_prefixes':['11.22.33.0/24']})
assert value==b'11.22.33.0/24,US,US-IL,Example City,\\r\\n'
print('PASS: installed BillMax selected AP network and native POP workload')
from isp_geofeed_generator.infoblox_nios import InfobloxNIOS
ref='ipv6network/opaque:2001%3A4860%3A1234%3A%3A/126/external'
nios=InfobloxNIOS('https://example.net/wapi/v2.13.6','reader','synthetic-password',{'network_refs':[ref]},Replies([
    {'result':[{'_ref':ref,'network':'2001:4860:1234::/126','network_view':'external','extattrs':{
        'geofeed_country':{'value':'US'},'geofeed_region':{'value':'US-IL'},'geofeed_city':{'value':'Example City'}}}]}]))
value,_=build(nios.for_publication(nios.snapshot()),{'allowed_prefixes':['2001:4860:1234::/48']})
assert value==b'2001:4860:1234::/126,US,US-IL,Example City,\\r\\n'
print('PASS: installed NIOS IPv6 network and declared geography workload')
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
from isp_geofeed_generator.netbox import NetBox
from isp_geofeed_generator.feed import build
prefix={'id':1,'prefix':'11.22.33.0/24','status':{'value':'active'},'vrf':None,
        'scope_type':'dcim.region','scope_id':3,
        'custom_fields':{'geofeed_country':'US','geofeed_region':'US-IL','geofeed_city':'Example City'}}
def page(rows):return {'count':len(rows),'next':None,'results':rows}
for mode in ('prefix_fields','region_hierarchy'):
    responses=[page([prefix]),page([])]
    if mode=='region_hierarchy':responses.append(page([{'id':1,'name':'US','parent':None},
        {'id':2,'name':'US-IL','parent':{'id':1}},{'id':3,'name':'Example City','parent':{'id':2}}]))
    source=NetBox('https://example.net','synthetic-token',{'location_mode':mode,'prefix_ids':['1']},Replies(responses))
    value,_=build(source.for_publication(source.snapshot()),{'allowed_prefixes':['11.22.33.0/24']})
    assert b',US,US-IL,Example City,' in value
print('PASS: installed NetBox prefix-field and Region-hierarchy workloads')
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
from isp_geofeed_generator.bound_output import policy_path,recover_bound
from isp_geofeed_generator.overlap import LONGEST_PREFIX
for index,name in enumerate(entries):
    inventory=root/(name+'.json');value=json.loads(inventory.read_text())
    prefix='11.22.33.0/24' if index==0 else '11.22.33.0/25'
    value['pools'][0]['ip_range']=prefix;value['pools'][0]['subnet']['subnet']=prefix
    value['sites'][0]['addresses'][0]['city']='Nested '+str(index)
    inventory.write_text(json.dumps(value))
nested=root/'nested.csv';nested_state=root/'nested-state'
config.update(overlap_policy=LONGEST_PREFIX,state_dir=str(nested_state),publish={'type':'file','path':str(nested)})
path.write_text(yaml.safe_dump(config))
assert main(['publish','--config',str(path)])==0
assert nested.read_bytes().startswith(b'# isp-geofeed-generator v2 ')
paths=[nested,policy_path(nested),nested_state/'before.csv',nested_state/'before.policy.json',nested_state/'local-transaction.json']
stamps={str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in paths}
assert main(['publish','--config',str(path)])==0
assert {str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in paths}==stamps
try:targets['local_file']({'path':str(nested)},None).publish(nested.read_bytes(),root/'old-extension-state')
except GeofeedError:pass
else:raise AssertionError('Version-1 target overwrote a policy-bound destination')
assert recover_bound(nested,nested_state,'csv',digest(nested.read_bytes()))['recovered'] is True
assert not nested.exists() and not policy_path(nested).exists()
print('PASS: installed nested multi-input local publication, unchanged policy history and conditional recovery')
'''
with tempfile.TemporaryDirectory() as directory:
    environment = dict(os.environ)
    environment.pop('PYTHONPATH', None)
    subprocess.run([sys.executable, '-c', code], cwd=directory, env=environment, check=True)
    subprocess.run([sys.executable, '-m', 'isp_geofeed_generator', '--help'], cwd=directory, env=environment, check=True, stdout=subprocess.DEVNULL)
