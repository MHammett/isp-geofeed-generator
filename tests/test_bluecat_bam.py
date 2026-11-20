import base64
import contextlib
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import yaml

from isp_geofeed_generator import bluecat_bam as module
from isp_geofeed_generator.adapters import SOURCES
from isp_geofeed_generator.cli import main
from isp_geofeed_generator.client import GeofeedError
from isp_geofeed_generator.credentials import CredentialStore, InputCredentialStore
from isp_geofeed_generator.feed import build, parse_feed
from bogon_fixture import policy
from test_sources import HTTP

CONFIGURATION = '101'
V4, V6 = '1001', '1002'
PREFIXES = ['11.22.33.0/24', '2001:4860:123a::/126']
LOCATION = {'country':'US','region':'US-IL','city':'Reviewed City'}


def row(identifier=V4, prefix=PREFIXES[0], kind='IPv4Network'):
    return {'id':int(identifier),'type':kind,'range':prefix,'configuration':{'id':101,'name':'PRIVATE configuration'},
            'name':'PRIVATE name','userDefinedFields':{'secret':'PRIVATE secret'},
            'location':{'id':777,'name':'PRIVATE location'},'_links':{'up':{'href':'https://foreign.example/PRIVATE'}}}


def settings(ids=None):
    return {'configuration_id':CONFIGURATION,'network_ids':[V4,V6] if ids is None else ids}


def locations():
    return {'network:'+identifier:dict(LOCATION) for identifier in (V4,V6)}


