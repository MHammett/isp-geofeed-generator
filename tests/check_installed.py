"""CI smoke check using installed wheels, outside the source checkout."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

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
import contextlib,io
from isp_geofeed_generator.feed import parse_feed
registry=root/'registry.json'
url='https://example.net/feed.csv'
objects=[{'id':str(index),'prefix':str(network),'geofeed':url,'remarks':['Geofeed https://other.example/feed.csv']}
         for index,network in enumerate(parse_feed(feed.read_bytes()))]
registry.write_text(json.dumps({'schema_version':1,'observed_at':'2020-01-01T00:00:00Z','objects':objects}))
prior={str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in (feed,root/'state/status.json',backup)}
output=io.StringIO()
with contextlib.redirect_stdout(output):
    assert main(['check-registry','--config',str(root/'missing.yaml'),'--registry-records',str(registry),
                 '--feed',str(feed),'--feed-url',url])==0
assert json.loads(output.getvalue())['comparison_consistent'] is True
objects[0]['geofeed']='https://other.example/feed.csv'
registry.write_text(json.dumps({'schema_version':1,'observed_at':'2020-01-01T00:00:00Z','objects':objects}))
output=io.StringIO()
with contextlib.redirect_stdout(output):
    assert main(['check-registry','--registry-records',str(registry),'--feed',str(feed),'--feed-url',url])==1
result=json.loads(output.getvalue())
assert result['comparison_consistent'] is False and result['live_registry_read']=='not_measured' and 'healthy' not in result
assert {str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in (feed,root/'state/status.json',backup)}==prior
print('PASS: installed offline registry precedence and unsigned coverage checks without configuration or publication writes')
import ipaddress
networks=list(parse_feed(feed.read_bytes()))
ranges=[{'id':str(index),'start':str(net.network_address),'end':str(net.broadcast_address),'geofeed':url}
        for index,net in enumerate(networks)]
def range_snapshot(values):
    registry.write_text(json.dumps({'schema_version':1,'observed_at':'2020-01-01T00:00:00Z','objects':values}))
range_snapshot(ranges)
output=io.StringIO()
with contextlib.redirect_stdout(output):
    assert main(['check-registry','--registry-records',str(registry),'--feed',str(feed),'--feed-url',url])==0
result=json.loads(output.getvalue())
assert result['comparison_consistent'] is True and result['scope']=='supplied_unsigned_range_snapshot'
assert result['registry_scope_formats']=={'cidr':0,'address_range':len(networks)}
index=next(i for i,net in enumerate(networks) if net.num_addresses>=4)
net=networks[index]
clipped=[dict(value) for value in ranges]
clipped[index]['start']=str(net.network_address+1)
clipped[index]['end']=str(net.broadcast_address-1)
range_snapshot(clipped)
output=io.StringIO()
with contextlib.redirect_stdout(output):
    assert main(['check-registry','--registry-records',str(registry),'--feed',str(feed),'--feed-url',url])==1
assert json.loads(output.getvalue())['coverage'][str(net.version)]['unreferenced']=='2'
range_snapshot(ranges+[{'id':'crossing','start':str(net.network_address+1),'end':str(net.broadcast_address+1),'geofeed':url}])
error=io.StringIO()
with contextlib.redirect_stderr(error):
    assert main(['check-registry','--registry-records',str(registry),'--feed',str(feed),'--feed-url',url])==1
assert 'crossing referring scopes' in error.getvalue()
assert {str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in (feed,root/'state/status.json',backup)}==prior
print('PASS: installed exact registry range coverage and crossing-scope refusal without publication writes')
ripe_objects=[]
for net in networks:
    kind='inetnum' if net.version==4 else 'inet6num'
    value=f'{net.network_address} - {net.broadcast_address}' if net.version==4 else str(net)
    ripe_objects.append({'type':kind,'source':{'id':'ripe'},
        'primary-key':{'attribute':[{'name':kind,'value':value}]},
        'attributes':{'attribute':[{'name':kind,'value':value},{'name':'source','value':'RIPE'},
                                   {'name':'geofeed','value':url},{'name':'admin-c','value':'PRIVATE-CONTACT'}]}})
registry.write_text(json.dumps({'objects':{'object':ripe_objects}}))
ripe_args=['check-registry','--registry-format','ripe-rest','--registry-observed-at','2020-01-01T00:00:00Z',
           '--registry-records',str(registry),'--feed',str(feed),'--feed-url',url,'--config',str(root/'absent.yaml')]
output=io.StringIO()
with contextlib.redirect_stdout(output):assert main(ripe_args)==0
result=json.loads(output.getvalue())
assert result['comparison_consistent'] and result['registry_input_format']=='ripe-rest'
assert result['snapshot_observed_at_source']=='operator_supplied' and result['live_registry_read']=='not_measured'
assert 'PRIVATE' not in output.getvalue() and url not in output.getvalue() and 'healthy' not in result
ripe_objects[0]['primary-key']['attribute'][0]['value']='11.22.34.0 - 11.22.34.255'
registry.write_text(json.dumps({'objects':{'object':ripe_objects}}))
error=io.StringIO();output=io.StringIO()
with contextlib.redirect_stderr(error),contextlib.redirect_stdout(output):assert main(ripe_args)==1
assert 'matching primary key' in error.getvalue() and output.getvalue()==''
assert {str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in (feed,root/'state/status.json',backup)}==prior
print('PASS: installed saved-RIPE exact coverage and primary-key refusal without configuration or publication writes')
batch_feed=root/'batch-feed.csv'
batch_feed.write_bytes(b'11.22.33.0/24,US,US-IL,Example City,\\r\\n2001:4860:1234::/126,US,US-IL,Example City,\\r\\n')
batch_sources=[root/'batch-v4.json',root/'batch-v6.json'];batch_objects=[]
for kind,value in (('inetnum','11.22.33.0 - 11.22.33.255'),('inet6num','2001:4860:1234::/126')):
    batch_objects.append({'type':kind,'source':{'id':'RIPE'},
        'primary-key':{'attribute':[{'name':kind,'value':value}]},
        'attributes':{'attribute':[{'name':kind,'value':value},{'name':'source','value':'RIPE'},
                                   {'name':'geofeed','value':url},{'name':'admin-c','value':'PRIVATE-CONTACT'}]}})
for source,value in zip(batch_sources,batch_objects):source.write_text(json.dumps({'objects':{'object':[value]}}))
batch_args=['check-registry','--registry-format','ripe-rest','--feed',str(batch_feed),'--feed-url',url,
            '--config',str(root/'absent.yaml')]
for source,stamp in zip(batch_sources,('2020-01-01T00:00:00Z','2021-01-01T00:00:00Z')):
    batch_args+=['--registry-records',str(source),'--registry-observed-at',stamp]
batch_prior={str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in
             (batch_feed,*batch_sources,feed,root/'state/status.json',backup)}
output=io.StringIO()
with contextlib.redirect_stdout(output):assert main(batch_args)==0
batch_report=json.loads(output.getvalue())
assert batch_report['snapshot_input_count']==batch_report['registry_objects']==2
assert batch_report['coverage']['4']['this_feed']=='256' and batch_report['coverage']['6']['this_feed']=='4'
assert batch_report['snapshot_observed_at_basis']=='oldest_supplied_input'
assert batch_report['snapshot_observed_at']=='2020-01-01T00:00:00+00:00'
assert [item['snapshot_sha256'] for item in batch_report['snapshot_inputs']]==[digest(p.read_bytes()) for p in batch_sources]
assert 'PRIVATE' not in output.getvalue() and url not in output.getvalue() and 'healthy' not in batch_report
assert {str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in
        (batch_feed,*batch_sources,feed,root/'state/status.json',backup)}==batch_prior
for duplicate in (False,True):
    value={'objects':{'object':[batch_objects[0]]}} if duplicate else {'objects':{'object':[]},'errormessages':{'errormessage':[{'severity':'Info','text':'PRIVATE'}]}}
    batch_sources[1].write_text(json.dumps(value))
    source_prior=(batch_sources[1].read_bytes(),batch_sources[1].stat().st_mtime_ns)
    output=io.StringIO();error=io.StringIO()
    with contextlib.redirect_stdout(output),contextlib.redirect_stderr(error):assert main(batch_args)==1
    assert output.getvalue()=='' and 'PRIVATE' not in error.getvalue()
    assert ('unique safe IDs' if duplicate else 'Registry input 2') in error.getvalue()
    assert (batch_sources[1].read_bytes(),batch_sources[1].stat().st_mtime_ns)==source_prior
    assert {str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in
            (batch_feed,batch_sources[0],feed,root/'state/status.json',backup)}=={key:value for key,value in batch_prior.items() if key!=str(batch_sources[1])}
print('REGISTRY BATCH INSTALLED OBSERVATION: '+json.dumps({'input_count':2,'object_count':2,'matched_families':[4,6],
    'oldest_date_verified':True,'input_hashes_verified':True,'api_message_refused':True,'duplicate_version_refused':True,
    'private_files_preserved':True,'no_configuration_needed':True}))
rdap_objects=[]
for family,start,end in (('v4','11.22.33.0','11.22.33.255'),('v6','2001:4860:1234::','2001:4860:1234::3')):
    rdap_objects.append({'objectClassName':'ip network','handle':'PRIVATE-'+family,'startAddress':start,'endAddress':end,
        'ipVersion':family,'rdapConformance':['rdap_level_0']+(['geofeed1'] if family=='v4' else []),
        'links':[{'rel':'geofeed alternate','value':'https://rdap.example/ip/object','href':url}],
        'country':'NL','entities':[{'handle':'PRIVATE-CONTACT'}]})
for source,value in zip(batch_sources,rdap_objects):source.write_text(json.dumps(value))
rdap_args=list(batch_args);rdap_args[rdap_args.index('ripe-rest')]='rdap'
rdap_prior={str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in
            (batch_feed,*batch_sources,feed,root/'state/status.json',backup)}
output=io.StringIO()
with contextlib.redirect_stdout(output):assert main(rdap_args)==0
rdap_report=json.loads(output.getvalue())
assert rdap_report['registry_input_format']=='rdap' and rdap_report['registry_source']=='operator_supplied_rdap'
assert rdap_report['coverage']['4']['this_feed']=='256' and rdap_report['coverage']['6']['this_feed']=='4'
assert rdap_report['rdap_geofeed1_advertised_inputs']==1 and rdap_report['rdap_linked_inputs']==2
assert [v['snapshot_sha256'] for v in rdap_report['snapshot_inputs']]==[digest(p.read_bytes()) for p in batch_sources]
assert 'PRIVATE' not in output.getvalue() and url not in output.getvalue() and 'healthy' not in rdap_report
assert {str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in
        (batch_feed,*batch_sources,feed,root/'state/status.json',backup)}==rdap_prior
rdap_objects[1]['notices']=[{'type':'object truncated due to authorization','description':['PRIVATE']}]
batch_sources[1].write_text(json.dumps(rdap_objects[1]))
output=io.StringIO();error=io.StringIO()
with contextlib.redirect_stdout(output),contextlib.redirect_stderr(error):assert main(rdap_args)==1
assert output.getvalue()=='' and 'Registry input 2' in error.getvalue() and 'PRIVATE' not in error.getvalue()
del rdap_objects[1]['notices'];rdap_objects[1]['links']=[]
batch_sources[1].write_text(json.dumps(rdap_objects[1]))
source_prior=(batch_sources[1].read_bytes(),batch_sources[1].stat().st_mtime_ns)
output=io.StringIO()
with contextlib.redirect_stdout(output):assert main(rdap_args)==1
unknown=json.loads(output.getvalue())
assert unknown['comparison_consistent'] is False and unknown['rdap_absence_unknown_inputs']==1
assert unknown['snapshot_inputs'][1]['rdap_link_status']=='availability_not_measured'
assert unknown['provider_ingestion']=='not_measured' and unknown['coverage']['6']['unreferenced']=='4'
assert (batch_sources[1].read_bytes(),batch_sources[1].stat().st_mtime_ns)==source_prior
assert {str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in
        (batch_feed,batch_sources[0],feed,root/'state/status.json',backup)}=={key:value for key,value in rdap_prior.items() if key!=str(batch_sources[1])}
print('RDAP REGISTRY INSTALLED OBSERVATION: '+json.dumps({'matched_families':[4,6],'input_hashes_verified':True,
    'optional_media_type_accepted':True,'combined_relation_accepted':True,'link_without_extension_accepted':True,'truncation_refused':True,
    'absence_without_extension_unknown':True,'private_files_preserved':True,'no_configuration_needed':True}))
contact_path="$.entities[?(@.handle=='PRIVATE-CONTACT')].vcardArray[1][?(@[0]=='email')]"
for source,value in zip(batch_sources,rdap_objects):
    value['links']=[{'rel':'geofeed','value':'https://rdap.example/ip/object','href':url}]
    value['rdapConformance']+=['redacted']
    value['redacted']=[{'name':{'description':'PRIVATE contact'},'prePath':contact_path}]
    source.write_text(json.dumps(value))
redaction_prior={str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in
                 (batch_feed,*batch_sources,feed,root/'state/status.json',backup)}
output=io.StringIO()
with contextlib.redirect_stdout(output):assert main(rdap_args)==0
redaction_report=json.loads(output.getvalue())
assert redaction_report['coverage']['4']['this_feed']=='256' and redaction_report['coverage']['6']['this_feed']=='4'
assert redaction_report['rdap_ignored_entity_redactions']==2
assert all(item['rdap_ignored_entity_redactions']==1 and item['rdap_redaction_status']=='ignored_entities_only'
           for item in redaction_report['snapshot_inputs'])
assert [item['snapshot_sha256'] for item in redaction_report['snapshot_inputs']]==[digest(p.read_bytes()) for p in batch_sources]
assert 'PRIVATE' not in output.getvalue() and contact_path not in output.getvalue()
assert {str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in
        (batch_feed,*batch_sources,feed,root/'state/status.json',backup)}==redaction_prior
rdap_objects[1]['redacted'].append({'name':{'type':'Example'},'prePath':'$.links'})
batch_sources[1].write_text(json.dumps(rdap_objects[1]))
source_prior=(batch_sources[1].read_bytes(),batch_sources[1].stat().st_mtime_ns)
output=io.StringIO();error=io.StringIO()
with contextlib.redirect_stdout(output),contextlib.redirect_stderr(error):assert main(rdap_args)==1
assert output.getvalue()=='' and 'Registry input 2' in error.getvalue()
assert 'PRIVATE' not in error.getvalue() and '$.links' not in error.getvalue()
assert (batch_sources[1].read_bytes(),batch_sources[1].stat().st_mtime_ns)==source_prior
assert {str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in
        (batch_feed,batch_sources[0],feed,root/'state/status.json',backup)}=={key:value for key,value in redaction_prior.items() if key!=str(batch_sources[1])}
print('RDAP REDACTION INSTALLED OBSERVATION: '+json.dumps({'matched_families':[4,6],'entity_declarations':2,
    'input_hashes_verified':True,'mixed_later_input_refused':True,'no_partial_report':True,
    'private_files_preserved':True,'raw_paths_omitted':True,'no_configuration_needed':True}))
for index,(source,value) in enumerate(zip(batch_sources,rdap_objects)):
    value['redacted']=value['redacted'][:1]
    value['links']=[{'rel':'geofeed','value':'https://rdap.example/ip/object','href':url,'hreflang':['EN-US','en']},
                    {'rel':'geofeed','value':'https://rdap.example/ip/object','href':'https://other.example/feed.csv','hreflang':'fr'}]
    if index:value['links'].reverse()
    source.write_text(json.dumps(value))
language_prior={str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in
                (batch_feed,*batch_sources,feed,root/'state/status.json',backup)}
language_args=rdap_args+['--rdap-language','EN']
output=io.StringIO()
with contextlib.redirect_stdout(output):assert main(language_args)==0
language_report=json.loads(output.getvalue())
assert language_report['coverage']['4']['this_feed']=='256' and language_report['coverage']['6']['this_feed']=='4'
assert language_report['rdap_requested_language']=='en' and language_report['rdap_language_selected_inputs']==2
assert language_report['snapshot_observed_at']=='2020-01-01T00:00:00+00:00'
assert [item['snapshot_observed_at'] for item in language_report['snapshot_inputs']]==['2020-01-01T00:00:00+00:00','2021-01-01T00:00:00+00:00']
assert all(item['rdap_link_selection']=='exact_language' and item['rdap_geofeed_link_count']==2
           for item in language_report['snapshot_inputs'])
assert [item['snapshot_sha256'] for item in language_report['snapshot_inputs']]==[digest(p.read_bytes()) for p in batch_sources]
assert 'PRIVATE' not in output.getvalue() and url not in output.getvalue() and 'other.example' not in output.getvalue()
output=io.StringIO();error=io.StringIO()
with contextlib.redirect_stdout(output),contextlib.redirect_stderr(error):assert main(rdap_args)==1
assert output.getvalue()=='' and 'multiple geofeed links' in error.getvalue()
output=io.StringIO()
with contextlib.redirect_stdout(output):assert main(rdap_args+['--rdap-language','fr'])==1
different_language=json.loads(output.getvalue())
assert different_language['comparison_consistent'] is False
assert different_language['coverage']['4']['other_feed']=='256' and different_language['coverage']['6']['other_feed']=='4'
assert {str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in
        (batch_feed,*batch_sources,feed,root/'state/status.json',backup)}==language_prior
for item in rdap_objects[1]['links']:
    if item['hreflang']=='fr':item['href']='http://PRIVATE.invalid/feed.csv'
batch_sources[1].write_text(json.dumps(rdap_objects[1]))
source_prior=(batch_sources[1].read_bytes(),batch_sources[1].stat().st_mtime_ns)
output=io.StringIO();error=io.StringIO()
with contextlib.redirect_stdout(output),contextlib.redirect_stderr(error):assert main(language_args)==1
assert output.getvalue()=='' and 'Registry input 2' in error.getvalue() and 'PRIVATE' not in error.getvalue()
assert (batch_sources[1].read_bytes(),batch_sources[1].stat().st_mtime_ns)==source_prior
assert {str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in
        (batch_feed,batch_sources[0],feed,root/'state/status.json',backup)}=={key:value for key,value in language_prior.items() if key!=str(batch_sources[1])}
print('RDAP LANGUAGE INSTALLED OBSERVATION: '+json.dumps({'matched_families':[4,6],'language':'en',
    'selected_inputs':2,'input_hashes_verified':True,'default_refused':True,'different_language_mismatch':True,
    'unsafe_unselected_later_link_refused':True,'no_partial_report':True,'private_files_preserved':True,
    'reference_urls_omitted':True,'no_configuration_needed':True}))
literal='"PRIVATE'+chr(92)+'uD83D'+chr(92)+'uDE00"'
valid_path='$.entities[?(@.handle=='+literal+')]'
for source,value in zip(batch_sources,rdap_objects):
    for item in value['links']:
        if item['hreflang']=='fr':item['href']='https://other.example/feed.csv'
    value['redacted']=[{'name':{'description':'PRIVATE logical field'},'prePath':valid_path}]
    source.write_text(json.dumps(value))
string_prior={str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in
              (batch_feed,*batch_sources,feed,root/'state/status.json',backup)}
output=io.StringIO()
with contextlib.redirect_stdout(output):assert main(language_args)==0
string_report=json.loads(output.getvalue())
assert string_report['coverage']['4']['this_feed']=='256' and string_report['coverage']['6']['this_feed']=='4'
assert string_report['rdap_ignored_entity_redactions']==2 and string_report['rdap_language_selected_inputs']==2
assert [item['snapshot_sha256'] for item in string_report['snapshot_inputs']]==[digest(p.read_bytes()) for p in batch_sources]
assert 'PRIVATE' not in output.getvalue() and valid_path not in output.getvalue()
assert {str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in
        (batch_feed,*batch_sources,feed,root/'state/status.json',backup)}==string_prior
refusals=[]
for kind,token in (('opposite_quote','"PRIVATE'+chr(92)+chr(39)+'"'),
                   ('escaped_surrogate','"PRIVATE'+chr(92)+'uD800"'),
                   ('raw_surrogate','"PRIVATE'+chr(0xD800)+'"')):
    rdap_objects[1]['redacted']=[{'name':{'description':'PRIVATE logical field'},'prePath':valid_path,
        'method':'replacementValue','replacementPath':'$.entities['+token+']'}]
    batch_sources[1].write_text(json.dumps(rdap_objects[1]))
    source_prior=(batch_sources[1].read_bytes(),batch_sources[1].stat().st_mtime_ns)
    output=io.StringIO();error=io.StringIO()
    with contextlib.redirect_stdout(output),contextlib.redirect_stderr(error):assert main(language_args)==1
    assert output.getvalue()=='' and 'Registry input 2' in error.getvalue() and 'PRIVATE' not in error.getvalue()
    assert (batch_sources[1].read_bytes(),batch_sources[1].stat().st_mtime_ns)==source_prior
    assert {str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in
            (batch_feed,batch_sources[0],feed,root/'state/status.json',backup)}=={key:value for key,value in string_prior.items() if key!=str(batch_sources[1])}
    refusals.append(kind)
print('RDAP STRING INSTALLED OBSERVATION: '+json.dumps({'matched_families':[4,6],'valid_pair_accepted':True,
    'language_selection_preserved':True,'input_hashes_verified':True,'lexical_refusals':refusals,
    'no_partial_report':True,'private_files_preserved':True,'raw_paths_omitted':True,'no_configuration_needed':True}))
arin='https://rdap.arin.net/registry/';ripe='https://rdap.db.ripe.net/'
bootstrap_sources=[root/'bootstrap-v4.json',root/'bootstrap-v6.json']
bootstrap_objects=[{'version':'1.0','publication':'2019-06-07T19:00:02Z','description':'PRIVATE ignored',
    'services':[[['11.0.0.0/8'],[arin,arin.replace('https://','http://')]],[[ '11.22.33.0/24'],[ripe]]]},
    {'version':'1.0','publication':'2019-06-07T19:00:02Z','description':'PRIVATE ignored',
     'services':[[['2001:4800::/23'],[ripe]],[[ '2001:4860:1234::/48'],[arin]]]}]
for source,value in zip(bootstrap_sources,bootstrap_objects):source.write_text(json.dumps(value))
bootstrap_prior={str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in
                 (*bootstrap_sources,*batch_sources,batch_feed,feed,root/'state/status.json',backup)}
for source,prefix,base in zip(bootstrap_sources,('11.22.33.0/24','2001:4860:1234::/48'),(ripe,arin)):
    output=io.StringIO()
    args=['plan-rdap','--bootstrap-records',str(source),'--bootstrap-observed-at','2020-01-01T00:00:00Z',
          '--rdap-prefix',prefix,'--config',str(root/'absent.yaml')]
    with contextlib.redirect_stdout(output):assert main(args)==0
    report=json.loads(output.getvalue())
    assert report['rdap_lookup_url']==base+'ip/'+prefix and report['bootstrap_sha256']==digest(source.read_bytes())
    assert report['bootstrap_observed_at_source']=='operator_supplied' and report['bootstrap_observed_at']=='2020-01-01T00:00:00+00:00'
    assert report['planning_only'] is True and report['bootstrap_match']=='single_service_for_entire_prefix'
    assert 'PRIVATE' not in output.getvalue() and str(source) not in output.getvalue() and 'healthy' not in report
    assert all(report[key]=='not_measured' for key in ('bootstrap_authenticity','live_registry_read',
        'ownership_validation','current_allocation_validation','signature_validation','public_retrieval','provider_ingestion'))
assert {str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in
        (*bootstrap_sources,*batch_sources,batch_feed,feed,root/'state/status.json',backup)}==bootstrap_prior
for index in (0,1):
    if index==0:bootstrap_objects[index]['services'][1][0]=['11.22.33.128/25']
    else:bootstrap_objects[index]['services'][1][1]=['https://PRIVATE.invalid/']
    bootstrap_sources[index].write_text(json.dumps(bootstrap_objects[index]))
    prior={str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in
           (*bootstrap_sources,*batch_sources,batch_feed,feed,root/'state/status.json',backup)}
    output=io.StringIO();error=io.StringIO()
    args=['plan-rdap','--bootstrap-records',str(bootstrap_sources[index]),'--bootstrap-observed-at','2020-01-01T00:00:00Z',
          '--rdap-prefix',('11.22.33.0/24','2001:4860:1234::/48')[index]]
    with contextlib.redirect_stdout(output),contextlib.redirect_stderr(error):assert main(args)==1
    assert output.getvalue()=='' and 'PRIVATE' not in error.getvalue()
    assert ('multiple bootstrap services' if index==0 else 'initial RIR profile') in error.getvalue()
    assert {str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in
            (*bootstrap_sources,*batch_sources,batch_feed,feed,root/'state/status.json',backup)}==prior
print('RDAP BOOTSTRAP INSTALLED OBSERVATION: '+json.dumps({'families':[4,6],'longest_prefix_verified':True,
    'hashes_verified':True,'date_sources_verified':True,'straddling_refused':True,'unknown_endpoint_refused':True,
    'unmeasured_fields_present':True,'no_partial_report':True,'private_files_preserved':True,'no_configuration_needed':True}))
for source,value in zip(batch_sources,rdap_objects):
    value.pop('redacted',None)
    value['links']=[{'rel':'geofeed','value':'https://rdap.example/ip/object','href':url}]
    source.write_text(json.dumps(value))
output=io.StringIO()
with contextlib.redirect_stdout(output):assert main(rdap_args)==0
assert json.loads(output.getvalue())['comparison_consistent'] is True
rdap_objects[1]['remarks']=[{'type':'object truncated due to server policy','description':['PRIVATE policy data removed']}]
batch_sources[1].write_text(json.dumps(rdap_objects[1]))
review_prior={str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in
              (*batch_sources,batch_feed,feed,root/'state/status.json',backup)}
output=io.StringIO();error=io.StringIO()
with contextlib.redirect_stdout(output),contextlib.redirect_stderr(error):assert main(rdap_args)==1
assert output.getvalue()=='' and 'Registry input 2' in error.getvalue() and 'reports truncation' in error.getvalue()
assert error.getvalue().count('no partial comparison made')==1 and 'PRIVATE' not in error.getvalue()
assert {str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in
        (*batch_sources,batch_feed,feed,root/'state/status.json',backup)}==review_prior
rdap_objects[1].pop('remarks')
rdap_objects[0]['links']=[{'rel':'geofeed','value':'https://rdap.example/ip/object','href':url,'hreflang':'en'},
                        {'rel':'geofeed','value':'https://rdap.example/ip/object','href':'https://other.example/feed.csv','hreflang':'fr'}]
for source,value in zip(batch_sources,rdap_objects):source.write_text(json.dumps(value))
review_prior={str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in
              (*batch_sources,batch_feed,feed,root/'state/status.json',backup)}
output=io.StringIO();error=io.StringIO()
with contextlib.redirect_stdout(output),contextlib.redirect_stderr(error):assert main(language_args)==1
assert output.getvalue()=='' and 'Registry input 2' in error.getvalue() and 'hreflang labels' in error.getvalue()
assert 'PRIVATE' not in error.getvalue()
assert {str(p):(p.read_bytes(),p.stat().st_mtime_ns) for p in
        (*batch_sources,batch_feed,feed,root/'state/status.json',backup)}==review_prior
print('RDAP REVIEW INSTALLED OBSERVATION: '+json.dumps({'policy_truncation_refused':True,'returned_link_preserved':True,
    'mixed_unlabeled_set_refused':True,'refusal_phrase_once':True,'no_partial_report':True,'private_files_preserved':True}))
'''
with tempfile.TemporaryDirectory() as directory:
    environment = dict(os.environ)
    environment.pop('PYTHONPATH', None)
    # A source file avoids Windows' command-line limit as this workload grows.
    script = Path(directory)/'installed_workload.py'
    with script.open('x', encoding='utf-8') as stream:
        stream.write(code)
    subprocess.run([sys.executable, str(script)], cwd=directory, env=environment, check=True)
    subprocess.run([sys.executable, '-m', 'isp_geofeed_generator', '--help'], cwd=directory, env=environment, check=True, stdout=subprocess.DEVNULL)
