"""BillMax public AP-detail contract; no live tenant data or credentials."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit
import yaml
from isp_geofeed_generator.adapters import SOURCES
from isp_geofeed_generator.billmax import BillMax
from isp_geofeed_generator.cli import main
from isp_geofeed_generator.client import GeofeedError
from isp_geofeed_generator.credentials import CredentialStore, InputCredentialStore
from isp_geofeed_generator.feed import build, parse_feed
from bogon_fixture import policy
from test_sources import HTTP


def ap(identifier='7', prefix='11.22.33.0/24'):
    return {'id': identifier, 'networkMask': prefix, 'pop': 'A display value, not an ID',
        '_pop': [{'id': 12, 'country': 'US', 'stateProvince': 'US-IL', 'city': 'Example City',
                  'address1': 'private-street', 'zipPostalCode': 'private-postal',
                  'location': ['private-longitude', 'private-latitude']}],
        '_notes': [{'text': 'private-note'}], 'password': 'private-ignored-field'}


class BillMaxTests(unittest.TestCase):
    def source(self, replies=None, settings=None):
        http = HTTP([[ap()]] if replies is None else replies)
        return BillMax('https://example.net:3105/api/billmaxCoreApi/v1', 'synthetic-key',
            settings or {'ap_ids': ['7']}, http=http), http

    def test_native_pop_exact_network_and_minimized_snapshot(self):
        source, http = self.source()
        snapshot = source.for_publication(source.snapshot())
        data, _ = build(snapshot, {'allowed_prefixes': ['11.22.33.0/24']})
        self.assertEqual(sum(n.num_addresses for n in parse_feed(data)), 256)
        self.assertEqual(data, b'11.22.33.0/24,US,US-IL,Example City,\r\n')
        self.assertEqual(snapshot['pools'][0]['site_id'], 'pop:12')
        self.assertNotIn('private-', json.dumps(snapshot))
        url, call = http.calls[0]
        self.assertEqual(urlsplit(url).path, '/api/billmaxCoreApi/v1/aps/7')
        self.assertEqual(parse_qs(urlsplit(url).query), {'pop':['true'],'notes':['false'],'tickets':['false'],'active':['true']})
        self.assertEqual(call, {'headers': {'api_key':'synthetic-key'}, 'method':'GET'})
        self.assertNotIn('synthetic-key', url)

    def test_whole_16_network_and_pop_reuse_conflict(self):
        source, _ = self.source([[ap('7', '11.22.0.0/16')]])
        data, _ = build(source.snapshot(), {'allowed_prefixes':['11.22.0.0/16']})
        self.assertEqual(sum(n.num_addresses for n in parse_feed(data)), 65536)
        first, second = ap(), ap('8', '11.22.34.0/24')
        source, _ = self.source([[first], [second]], {'ap_ids':['7','8']})
        self.assertEqual(len(source.snapshot()['sites']), 1)
        second['_pop'][0]['city'] = 'Conflicting City'
        source, _ = self.source([[first], [second]], {'ap_ids':['7','8']})
        with self.assertRaisesRegex(GeofeedError, 'pop:12.*conflict'): source.snapshot()

    def test_invalid_detail_and_pop_shapes_stop_without_private_values(self):
        cases = [None, {}, [], [ap(),ap()], [ap('8')], [None]]
        for link in (None, {}, [], [None], [{'id':'private-bad-id'}], [{'id':0}], [{'id':True}], ap()['_pop']*2):
            row = ap(); row['_pop'] = link; cases.append([row])
        for result in cases:
            with self.subTest(result=result):
                source, _ = self.source([result])
                with self.assertRaisesRegex(GeofeedError, 'BillMax AP 7') as error: source.snapshot()
                self.assertNotIn('private-', str(error.exception))

    def test_unsupported_or_bad_boundaries_do_not_expand_or_guess(self):
        for value in ('', None, 17, '11.22.33.1', '11.22.33.1/24', '11.22.33.0/25',
                      '11.22.33.0/255.255.255.0', '2001:4860:1234::/48', 'private-bad-prefix'):
            source, _ = self.source([[ap(prefix=value)]])
            with self.subTest(value=value), self.assertRaisesRegex(GeofeedError, 'AP 7.*networkMask') as error: source.snapshot()
            self.assertNotIn('private-', str(error.exception))

    def test_iso_values_need_reviewed_overrides_and_no_coordinate_inference(self):
        row = ap(); row['_pop'][0].update(country='USA', stateProvince='Texas')
        source, _ = self.source([[row]])
        snapshot = source.snapshot()
        with self.assertRaisesRegex(GeofeedError, 'Site pop:12'): build(snapshot, {'allowed_prefixes':['11.22.33.0/24']})
        data, _ = build(snapshot, {'allowed_prefixes':['11.22.33.0/24'],
            'site_locations':{'pop:12':{'country':'US','region':'US-TX','city':'Reviewed City'}}})
        self.assertIn(b',US,US-TX,Reviewed City,', data)

    def test_discovery_clamped_pages_until_empty_and_explicit_selection(self):
        rows = [{'id':'7','name':'AP A','networkMask':'','pop':'Example POP','status':'Available','password':'private-field'},
                {'id':'8','networkMask':'11.22.33.0/24'}]
        source, http = self.source([[rows[0]],[rows[1]],[]], {'ap_ids':[]})
        snapshot = source.snapshot()
        self.assertEqual(len(snapshot['ap_directory']), 2)
        self.assertEqual(snapshot['pools'], [])
        self.assertNotIn('private-field', json.dumps(snapshot))
        self.assertEqual([parse_qs(urlsplit(c[0]).query)['limitStart'] for c in http.calls], [['0'],['1'],['2']])
        with self.assertRaisesRegex(GeofeedError, 'source.ap_ids'): source.for_publication(snapshot)

    def test_directory_invalid_empty_duplicate_and_unordered_pages_fail(self):
        for replies in ([[]], [{}], [[None]], [[{'id':'private-id'}]], [[{'id':'8'}],[{'id':'8'}]],
                        [[{'id':'8'}],[{'id':'7'}]], [[{'id':'7'}]*101]):
            source, _ = self.source(replies, {'ap_ids':[]})
            with self.subTest(replies=replies), self.assertRaises(GeofeedError) as error: source.snapshot()
            self.assertNotIn('private-id', str(error.exception))

    def test_settings_and_urls_fail_before_requests(self):
        for settings in ({'ap_ids':'7'}, {'ap_ids':[7]}, {'ap_ids':[True]}, {'ap_ids':['0']},
                         {'ap_ids':['7','7']}, {'ap_ids':['7/../8']}, {'auth_mode':'guess'}):
            with self.subTest(settings=settings), self.assertRaises(GeofeedError): self.source(settings=settings)
        for url in ('http://example.net','https://key@example.net','https://example.net?token=key'):
            with self.assertRaises(GeofeedError): BillMax(url,'key')

    def test_userpass_login_is_only_post_and_session_is_not_retained(self):
        http = HTTP([{'BXSESSIONID':'synthetic-session'}, [ap()]])
        source = BillMax('https://example.net/api/billmaxCoreApi/v1','synthetic-key',
            {'ap_ids':['7'],'auth_mode':'userpass'}, username='reader',password='synthetic-password',http=http)
        snapshot = source.snapshot()
        self.assertEqual(http.calls[0][1], {'headers':{'api_key':'synthetic-key'},
            'body':{'username':'reader','password':'synthetic-password'},'method':'POST'})
        self.assertEqual(http.calls[1][1]['headers']['Authorization'], 'Bearer synthetic-session')
        self.assertNotIn('synthetic-', json.dumps(snapshot))
        for result in (None,[],{}, {'BXSESSIONID':'bad\r\nsession'}, {'BXSESSIONID':False}):
            source.http=HTTP([result])
            with self.assertRaisesRegex(GeofeedError, 'BillMax'): source.snapshot()
            self.assertEqual(len(source.http.calls), 1)

    def test_factory_requests_only_its_credentials_and_named_endpoint(self):
        for mode, expected in [('api_key',{'BILLMAX_API_KEY'}),
                               ('userpass',{'BILLMAX_API_KEY','BILLMAX_USERNAME','BILLMAX_PASSWORD'})]:
            credentials=Mock();credentials.get.return_value='synthetic-value'
            with patch.dict('os.environ',{'BILLMAX_URL':'https://example.net/api/billmaxCoreApi/v1'}):
                source=SOURCES['billmax'].create({'auth_mode':mode},credentials)
            self.assertEqual({c.args[0] for c in credentials.get.call_args_list},expected)
            self.assertTrue(SOURCES['billmax'].initial)
        parent=CredentialStore(environ={'BILLMAX_API_KEY':'synthetic-key'})
        store=InputCredentialStore({'BILLMAX_API_KEY':'env:BILLMAX_API_KEY'},parent,'https://named.example.net/v1')
        self.assertEqual(SOURCES['billmax'].create({},store).url,'https://named.example.net/v1')

    def test_http_denial_or_timeout_does_not_retry_or_continue(self):
        source,_=self.source()
        for message in ('HTTP 401; no retry was made','Connection failed (TimeoutError); no retry was made'):
            source.http=Mock();source.http.request.side_effect=GeofeedError(message)
            with self.assertRaises(GeofeedError):source.snapshot()
            source.http.request.assert_called_once()

    def test_cli_initial_opt_in_success_then_source_failure_keeps_feed_and_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); config={'source':{'type':'billmax','ap_ids':['7']},
                'credentials':{'BILLMAX_API_KEY':'env:BILLMAX_API_KEY'},'allowed_prefixes':['11.22.33.0/24'],
                'state_dir':str(root/'state'),'publish':{'type':'file','path':str(root/'feed.csv')}}
            path=root/'config.yaml'
            def run(replies):
                path.write_text(yaml.safe_dump(config),encoding='utf-8')
                http=HTTP(replies)
                with patch.dict('os.environ',{'BILLMAX_URL':'https://example.net/v1','BILLMAX_API_KEY':'synthetic-key'}), \
                     patch('isp_geofeed_generator.billmax.JsonHTTP',return_value=http), \
                     patch('isp_geofeed_generator.cli.load_policy',return_value=policy()), \
                     contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                    result=main(['publish','--config',str(path)])
                return result
            self.assertEqual(run([[ap()]]),1)
            self.assertFalse((root/'feed.csv').exists())
            config['source']['allow_initial']=True
            self.assertEqual(run([[ap()]]),0)
            before=(root/'feed.csv').read_bytes(); backup=root/'state/before.csv'
            backup.write_bytes(b'private-prior-backup')
            bad=ap();bad['_pop']=[]
            self.assertEqual(run([[bad]]),1)
            self.assertEqual((root/'feed.csv').read_bytes(),before)
            self.assertEqual(backup.read_bytes(),b'private-prior-backup')
            self.assertFalse(json.loads((root/'state/status.json').read_text())['data']['healthy'])
            config['source']['ap_ids']=['7','8']
            self.assertEqual(run([[ap()],[]]),1)
            self.assertEqual((root/'feed.csv').read_bytes(),before)
            self.assertEqual(backup.read_bytes(),b'private-prior-backup')