class BlueCatTests(unittest.TestCase):
    def source(self, replies=None, ids=None):
        http=HTTP([row(),row(V6,'2001:4860:123A::/126','IPv6Network')] if replies is None else replies)
        return module.BlueCatBAM('https://example.net/mount/api/v2/','reader','synthetic-token',settings(ids),http),http

    def test_selected_dual_stack_gets_exact_boundaries_and_auth_without_private_fields(self):
        source,http=self.source();snapshot=source.for_publication(source.snapshot())
        data,report=build(snapshot,{'allowed_prefixes':PREFIXES,'site_locations':locations()})
        self.assertEqual([str(net) for net in parse_feed(data)],PREFIXES)
        self.assertEqual([net.num_addresses for net in parse_feed(data)],[256,4])
        self.assertEqual({r['mapping_source'] for r in report},{'configuration'})
        self.assertNotIn('PRIVATE',json.dumps(snapshot));self.assertNotIn('foreign',json.dumps(snapshot))
        expected={'Authorization':'Basic '+base64.b64encode(b'reader:synthetic-token').decode(),'Accept':'application/hal+json'}
        for (url,kwargs),identifier in zip(http.calls,(V4,V6)):
            self.assertEqual(url,'https://example.net/mount/api/v2/networks/'+identifier)
            self.assertEqual(kwargs,{'headers':expected,'method':'GET'})
        self.assertEqual(len(http.calls),2)

    def test_documented_uppercase_ipv6_is_canonicalized_without_widening(self):
        value='2A00:23C6:A890:5001::/64'
        source,_=self.source([row(V6,value,'IPv6Network')],[V6])
        snapshot=source.snapshot();self.assertEqual(snapshot['pools'][0]['ip_range'],'2a00:23c6:a890:5001::/64')
        data,_=build(snapshot,{'allowed_prefixes':['2a00:23c6:a890:5001::/64'],'site_locations':locations()})
        self.assertEqual(parse_feed(data)[0].num_addresses,2**64)

    def test_reply_id_must_be_exact_numeric_not_boolean_string_or_other_record(self):
        for bad in (None,[],{}, {'data':[row()]},{**row(),'id':True},{**row(),'id':V4},row('9999')):
            source,_=self.source([bad],[V4])
            with self.subTest(value=bad),self.assertRaisesRegex(GeofeedError,'numeric ID'):source.snapshot()

    def test_configuration_is_required_exact_and_not_a_physical_location(self):
        for value in (None,{},False,{'id':True},{'id':CONFIGURATION},{'id':202}):
            source,_=self.source([{**row(),'configuration':value}],[V4])
            with self.subTest(value=value),self.assertRaisesRegex(GeofeedError,'configured configuration'):source.snapshot()
        source,_=self.source();snapshot=source.snapshot()
        with self.assertRaises(GeofeedError):build(snapshot,{'allowed_prefixes':PREFIXES})
        self.assertIn('not verified',snapshot['site_resolution'])

    def test_invalid_types_ranges_host_bits_and_wrong_family_never_echo_values(self):
        changes=[{'type':'IP4Network'},{'type':'IPv4Block'},{'type':False},{'range':'PRIVATE'},
                 {'range':True},{'range':'11.22.33.1/24'},{'range':'11.22.33.0'},
                 {'range':'11.22.33.0/255.255.255.0'},{'range':'11.22.33.0/024'},
                 {'range':'2001:4860::/64'},{'range':'2001:4860::%PRIVATE/64'},
                 {'range':'11.22.33.0/24\n'},{'range':'1'*129}]
        for change in changes:
            source,_=self.source([{**row(),**change}],[V4])
            with self.subTest(change=change):
                with self.assertRaises(GeofeedError) as error:source.snapshot()
                self.assertNotIn('PRIVATE',str(error.exception))
        source,_=self.source([row(V6,'2001:4860:123A::1/126','IPv6Network')],[V6])
        with self.assertRaises(GeofeedError):source.snapshot()

    def test_config_ids_and_selection_are_validated_before_any_request(self):
        for change in ({'configuration_id':False},{'configuration_id':'../PRIVATE'},
                       {'network_ids':None},{'network_ids':[]},{'network_ids':V4},
                       {'network_ids':[V4,int(V4)]},{'network_ids':['01001']},
                       {'network_ids':[False]},{'network_ids':['1'*21]},{'network_ids':[V4]*257}):
            http=Mock()
            with self.subTest(change=change),self.assertRaises(GeofeedError):
                module.BlueCatBAM('https://example.net/api/v2','reader','token',{**settings(),**change},http)
            http.request.assert_not_called()
        source=module.BlueCatBAM('https://example.net/api/v2','reader','token',{'configuration_id':101,'network_ids':[1001]},HTTP([row()]))
        self.assertEqual(source.snapshot()['pools'][0]['source_id'],V4)

    def test_url_and_basic_credentials_are_explicit_and_scoped_to_named_input(self):
        for url in ('http://example.net/api/v2','https://user:token@example.net/api/v2',
                    'https://example.net/Services/REST/v1','https://example.net/api/v2?x=PRIVATE'):
            with self.assertRaises(GeofeedError):module.BlueCatBAM(url,'reader','token',settings())
        for username,token in (('reader:other','token'),('reader','bad\nheader'),('reader',''),
                               ('','token'),('bad name','token'),('reader',False),('r\u00e9ader','token')):
            with self.assertRaises(GeofeedError):module.BlueCatBAM('https://example.net/api/v2',username,token,settings())
        credentials=Mock();credentials.get.return_value='synthetic-value'
        with patch.dict('os.environ',{'BLUECAT_BAM_URL':'https://example.net/api/v2'}):
            SOURCES['bluecat_bam'].create(settings(),credentials)
        self.assertEqual({call.args[0] for call in credentials.get.call_args_list},{'BLUECAT_BAM_USERNAME','BLUECAT_BAM_API_TOKEN'})
        parent=CredentialStore(environ={'EXT_BAM_USERNAME':'reader','EXT_BAM_TOKEN':'synthetic-token'})
        named=InputCredentialStore({'BLUECAT_BAM_USERNAME':'env:EXT_BAM_USERNAME','BLUECAT_BAM_API_TOKEN':'env:EXT_BAM_TOKEN'},parent,'https://named.example/api/v2')
        self.assertEqual(SOURCES['bluecat_bam'].create(settings(),named).url,'https://named.example/api/v2')
        self.assertTrue(SOURCES['bluecat_bam'].initial)

    def test_expired_token_denial_timeout_and_late_failure_never_retry_or_login(self):
        for replies in ([GeofeedError('HTTP 401; no retry was made')],
                        [GeofeedError('Connection failed (TimeoutError); no retry was made')],
                        [row(),GeofeedError('HTTP 403; no retry was made')]):
            source,_=self.source();source.http=Mock();source.http.request.side_effect=replies
            with self.assertRaises(GeofeedError):source.snapshot()
            self.assertEqual(source.http.request.call_count,len(replies))
            self.assertTrue(all(call.kwargs['method']=='GET' for call in source.http.request.call_args_list))

    def test_missing_or_reordered_publication_selection_is_not_healthy(self):
        source,_=self.source();snapshot=source.snapshot()
        for pools in ([],snapshot['pools'][:1],snapshot['pools'][::-1],snapshot['pools']*2):
            with self.assertRaises(GeofeedError):source.for_publication({**snapshot,'pools':pools})

    def test_ownership_bogons_and_overlap_guards_remain_active(self):
        source,_=self.source();snapshot=source.snapshot()
        with self.assertRaisesRegex(GeofeedError,'outside allowed_prefixes'):
            build(snapshot,{'allowed_prefixes':PREFIXES[:1],'site_locations':locations()})
        source,_=self.source([row(),row(V6,PREFIXES[0],'IPv4Network')])
        with self.assertRaisesRegex(GeofeedError,'Overlapping/duplicate'):
            build(source.snapshot(),{'allowed_prefixes':PREFIXES,'site_locations':locations()})
        for value,kind in (('10.0.0.0/24','IPv4Network'),('2001:db8::/64','IPv6Network')):
            source,_=self.source([row(V4,value,kind)],[V4])
            with self.assertRaisesRegex(GeofeedError,'No public mapped prefixes'):
                build(source.snapshot(),{'allowed_prefixes':[value],'site_locations':locations()})

    def test_cli_opt_in_unchanged_and_late_invalid_selection_preserve_feed_and_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'config.yaml'
            config={'inputs':{'bam':{'source':{'type':'bluecat_bam',**settings()},'url':'https://example.net/api/v2',
                    'credentials':{'BLUECAT_BAM_USERNAME':'env:EXT_BAM_USERNAME','BLUECAT_BAM_API_TOKEN':'env:EXT_BAM_TOKEN'},
                    'site_locations':locations()}},'allowed_prefixes':PREFIXES,'state_dir':str(root/'state'),
                    'publish':{'type':'file','path':str(root/'feed.csv')}}
            def run(replies):
                path.write_text(yaml.safe_dump(config));output,error=io.StringIO(),io.StringIO()
                with patch.dict('os.environ',{'EXT_BAM_USERNAME':'reader','EXT_BAM_TOKEN':'synthetic-token'}), \
                     patch.object(module,'JsonHTTP',return_value=HTTP(replies)), \
                     patch('isp_geofeed_generator.cli.load_policy',return_value=policy()), \
                     contextlib.redirect_stdout(output),contextlib.redirect_stderr(error):result=main(['publish','--config',str(path)])
                self.assertNotIn('PRIVATE',output.getvalue()+error.getvalue())
                self.assertNotIn('synthetic-token',output.getvalue()+error.getvalue())
                return result
            good=[row(),row(V6,'2001:4860:123A::/126','IPv6Network')]
            self.assertEqual(run(good),1);self.assertFalse((root/'feed.csv').exists())
            config['inputs']['bam']['source']['allow_initial']=True;self.assertEqual(run(good),0)
            files=[root/'feed.csv',root/'state/before.csv'];before={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in files}
            self.assertEqual(run(good),0);self.assertEqual({p:(p.read_bytes(),p.stat().st_mtime_ns) for p in files},before)
            for change in ({'id':9999},{'configuration':{'id':202}},{'range':'PRIVATE'},{'range':PREFIXES[0],'type':'IPv4Network'}):
                self.assertEqual(run([row(),{**good[1],**change}]),1)
                self.assertEqual({p:(p.read_bytes(),p.stat().st_mtime_ns) for p in files},before)
                self.assertFalse(json.loads((root/'state/status.json').read_text())['data']['healthy'])

    def test_private_id_configuration_and_family_guard_removals_fail_assertions(self):
        text=Path(module.__file__).read_text()
        controls=[('identity',"str(row['id']) != rid",'False',
                   'test_reply_id_must_be_exact_numeric_not_boolean_string_or_other_record'),
                  ('configuration',"str(configuration['id']) != self.configuration",'False',
                   'test_configuration_is_required_exact_and_not_a_physical_location'),
                  ('family','if network.version != TYPES[kind]:','if False:',
                   'test_invalid_types_ranges_host_bits_and_wrong_family_never_echo_values')]
        def run(method):
            result=unittest.TestResult();BlueCatTests(method).run(result);return result
        positive='test_selected_dual_stack_gets_exact_boundaries_and_auth_without_private_fields'
        for name,find,replacement,method in controls:
            self.assertTrue(run(positive).wasSuccessful());self.assertTrue(run(method).wasSuccessful())
            self.assertEqual(text.count(find),1)
            private=types.ModuleType('isp_geofeed_generator._private_bam_control');private.__package__='isp_geofeed_generator'
            exec(compile(text.replace(find,replacement),'<private BAM control>','exec'),private.__dict__)
            with patch.object(module,'BlueCatBAM',private.BlueCatBAM):result=run(method)
            self.assertEqual(result.errors,[]);self.assertGreater(len(result.failures),0)
            self.assertTrue(run(positive).wasSuccessful());self.assertTrue(run(method).wasSuccessful())
            print('BLUECAT BAM MUTATION OBSERVATION: '+json.dumps({'mutation':name,
                'assertion_failures':len(result.failures),'errors':0,'intact_before_after':True}))
