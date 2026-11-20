"""Explicit alternate NetBox geography models, without hierarchy guesses."""
import copy
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit
import yaml
from isp_geofeed_generator.client import GeofeedError
from isp_geofeed_generator.netbox import NetBox
from isp_geofeed_generator.feed import build,parse_feed
from isp_geofeed_generator.cli import main,load_config
from bogon_fixture import policy
from test_sources import PREFIX,page

FIELDS={'geofeed_country':'US','geofeed_region':'US-IL','geofeed_city':'Example City'}
REGIONS=[{'id':1,'name':'US','parent':None},{'id':2,'name':'US-IL','parent':{'id':1}},
         {'id':3,'name':'Example City','parent':{'id':2}}]
CONFIG={'allowed_prefixes':['11.22.33.0/24']}


class API:
    def __init__(self,prefixes=None,ranges=None,regions=None):
        self.calls=[];self.rows={'/api/ipam/prefixes/':prefixes or [{**PREFIX,'custom_fields':copy.deepcopy(FIELDS)}],
            '/api/ipam/ip-ranges/':ranges or [],'/api/dcim/regions/':copy.deepcopy(REGIONS if regions is None else regions)}
    def request(self,url,**kwargs):
        self.calls.append((url,kwargs));path=urlsplit(url).path
        if path not in self.rows:raise AssertionError('Unexpected endpoint '+path)
        return page(copy.deepcopy(self.rows[path]))


def source(mode,**kwargs):
    api=API(**{key:kwargs.pop(key) for key in list(kwargs) if key in ('prefixes','ranges','regions')})
    item=NetBox('https://netbox.example.net','synthetic-token',{'location_mode':mode,'prefix_ids':['1'],**kwargs},api)
    return item,api


