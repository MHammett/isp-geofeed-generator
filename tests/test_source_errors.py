"""Actionable record IDs without source values or credential disclosure."""
import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import yaml

from isp_geofeed_generator.client import GeofeedError, Sonar
from isp_geofeed_generator.cli import main
from isp_geofeed_generator.splynx import Splynx
from isp_geofeed_generator.phpipam import PhpIPAM
from test_client import FakeHTTP
from test_sources import HTTP
from test_sonar_subnets import Fixture, SITE, POOL, connection, inline, settings

PRIVATE='private-source-value'


def page(root,rows,**changes):
    return {'data':{root:{'entities':rows,'page_info':{
        'page':1,'total_pages':1,'total_count':len(rows),**changes}}}}


def ok(rows):return {'success':True,'code':200,'data':rows}


def dhcp(**changes):
    return {'id':'3','enabled':True,'serves_all_pools':False,'ip_address':PRIVATE,
            'ip_pools':connection([{'id':'101'}]),**changes}


class SourceErrors(unittest.TestCase):
    def check_error(self,call,label):
        with self.assertRaises(GeofeedError) as caught:call()
        message=str(caught.exception)
        self.assertIn(label,message)
        self.assertNotIn(PRIVATE,message)
        self.assertNotIn('synthetic-token',message)
        return message

    def test_sonar_dhcp_invalid_or_missing_management_ip_names_server(self):
        for changes in ({},{'ip_address':None},{'ip_address':{} }):
            source=Fixture({'site_resolution':'controllers'})
            source.rows['dhcp_servers']=[dhcp(**changes)]
            self.check_error(source.snapshot,'Sonar DHCP server 3')

    def test_sonar_inline_bad_flags_and_links_name_device(self):
        for changes in ({'enabled':PRIVATE},{'subnets':None},
                        {'subnets':connection([{'id':'101'}],PRIVATE)}):
            source=Fixture(settings(),controllers=[inline('7',**changes)])
            self.check_error(source.snapshot,'Sonar inline device 7')

    def test_sonar_assignment_prefix_and_inventory_shape_name_assignment(self):
        for changes in ({'subnet':PRIVATE},{'ipassignmentable':[PRIVATE]},
                        {'ipassignmentable':{'__typename':'NetworkSite'}},
                        {'ipassignmentable':{'__typename':'InventoryItem','inventoryitemable_type':'Address','inventoryitemable':[PRIVATE]}}):
            assignment={'id':'701','subnet':'2001:4860::1','ipassignmentable':{},**changes}
            source=Fixture(settings(),owners={'2001:4860::1':[assignment]})
            self.check_error(source.snapshot,'Sonar IP assignment 701')

    def test_sonar_site_bad_address_connection_names_site(self):
        for value in (None,{'entities':[],'page_info':{'total_count':PRIVATE}}):
            source=Fixture();source.rows['network_sites']=[{**SITE,'addresses':value}]
            self.check_error(source.snapshot,'Sonar network site 11')

    def test_sonar_nested_controller_metadata_names_parent(self):
        source=Fixture(settings(),controllers=[inline('7',subnets=connection([{'id':'101'}],2))])
        source.http=FakeHTTP([{'data':{'inline_devices':{'entities':[{'id':'7','subnets':{
            'page_info':{'page':1,'total_pages':2,'total_count':PRIVATE},'entities':[]}}]}}}])
        self.check_error(source.snapshot,'Sonar inline device 7')

    def test_sonar_collection_bad_ids_are_not_echoed(self):
        for row in ({'id':PRIVATE},{'id':{'secret':PRIVATE}},None,{'id':True},{'id':1.0},{'id':10**21}):
            source=Sonar('https://example.net','synthetic-token',http=FakeHTTP([page('ip_pools',[row])]))
            self.check_error(lambda:source.pages('ip_pools','id'),'Sonar ip_pools')

    def test_sonar_pagination_error_names_collection_and_page(self):
        for value in (PRIVATE,None,float('inf')):
            source=Sonar('https://example.net','synthetic-token',http=FakeHTTP([page('ip_pools',[],total_count=value)]))
            message=self.check_error(lambda:source.pages('ip_pools','id'),'Sonar ip_pools')
            self.assertIn('page 1',message)

    def test_splynx_bad_ipv4_network_fields_name_network(self):
        for changes in ({'network':PRIVATE},{'mask':None},{'mask':PRIVATE}):
            row={'id':42,'network':'11.22.33.0','mask':24,**changes}
            source=Splynx('https://example.net','key','secret',http=HTTP([[],[row],[]]))
            self.check_error(source.snapshot,'Splynx IPv4 network 42')

    def test_splynx_bad_ipv6_range_fields_name_network(self):
        for changes in ({'prefix':None},{'range_from':PRIVATE,'range_to':None},
                        {'range_from':{},'range_to':'2001:4860::2'},
                        {'range_from':{},'range_to':{}},
                        {'range_from':'2001:4860::2','range_to':'2001:4860::1'},
                        {'range_from':'2001:4860::1','range_to':'2001:4861::1'},
                        {'range_from':PRIVATE,'range_to':'2001:4860::2'}):
            row={'id':'43','network':'2001:4860::','prefix':32,**changes}
            source=Splynx('https://example.net','key','secret',http=HTTP([[],[],[row],[]]))
            self.check_error(source.snapshot,'Splynx IPv6 network 43')

    def test_splynx_valid_ipv6_ranges_still_build_exact_coverage(self):
        from isp_geofeed_generator.feed import build,parse_feed
        row={'id':'43','network':'2001:4860::','prefix':32,'range_from':'2001:4860::2',
             'range_to':'2001:4860::e','network_type':'endnet','type_of_usage':'pool'}
        source=Splynx('https://example.net','key','secret',{'network_ids':['ipv6:43']},
                      HTTP([[{'id':'10'}],[],[],[row],[]]))
        snap=source.for_publication(source.snapshot())
        data,_=build(snap,{'allowed_prefixes':['2001:4860::/32'],'pool_sites':{'ipv6:43':'10'},
                           'site_locations':{'10':{'country':'US','region':'US-IL','city':'Example City'}}})
        self.assertEqual(sum(net.num_addresses for net in parse_feed(data)),13)

    def test_sonar_discovery_nested_metadata_names_owning_record(self):
        direct=connection([{'id':'701','ip_pool_id':'101'}])
        field={'id':'55','ip_assignments':connection([])}
        item={'id':'44','ip_assignments':connection([]),'inventory_model_field_data':connection([field])}
        site={'id':'11','ip_assignments':direct,'inventory_items':connection([item])}
        for kind in ('site','item','field','assignment'):
            row=copy.deepcopy(site)
            if kind=='site':row['inventory_items']=None;label='Sonar network site 11'
            elif kind=='item':
                row['inventory_items']['entities'][0]['inventory_model_field_data']=None;label='Sonar inventory item 44'
            elif kind=='field':
                row['inventory_items']['entities'][0]['inventory_model_field_data']['entities'][0]['ip_assignments']=None
                label='Sonar inventory field 55'
            else:
                del row['ip_assignments']['entities'][0]['ip_pool_id'];label='Sonar IP assignment 701'
            source=Sonar('https://example.net','synthetic-token',http=FakeHTTP([page('network_sites',[row])]))
            with self.subTest(kind=kind):self.check_error(lambda:source.assignment_candidates([{'id':'11'}]),label)

    def test_phpipam_bad_subnet_fields_and_location_name_subnet(self):
        for changes in ({'subnet':PRIVATE},{'mask':None},{'mask':PRIVATE},
                        {'location':{'id':PRIVATE,'address':PRIVATE}}):
            row={'id':'12','subnet':'11.22.33.0','mask':'24',**changes}
            source=PhpIPAM('https://example.net','app','synthetic-token',http=HTTP([ok([row]),ok([])]))
            self.check_error(source.snapshot,'phpIPAM subnet 12')

    def test_splynx_and_phpipam_duplicates_and_bad_ids_have_safe_context(self):
        for kind in ('splynx','phpipam'):
            for rows,identifier in (([{'id':'42'},{'id':'42'}],'42'),([{'id':PRIVATE}],'(unknown ID)'),
                                    ([{'id':{PRIVATE:PRIVATE}}],'(unknown ID)')):
                if kind=='splynx':
                    source=Splynx('https://example.net','key','secret',http=HTTP([rows]))
                    call=lambda:source.pages('/admin/networking/ipv4');label='Splynx IPv4 network '
                else:
                    source=PhpIPAM('https://example.net','app','synthetic-token',http=HTTP([ok(rows)]))
                    call=lambda:source.collection('/subnets/all/');label='phpIPAM subnet '
                self.check_error(call,label+identifier)

    def test_cli_source_failures_record_id_and_keep_feed_and_recovery_untouched(self):
        for kind in ('sonar','splynx','phpipam'):
            with self.subTest(source=kind),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);state=root/'state';state.mkdir()
                target=root/'feed.csv';target.write_bytes(b'last feed sentinel')
                backup=state/'before.csv';backup.write_bytes(b'recovery sentinel')
                options={'type':kind,'allow_initial':True}
                if kind=='sonar':
                    options['site_resolution']='controllers';label='Sonar DHCP server 3'
                    replies=[page('ip_pools',[copy.deepcopy(POOL)]),page('network_sites',[copy.deepcopy(SITE)]),page('dhcp_servers',[dhcp()])]
                elif kind=='splynx':
                    options['network_ids']=['ipv4:42'];label='Splynx IPv4 network 42'
                    replies=[[],[{'id':'42','network':PRIVATE,'mask':24}],[]]
                else:
                    options.update({'subnet_ids':['12'],'app_id':'app'});label='phpIPAM subnet 12'
                    replies=[ok([{'id':'12','subnet':PRIVATE,'mask':24}]),ok([])]
                config={'source':options,'state_dir':str(state),'allowed_prefixes':['11.22.33.0/24'],
                        'publish':{'type':'file','path':str(target)}}
                path=root/'config.yaml';path.write_text(yaml.safe_dump(config))
                env={key:'synthetic-token' for key in ('SONAR_API_TOKEN','SPLYNX_API_KEY','SPLYNX_API_SECRET','PHPIPAM_API_TOKEN')}
                env.update({key:'https://example.net' for key in ('SONAR_URL','SPLYNX_URL','PHPIPAM_URL')})
                errors=io.StringIO();http=HTTP(replies)
                with patch.dict('os.environ',env),patch('isp_geofeed_generator.client.JsonHTTP.request',side_effect=http.request),contextlib.redirect_stderr(errors):
                    self.assertEqual(main(['publish','--config',str(path)]),1)
                status=json.loads((state/'status.json').read_bytes())['data']
                self.assertFalse(status['healthy']);self.assertIn(label,status['error'])
                self.assertIn(label,errors.getvalue());self.assertNotIn(PRIVATE,errors.getvalue()+status['error'])
                self.assertEqual(target.read_bytes(),b'last feed sentinel')
                self.assertEqual(backup.read_bytes(),b'recovery sentinel')
