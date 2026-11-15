import copy
import hashlib
import hmac
import unittest
from urllib.parse import parse_qs, urlsplit
from isp_geofeed_generator.client import GeofeedError, Sonar
from isp_geofeed_generator.netbox import NetBox
from isp_geofeed_generator.splynx import Splynx
from isp_geofeed_generator.phpipam import PhpIPAM
from isp_geofeed_generator.feed import build


class HTTP:
    def __init__(self, replies): self.replies, self.calls = list(replies), []
    def request(self, url, **kwargs):
        self.calls.append((url, kwargs)); return self.replies.pop(0)


def page(rows, total=None, following=None):
    return {'count':len(rows) if total is None else total, 'results':rows, 'next':following}


SITE = {'id':10,'name':'Example site','custom_fields':{
    'geofeed_country':'US','geofeed_region':'US-IL','geofeed_city':'Example City'}}
PREFIX = {'id':1,'prefix':'11.22.33.0/24','scope_type':'dcim.site','scope_id':10,
          'status':{'value':'active'},'vrf':None,'tags':[{'slug':'geofeed'}]}


class NetBoxTests(unittest.TestCase):
    def test_compatible_default_auth_header_and_explicit_override(self):
        self.assertEqual(NetBox('https://example.net', 'fake-token').headers['Authorization'], 'Token fake-token')
        self.assertEqual(NetBox('https://example.net', 'fake-token', {'auth_scheme': 'Bearer'}).headers['Authorization'], 'Bearer fake-token')
        class Denied:
            def request(self, *args, **kwargs): raise GeofeedError('HTTP 401; private upstream payload')
        with self.assertRaisesRegex(GeofeedError, 'NetBox authentication') as result:
            NetBox('https://example.net', 'fake-token', http=Denied()).pages('/dcim/sites/')
        self.assertNotIn('private', str(result.exception))

    def source(self, prefixes=None, ranges=None, sites=None, settings=None, locations=None):
        responses = [page([PREFIX] if prefixes is None else prefixes),page(ranges or []),page([SITE] if sites is None else sites)]
        if locations is not None: responses.append(page(locations))
        return NetBox('https://netbox.example.net','example-token',settings or {'prefix_ids':['1']},HTTP(responses))

    def test_native_site_scope_generates_without_manual_pool_mapping(self):
        source=self.source(); snapshot=source.for_publication(source.snapshot())
        csv,report=build(snapshot,{'allowed_prefixes':['11.22.33.0/24']})
        self.assertEqual(csv,b'11.22.33.0/24,US,US-IL,Example City,\n')
        self.assertEqual(report[0]['mapping_source'],'native_scope')

    def test_location_scope_resolves_site_and_legacy_site_is_supported(self):
        for prefix,locations in [({**PREFIX,'scope_type':'dcim.location','scope_id':5},[{'id':5,'site':{'id':10}}]),
                                 ({**PREFIX,'scope_type':None,'scope_id':None,'site':{'id':10}},None)]:
            source=self.source(prefixes=[prefix],locations=locations)
            self.assertEqual(source.snapshot()['pools'][0]['site_id'],'10')

    def test_range_uses_most_specific_parent_and_same_vrf(self):
        broad={**PREFIX,'id':2,'prefix':'11.22.0.0/16','scope_id':99}
        row={'id':1,'start_address':'11.22.33.2/24','end_address':'11.22.33.6/24','vrf':None,'status':{'value':'active'}}
        source=self.source(prefixes=[broad,PREFIX],ranges=[row],settings={'range_ids':['1']})
        snapshot=source.for_publication(source.snapshot())
        self.assertEqual(snapshot['pools'][0]['site_id'],'10')
        csv,_=build(snapshot,{'allowed_prefixes':['11.22.33.0/24']})
        self.assertEqual(len(csv.splitlines()),3)
        source=self.source(ranges=[{**row,'vrf':{'id':7}}],settings={'range_ids':['1'],'vrf_ids':['7']})
        self.assertIsNone(source.snapshot()['pools'][-1]['site_id'])

    def test_ambiguous_parent_does_not_pick_first(self):
        duplicate={**PREFIX,'id':2,'scope_id':99}
        row={'id':1,'start_address':'11.22.33.2/24','end_address':'11.22.33.6/24','status':{'value':'active'}}
        source=self.source(prefixes=[PREFIX,duplicate],ranges=[row])
        self.assertIn('ambiguous',source.snapshot()['pools'][-1]['scope_error'])

    def test_missing_scope_and_missing_geo_are_configuration_gaps(self):
        for prefix,site in [({**PREFIX,'scope_type':None,'scope_id':None},SITE),(PREFIX,{**SITE,'custom_fields':{}})]:
            source=self.source(prefixes=[prefix],sites=[site])
            snapshot=source.for_publication(source.snapshot())
            with self.assertRaises(GeofeedError): build(snapshot,{'allowed_prefixes':['11.22.33.0/24']})

    def test_publication_requires_selection_and_active_global_by_default(self):
        source=self.source(settings={'type':'netbox'})
        with self.assertRaisesRegex(GeofeedError,'Select NetBox'): source.for_publication(source.snapshot())
        for prefix in ({**PREFIX,'status':{'value':'reserved'}},{**PREFIX,'vrf':{'id':7}}):
            source=self.source(prefixes=[prefix])
            with self.assertRaisesRegex(GeofeedError,'No NetBox'): source.for_publication(source.snapshot())
        source=self.source(settings={'tag':'geofeed'})
        self.assertEqual(len(source.for_publication(source.snapshot())['pools']),1)

    def test_next_page_cannot_receive_credentials_off_origin(self):
        http=HTTP([page([{'id':1}],2,'https://other.example.net/api/dcim/sites/?offset=1')])
        source=NetBox('https://netbox.example.net','example-token',http=http)
        with self.assertRaisesRegex(GeofeedError,'outside'):source.pages('/dcim/sites/')
        self.assertEqual(len(http.calls),1)

    def test_pagination_duplicates_and_empty_inventory_fail(self):
        for replies in ([page([{'id':1}],2)], [page([{'id':1}],2,'https://netbox.example.net/api/dcim/sites/?offset=1'),page([{'id':1}],2)],
                        [page([{'id':1}],2,'https://netbox.example.net/api/dcim/sites/?offset=1'),page([{'id':2}],3)]):
            with self.assertRaises(GeofeedError):NetBox('https://netbox.example.net','example-token',http=HTTP(replies)).pages('/dcim/sites/')
        with self.assertRaisesRegex(GeofeedError,'not measured'):self.source(prefixes=[]).snapshot()

    def test_plain_http_requires_explicit_exception(self):
        with self.assertRaises(GeofeedError):NetBox('http://netbox.example.net','example-token')
        NetBox('http://netbox.example.net','example-token',{'allow_http':True})