class NetBoxModels(unittest.TestCase):
    def generate(self,item):return build(item.for_publication(item.snapshot()),CONFIG)[0]

    def test_prefix_fields_publish_without_site_scope_or_site_permissions(self):
        item,api=source('prefix_fields',prefixes=[{**PREFIX,'scope_type':None,'scope_id':None,'custom_fields':FIELDS}])
        self.assertEqual(self.generate(item),b'11.22.33.0/24,US,US-IL,Example City,\r\n')
        self.assertEqual(len(api.calls),2)
        self.assertTrue(all('/ipam/' in url for url,_ in api.calls))

    def test_geobox_field_values_and_explicit_enable_flag_are_supported(self):
        row={**PREFIX,'custom_fields':{'geoloc_country':{'value':'US','label':'Display only'},
            'geoloc_region':'US-IL','geoloc_city':'Example City','geoloc_has_location':True}}
        item,_=source('prefix_fields',prefixes=[row],location_fields={
            'country':'geoloc_country','region':'geoloc_region','city':'geoloc_city'},location_enabled_field='geoloc_has_location')
        self.assertIn(b',US,US-IL,Example City,',self.generate(item))

    def test_disabled_or_missing_geobox_flag_stops_selected_prefix(self):
        for value in (False,None,'false'):
            item,_=source('prefix_fields',prefixes=[{**PREFIX,'custom_fields':{**FIELDS,'enabled':value}}],location_enabled_field='enabled')
            with self.subTest(value=value),self.assertRaises(GeofeedError):self.generate(item)

    def test_missing_prefix_fields_never_inherit_from_broader_prefix(self):
        broad={**PREFIX,'id':2,'prefix':'11.22.0.0/16','custom_fields':FIELDS}
        item,_=source('prefix_fields',prefixes=[broad,{**PREFIX,'custom_fields':{}}])
        with self.assertRaises(GeofeedError):self.generate(item)

    def test_prefix_field_country_region_conflicts_and_invalid_iso_fail(self):
        for changes in ({'geofeed_region':'GB-ENG'},{'geofeed_country':'XX'},{'geofeed_city':None}):
            item,_=source('prefix_fields',prefixes=[{**PREFIX,'custom_fields':{**FIELDS,**changes}}])
            with self.subTest(changes=changes),self.assertRaises(GeofeedError):self.generate(item)

    def test_malformed_prefix_custom_fields_report_safe_record_context(self):
        for fields in ([],False,'private upstream fields'):
            item,_=source('prefix_fields',prefixes=[{**PREFIX,'custom_fields':fields}])
            with self.subTest(fields=fields),self.assertRaises(GeofeedError) as caught:self.generate(item)
            self.assertIn('prefix 1',str(caught.exception));self.assertNotIn('private',str(caught.exception))

    def test_region_hierarchy_uses_exact_country_state_city_chain(self):
        item,api=source('region_hierarchy',prefixes=[{**PREFIX,'scope_type':'dcim.region','scope_id':3}])
        self.assertIn(b',US,US-IL,Example City,',self.generate(item))
        self.assertEqual(len(api.calls),3)
        self.assertTrue(api.calls[-1][0].startswith('https://netbox.example.net/api/dcim/regions/'))

    def test_region_hierarchy_cycle_missing_parent_and_wrong_depth_stop(self):
        for rows in (REGIONS[:2],[{**REGIONS[0],'parent':{'id':3}},*REGIONS[1:]],
                     [REGIONS[0],{**REGIONS[2],'parent':{'id':1}}],
                     [{**REGIONS[0],'parent':{'id':4}},*REGIONS[1:],{'id':4,'name':'Continent','parent':None}]):
            item,_=source('region_hierarchy',prefixes=[{**PREFIX,'scope_type':'dcim.region','scope_id':3}],regions=rows)
            with self.subTest(rows=rows),self.assertRaises(GeofeedError):self.generate(item)

    def test_region_hierarchy_does_not_guess_country_names_or_scope_conflicts(self):
        for prefix,regions in (({**PREFIX,'scope_type':'dcim.region','scope_id':3},[{**REGIONS[0],'name':'United States'},*REGIONS[1:]]),
                               ({**PREFIX,'scope_type':'dcim.region','scope_id':3,'scope':{'id':2}},REGIONS),
                               (PREFIX,REGIONS)):
            item,_=source('region_hierarchy',prefixes=[prefix],regions=regions)
            with self.assertRaises(GeofeedError):self.generate(item)

    def test_unselected_unresolved_region_is_visible_but_not_published(self):
        good={**PREFIX,'scope_type':'dcim.region','scope_id':3}
        bad={**PREFIX,'id':2,'prefix':'11.22.34.0/24','scope_type':'dcim.region','scope_id':999}
        item,_=source('region_hierarchy',prefixes=[good,bad])
        snapshot=item.snapshot()
        self.assertTrue(snapshot['pools'][1]['scope_error'])
        selected=item.for_publication(snapshot)
        self.assertEqual([p['id'] for p in selected['pools']],['prefix:1'])
        self.assertEqual(len(parse_feed(build(selected,CONFIG)[0])),1)

    def test_ranges_use_most_specific_same_vrf_parent_in_selected_mode(self):
        row={'id':9,'start_address':'11.22.33.2/24','end_address':'11.22.33.6/24','status':{'value':'active'},'vrf':None}
        for mode,prefix in (('prefix_fields',{**PREFIX,'custom_fields':FIELDS}),
                            ('region_hierarchy',{**PREFIX,'scope_type':'dcim.region','scope_id':3})):
            item,_=source(mode,prefixes=[prefix],ranges=[row],prefix_ids=[],range_ids=['9'])
            data=self.generate(item)
            self.assertEqual(sum(n.num_addresses for n in parse_feed(data)),5)
            wrong,_=source(mode,prefixes=[prefix],ranges=[{**row,'vrf':{'id':7}}],prefix_ids=[],range_ids=['9'],vrf_ids=['7'])
            with self.assertRaises(GeofeedError):self.generate(wrong)

    def test_both_modes_publish_exact_ipv6_ranges(self):
        parent={**PREFIX,'prefix':'2001:4860:1234::/48','custom_fields':FIELDS,'scope_type':'dcim.region','scope_id':3}
        row={'id':9,'start_address':'2001:4860:1234::2/64','end_address':'2001:4860:1234::6/64','status':{'value':'active'}}
        for mode in ('prefix_fields','region_hierarchy'):
            item,_=source(mode,prefixes=[parent],ranges=[row],prefix_ids=[],range_ids=['9'])
            data,_=build(item.for_publication(item.snapshot()),{'allowed_prefixes':['2001:4860::/32']})
            nets=parse_feed(data)
            self.assertTrue(all(net.version==6 for net in nets));self.assertEqual(sum(net.num_addresses for net in nets),5)

    def test_invalid_mode_or_field_configuration_fails_before_any_api_read(self):
        for options in ({'location_mode':'guess'},{'location_mode':'site','location_enabled_field':'enabled'},
                        {'location_mode':'region_hierarchy','location_fields':{'country':'custom'}},
                        {'location_mode':'prefix_fields','location_fields':{'country':[]}}):
            api=API()
            with self.subTest(options=options),self.assertRaises(GeofeedError):
                NetBox('https://example.net','synthetic-token',options,api)
            self.assertEqual(api.calls,[])

    def test_ranges_refuse_ambiguous_or_incomplete_closest_parent(self):
        row={'id':9,'start_address':'11.22.33.2/24','end_address':'11.22.33.6/24','status':{'value':'active'}}
        parent={**PREFIX,'custom_fields':FIELDS}
        for prefixes in ([parent,{**parent,'id':2}],
                         [{**parent,'id':2,'prefix':'11.22.0.0/16'},{**parent,'custom_fields':{}}]):
            item,_=source('prefix_fields',prefixes=prefixes,ranges=[row],prefix_ids=[],range_ids=['9'])
            with self.assertRaises(GeofeedError):self.generate(item)

    def test_cli_modes_publish_and_failure_keeps_feed_and_backup(self):
        for mode in ('prefix_fields','region_hierarchy'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);target=root/'feed.csv';state=root/'state';path=root/'config.yaml'
                rows=[{**PREFIX,'custom_fields':copy.deepcopy(FIELDS),'scope_type':'dcim.region','scope_id':3}]
                api=API(prefixes=rows)
                config={'source':{'type':'netbox','location_mode':mode,'prefix_ids':['1']},
                    **CONFIG,'state_dir':str(state),'publish':{'type':'file','path':str(target)}}
                path.write_text(yaml.safe_dump(config))
                errors=io.StringIO()
                with patch.dict('os.environ',{'NETBOX_URL':'https://netbox.example.net','NETBOX_API_TOKEN':'synthetic-token'}), \
                     patch('isp_geofeed_generator.client.JsonHTTP.request',side_effect=api.request), \
                     patch('isp_geofeed_generator.cli.load_policy',side_effect=lambda c:policy()), \
                     contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(errors):
                    self.assertEqual(main(['publish','--config',str(path)]),0,errors.getvalue())
                    before=target.read_bytes();backup=(state/'before.csv').read_bytes()
                    if mode=='prefix_fields':api.rows['/api/ipam/prefixes/'][0]['custom_fields']={}
                    else:api.rows['/api/dcim/regions/']=[]
                    self.assertEqual(main(['publish','--config',str(path)]),1)
                self.assertEqual(target.read_bytes(),before);self.assertEqual((state/'before.csv').read_bytes(),backup)
                self.assertFalse(json.loads((state/'status.json').read_bytes())['data']['healthy'])
