import base64
import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit
import yaml
from isp_geofeed_generator.adapters import SOURCES
from isp_geofeed_generator.client import GeofeedError
from isp_geofeed_generator.cli import main
from isp_geofeed_generator.credentials import CredentialStore, InputCredentialStore
from isp_geofeed_generator.feed import build, parse_feed
from isp_geofeed_generator.infoblox_nios import InfobloxNIOS, normalized_id
from bogon_fixture import policy
from test_sources import HTTP

V4 = 'network/opaque-v4:11.22.33.0/24/external'
V6 = 'ipv6network/opaque-v6:2001%3A4860%3A1234%3A%3A/126/external'


def network(ref=V4, prefix='11.22.33.0/24', view='external'):
    return {'_ref':ref, 'network':prefix, 'network_view':view, 'extattrs':{
        'geofeed_country':{'value':'US'}, 'geofeed_region':{'value':'US-IL'},
        'geofeed_city':{'value':'Example City'}, 'unrelated-password':{'value':'private-secret'}},
        'comment':'private-comment', 'members':['private-member']}


def page(rows, cursor=None):
    result={'result':rows}
    if cursor is not None:result['next_page_id']=cursor
    return result


class NIOSTests(unittest.TestCase):
    def source(self, replies=None, settings=None):
        http=HTTP([page([network()])] if replies is None else replies)
        return InfobloxNIOS('https://example.net/wapi/v2.13.6','reader','synthetic-password',
            settings if settings is not None else {'network_refs':[V4]},http),http

    def test_dual_stack_exact_coverage_and_attribute_projection(self):
        source,http=self.source([page([network()]),page([network(V6,'2001:4860:1234::/126')])],{'network_refs':[V4,V6]})
        snapshot=source.for_publication(source.snapshot())
        data,_=build(snapshot,{'allowed_prefixes':['11.22.33.0/24','2001:4860:1234::/48']})
        nets=parse_feed(data)
        self.assertEqual([(n.version,n.num_addresses) for n in nets],[(4,256),(6,4)])
        self.assertNotIn('private-',json.dumps(snapshot))
        self.assertEqual(snapshot['pools'][0]['source_id'],V4)
        self.assertEqual(snapshot['pools'][0]['network_view'],'external')
        self.assertEqual(http.calls[0][1],{'headers':{'Authorization':'Basic '+base64.b64encode(b'reader:synthetic-password').decode()},'method':'GET'})
        self.assertNotIn('synthetic-password',http.calls[0][0])
        self.assertEqual(parse_qs(urlsplit(http.calls[0][0]).query),{'_paging':['1'],'_return_as_object':['1'],'_max_results':['100'],
            '_return_fields':['network,network_view,extattrs']})

    def test_page_token_is_data_and_continuation_stays_on_configured_endpoint(self):
        token='https://foreign.example/secret?a=b&x=y'
        other=network('network/second:11.22.34.0/24/external','11.22.34.0/24')
        source,http=self.source([page([network()],token),page([other])])
        self.assertEqual(len(source.snapshot()['pools']),2)
        follow=urlsplit(http.calls[1][0])
        self.assertEqual((follow.netloc,follow.path),('example.net','/wapi/v2.13.6/network'))
        self.assertEqual(parse_qs(follow.query),{'_page_id':[token]})

    def test_percent_encoded_view_names_preserve_opaque_selection(self):
        refs=[ref.rsplit('/',1)[0]+'/Company%201' for ref in (V4,V6)]
        source,http=self.source([page([network(refs[0],view='Company 1')]),
            page([network(refs[1],'2001:4860:1234::/126',view='Company 1')])],{'network_refs':refs})
        snapshot=source.for_publication(source.snapshot())
        self.assertEqual({p['source_id'] for p in snapshot['pools']},set(refs))
        self.assertEqual({p['network_view'] for p in snapshot['pools']},{'Company 1'})
        data,_=build(snapshot,{'allowed_prefixes':['11.22.33.0/24','2001:4860:1234::/48']})
        self.assertEqual([(n.version,n.num_addresses) for n in parse_feed(data)],[(4,256),(6,4)])
        self.assertEqual(len(http.calls),2)
        # Negative controls: a decoded reference is not an accepted substitute,
        # either in config or among the returned inventory records.
        raw=refs[0].replace('%20',' ')
        with self.assertRaises(GeofeedError):self.source(settings={'network_refs':[raw]})
        source,_=self.source([page([network(raw,view='Company 1')])],{'network_refs':[refs[0]]})
        with self.assertRaises(GeofeedError):source.snapshot()

    def test_repeated_token_duplicate_reference_bad_or_empty_intermediate_page_fails(self):
        other=network('network/second:11.22.34.0/24/external','11.22.34.0/24')
        for replies in ([{}],[[]],[{'result':{}}],[page([None])],[page([network()]*101)],
                        [page([network()],'same'),page([other],'same')],
                        [page([network()],'next'),page([network()])],[page([],'next')],
                        [{'result':[network()],'next_page_id':''}],
                        [{'result':[network()],'next_page_id':True}]):
            source,_=self.source(replies)
            with self.subTest(replies=replies),self.assertRaises(GeofeedError):source.snapshot()
        source,_=self.source([page([network()],'next')])
        with patch('isp_geofeed_generator.infoblox_nios.MAX_PAGES',1),self.assertRaisesRegex(GeofeedError,'page limit'):source.snapshot()

    def test_empty_inventory_and_missing_selection_are_not_healthy(self):
        source,_=self.source([page([])])
        with self.assertRaisesRegex(GeofeedError,'zero networks; not measured'):source.snapshot()
        source,_=self.source([page([network()]),page([])],{})
        snapshot=source.snapshot()
        with self.assertRaisesRegex(GeofeedError,'network_refs'):source.for_publication(snapshot)
        source,_=self.source([page([network()])],{'network_refs':[V4,'network/missing:11.22.34.0/24/external']})
        with self.assertRaisesRegex(GeofeedError,'missing or inaccessible'):source.for_publication(source.snapshot())

    def test_total_inventory_budget_and_oversize_declared_values_fail(self):
        source,_=self.source([page([network()]),page([network(V6,'2001:4860:1234::/126')])],{'network_refs':[V4,V6]})
        with patch('isp_geofeed_generator.infoblox_nios.MAX_RECORDS',1),self.assertRaisesRegex(GeofeedError,'record limit'):source.snapshot()
        row=network();row['extattrs']['geofeed_city']['value']='x'*513
        source,_=self.source([page([row])]);snapshot=source.snapshot()
        self.assertNotIn('x'*513,json.dumps(snapshot))
        with self.assertRaisesRegex(GeofeedError,'geography attribute'):source.for_publication(snapshot)

    def test_selected_family_only_and_identical_prefix_in_two_views_conflicts(self):
        source,http=self.source()
        source.snapshot();self.assertEqual(len(http.calls),1)
        otherref='network/another:11.22.33.0/24/another-view'
        source,_=self.source([page([network(),network(otherref,view='another-view')])],{'network_refs':[V4,otherref]})
        snapshot=source.for_publication(source.snapshot())
        self.assertNotEqual(snapshot['pools'][0]['id'],snapshot['pools'][1]['id'])
        with self.assertRaises(GeofeedError):build(snapshot,{'allowed_prefixes':['11.22.33.0/24']})

    def test_explicit_field_names_and_inherited_values_without_parent_fetch(self):
        row=network();row['extattrs']={'Country':{'value':'US','inheritance_source':'network/private-parent'},
            'State':{'value':'US-CA'},'City':{'value':'Reviewed City'}}
        source,http=self.source([page([row])],{'network_refs':[V4],'location_fields':{'country':'Country','region':'State','city':'City'}})
        data,_=build(source.for_publication(source.snapshot()),{'allowed_prefixes':['11.22.33.0/24']})
        self.assertIn(b',US,US-CA,Reviewed City,',data)
        self.assertEqual(len(http.calls),1)

    def test_bad_attribute_container_stops_selected_and_is_visible_for_unselected(self):
        for bad in (None,[],True,{'geofeed_country':True},{'geofeed_country':{'value':False}}):
            row=network();row['extattrs']=bad
            source,_=self.source([page([row])]);snapshot=source.snapshot()
            self.assertTrue(snapshot['pools'][0]['location_error'])
            with self.assertRaisesRegex(GeofeedError,'geography attribute'):source.for_publication(snapshot)
            other=copy.deepcopy(row);other['_ref']='network/unselected:11.22.34.0/24/external';other['network']='11.22.34.0/24'
            source,_=self.source([page([network(),other])])
            self.assertEqual(len(source.for_publication(source.snapshot())['pools']),1)

    def test_missing_or_wrong_geography_fails_build_and_explicit_override_can_supply_missing_values(self):
        row=network();row['extattrs']={}
        source,_=self.source([page([row])]);snapshot=source.for_publication(source.snapshot())
        with self.assertRaises(GeofeedError):build(snapshot,{'allowed_prefixes':['11.22.33.0/24']})
        sid=snapshot['sites'][0]['id']
        data,_=build(snapshot,{'allowed_prefixes':['11.22.33.0/24'],'site_locations':{sid:{'country':'US','region':'US-IL','city':'Reviewed City'}}})
        self.assertIn(b'Reviewed City',data)
        row=network();row['extattrs']['geofeed_country']['value']='XX'
        source,_=self.source([page([row])])
        with self.assertRaises(GeofeedError):build(source.snapshot(),{'allowed_prefixes':['11.22.33.0/24']})

    def test_malformed_boundary_reference_or_view_errors_do_not_echo_values(self):
        for update in ({'network':'private-bad-prefix'},{'network':'11.22.33.1/24'},{'network':'2001:4860::/48'},
                       {'_ref':'private-bad-ref'},{'_ref':False},{'_ref':'ipv6network/wrong-family'},
                       {'network_view':False},{'network_view':'private\nview'}):
            row=network();row.update(update);source,_=self.source([page([row])])
            with self.subTest(update=update),self.assertRaises(GeofeedError) as error:source.snapshot()
            self.assertNotIn('private-',str(error.exception))

    def test_settings_url_auth_and_credential_scope(self):
        for settings in ({'network_refs':V4},{'network_refs':[V4,V4]},{'network_refs':[False]},
                         {'location_fields':{'postal_code':'Postal'}},{'location_fields':{'city':'bad\nname'}},
                         {'location_fields':{'city':'geofeed_country'}}):
            with self.subTest(settings=settings),self.assertRaises(GeofeedError):self.source(settings=settings)
        for url in ('http://example.net/wapi/v2.13.6','https://example.net/wapi/v2.12','https://key@example.net/wapi/v2.13.6'):
            with self.assertRaises(GeofeedError):InfobloxNIOS(url,'reader','password')
        with self.assertRaises(GeofeedError):InfobloxNIOS('https://example.net/wapi/v2.13.6','bad:reader','password')
        credentials=Mock();credentials.get.return_value='synthetic-value'
        with patch.dict('os.environ',{'INFOBLOX_NIOS_URL':'https://example.net/wapi/v2.13.6'}):SOURCES['infoblox_nios'].create({},credentials)
        self.assertEqual({c.args[0] for c in credentials.get.call_args_list},{'INFOBLOX_NIOS_USERNAME','INFOBLOX_NIOS_PASSWORD'})
        parent=CredentialStore(environ={'INFOBLOX_NIOS_USERNAME':'reader','INFOBLOX_NIOS_PASSWORD':'password'})
        named=InputCredentialStore({k:'env:'+k for k in ('INFOBLOX_NIOS_USERNAME','INFOBLOX_NIOS_PASSWORD')},parent,'https://named.example.net/wapi/v2.13.6')
        self.assertEqual(SOURCES['infoblox_nios'].create({},named).url,'https://named.example.net/wapi/v2.13.6')
        self.assertTrue(SOURCES['infoblox_nios'].initial)

    def test_http_auth_denial_timeout_and_late_page_error_never_retry(self):
        for failure in ('HTTP 401; no retry was made','Connection failed (TimeoutError); no retry was made'):
            source,_=self.source();source.http=Mock();source.http.request.side_effect=GeofeedError(failure)
            with self.assertRaises(GeofeedError):source.snapshot()
            self.assertEqual(source.http.request.call_count,1)
        source,_=self.source();source.http=Mock();source.http.request.side_effect=[page([network()],'next'),GeofeedError('HTTP 403')]
        with self.assertRaises(GeofeedError):source.snapshot()
        self.assertEqual(source.http.request.call_count,2)

    def test_cli_publish_then_missing_selected_network_or_bad_attributes_retains_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);config={'source':{'type':'infoblox_nios','network_refs':[V4]},
                'credentials':{k:'env:'+k for k in ('INFOBLOX_NIOS_USERNAME','INFOBLOX_NIOS_PASSWORD')},
                'allowed_prefixes':['11.22.33.0/24'],'state_dir':str(root/'state'),
                'publish':{'type':'file','path':str(root/'feed.csv')}}
            path=root/'config.yaml'
            def run(rows):
                path.write_text(yaml.safe_dump(config),encoding='utf-8')
                with patch.dict('os.environ',{'INFOBLOX_NIOS_URL':'https://example.net/wapi/v2.13.6','INFOBLOX_NIOS_USERNAME':'reader','INFOBLOX_NIOS_PASSWORD':'password'}), \
                    patch('isp_geofeed_generator.infoblox_nios.JsonHTTP',return_value=HTTP([page(rows)])), \
                    patch('isp_geofeed_generator.cli.load_policy',return_value=policy()), \
                    contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):return main(['publish','--config',str(path)])
            self.assertEqual(run([network()]),1);self.assertFalse((root/'feed.csv').exists())
            config['source']['allow_initial']=True;self.assertEqual(run([network()]),0)
            before=(root/'feed.csv').read_bytes();backup=root/'state/before.csv';backup.write_bytes(b'private-backup')
            bad=network();bad['extattrs']=False
            other=network('network/not-selected:11.22.34.0/24/external','11.22.34.0/24')
            for rows in ([bad],[other]):
                self.assertEqual(run(rows),1)
                self.assertEqual((root/'feed.csv').read_bytes(),before)
                self.assertEqual(backup.read_bytes(),b'private-backup')
                self.assertFalse(json.loads((root/'state/status.json').read_text())['data']['healthy'])