class InitialAdapterTests(unittest.TestCase):
    def test_splynx_signature_and_pagination(self):
        http=HTTP([[{'id':1}],[{'id':2}],[]])
        source=Splynx('https://billing.example.net','test-key','test-secret',http=http)
        self.assertEqual(len(source.pages('/admin/networking/ipv4')),2)
        headers=[call[1]['headers']['Authorization'] for call in http.calls]
        self.assertEqual(len(set(headers)),3)
        for value in headers:
            values=parse_qs(value[len('Splynx-EA ('):-1]); nonce=values['nonce'][0]
            expected=hmac.new(b'test-secret',(nonce+'test-key').encode(),hashlib.sha256).hexdigest().upper()
            self.assertEqual(values['signature'][0],expected)
        self.assertNotIn('test-secret',repr(http.calls))
        self.assertEqual(parse_qs(urlsplit(http.calls[1][0]).query)['offset'],['1'])

    def test_splynx_uses_reviewed_location_mapping_not_name_guess(self):
        ipv4={'id':1,'network':'11.22.33.0','mask':24,'location_id':9,'network_type':'endnet','type_of_usage':'pool'}
        http=HTTP([[{'id':10,'title':'Example site'}],[],[ipv4],[],[]])
        source=Splynx('https://billing.example.net','test-key','test-secret',
                      {'network_ids':['ipv4:1'],'location_sites':{'9':'10'}},http)
        snapshot=source.for_publication(source.snapshot())
        config={'allowed_prefixes':['11.22.33.0/24'],'site_locations':{'10':{'country':'US','region':'US-IL','city':'Example City'}}}
        self.assertEqual(build(snapshot,config)[0],b'11.22.33.0/24,US,US-IL,Example City,\n')

    def test_splynx_duplicate_and_error_body_fail(self):
        for rows in ([[{'id':1}],[{'id':1}]], [{'error':{'message':'private server detail'}}]):
            with self.assertRaises(GeofeedError):Splynx('https://billing.example.net','key','secret',http=HTTP(rows)).pages('/admin/networking/ipv4')

    def test_phpipam_decimal_prefix_and_native_location(self):
        def ok(rows):return {'code':200,'success':True,'data':rows}
        http=HTTP([ok([{'id':'1','subnet':str(int(__import__('ipaddress').ip_address('11.22.33.0'))),'mask':'24','location':{'id':'10','address':'private street','lat':41.9,'long':-88.7},'isFolder':'0'}]),ok([{'id':'10','name':'Example site'}])])
        source=PhpIPAM('https://ipam.example.net','geofeed','example-token',{'subnet_ids':['1']},http)
        snapshot=source.for_publication(source.snapshot())
        config={'allowed_prefixes':['11.22.33.0/24'],'site_locations':{'10':{'country':'US','region':'US-IL','city':'Example City'}}}
        self.assertEqual(build(snapshot,config)[0],b'11.22.33.0/24,US,US-IL,Example City,\n')
        self.assertTrue(all(c[1]['method']=='GET' for c in http.calls))

    def test_phpipam_failure_is_not_an_empty_success(self):
        for reply in ({'success':False,'code':403,'data':[]},{'success':True,'code':200,'data':[{'id':1},{'id':1}]}):
            with self.assertRaises(GeofeedError):PhpIPAM('https://ipam.example.net','geofeed','token',http=HTTP([reply])).collection('/subnets/all/')

    def test_phpipam_unassigned_and_malformed_location_do_not_leak_details(self):
        def ok(rows): return {'code': 200, 'success': True, 'data': rows}
        for location in ([], {'id': 'private street', 'address': 'secret street'}):
            http = HTTP([ok([{'id': '1', 'subnet': '11.22.33.0', 'mask': '24', 'location': location}]), ok([])])
            source = PhpIPAM('https://ipam.example.net', 'geofeed', 'token', http=http)
            if location == []:
                self.assertIsNone(source.snapshot()['pools'][0]['site_id'])
            else:
                with self.assertRaises(GeofeedError) as result: source.snapshot()
                self.assertNotIn('private street', str(result.exception))
                self.assertNotIn('secret street', str(result.exception))


class ControllerTests(unittest.TestCase):
    def test_controller_ip_inventory_site_with_consistency_guard(self):
        class Source(Sonar):
            def pages(self,root,fields,**kwargs):
                if root=='dhcp_servers':return [{'id':'1','enabled':True,'serves_all_pools':False,'ip_address':'11.0.0.1','ip_pools':{'page_info':{'total_count':1},'entities':[{'id':'101'}]}}]
                if root=='inline_devices':return [{'id':'2','enabled':True,'all_subnets':False,'ip_address':'11.0.0.2','subnets':{'page_info':{'total_count':1},'entities':[{'id':'5'}]}}]
                ip=kwargs['variables']['ip']
                owner={'__typename':'InventoryModelFieldData','inventory_item':{'inventoryitemable_type':'Address',
                    'inventoryitemable':{'addressable_type':'NetworkSite','addressable_id':self.inline_site if ip.endswith('.2') else '10'}}}
                return [{'id':'3','subnet':ip,'ipassignmentable':owner}]
        source=Source('https://sonar.example.net','example-token')
        snapshot={'pools':[{'id':'101','subnet_id':'5'}],'sites':[{'id':'10'},{'id':'11'}]}
        source.inline_site='10'
        self.assertEqual(source.controller_candidates(snapshot)['101']['site_id'],'10')
        source.inline_site='11'
        result=source.controller_candidates(snapshot)['101']
        self.assertIsNone(result['site_id']);self.assertIn('conflicting',result['reason'])

    def test_global_controller_is_not_used_as_pool_host(self):
        class Source(Sonar):
            def pages(self,root,fields,**kwargs):
                if root=='dhcp_servers':return [{'id':'1','enabled':True,'serves_all_pools':True}]
                if root=='inline_devices':return []
                self.fail('Management-IP lookup should not be attempted')
        source=Source('https://sonar.example.net','example-token')
        result=source.controller_candidates({'pools':[{'id':'101','subnet_id':'5'}],'sites':[]})
        self.assertIsNone(result['101']['site_id'])
