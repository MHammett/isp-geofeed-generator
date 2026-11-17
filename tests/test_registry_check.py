"""Offline discovery precedence, exact unsigned coverage and untrusted inputs."""
import contextlib
from datetime import datetime, timezone
import io
import ipaddress
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from isp_geofeed_generator import registry_check
from isp_geofeed_generator.cli import main
from isp_geofeed_generator.client import GeofeedError, JsonHTTP
from isp_geofeed_generator.credentials import CredentialStore
from isp_geofeed_generator.feed import render_csv
from isp_geofeed_generator.overlap import LONGEST_PREFIX
from test_nested_core import PARENT, CHILD

URL='https://example.net/feed.csv'
OTHER='https://other.example/feed.csv'
BASE=ipaddress.ip_network(PARENT['prefix'])
CSV=render_csv([PARENT])
NOW=datetime(2026,11,17,tzinfo=timezone.utc)


def snapshot(rows, **changes):
    return json.dumps({'schema_version':1,'observed_at':'2026-11-16T00:00:00Z','objects':rows,**changes}).encode()


def record(identity='parent', prefix=str(BASE), **changes):
    return {'id':identity,'prefix':prefix,**changes}


def check(objects, csv=CSV, url=URL, **kwargs):
    return registry_check.check_snapshot(snapshot(objects),csv,url,now=NOW,**kwargs)


class RegistryCheckTests(unittest.TestCase):
    def test_native_reference_wins_without_parsing_ignored_remarks(self):
        for remarks in ([f'Geofeed {OTHER}'],['geofeed: invalid'],['Geofeedback is unrelated']):
            with self.subTest(remarks=remarks):
                result=check([record(geofeed=URL,remarks=remarks)])
                self.assertTrue(result['comparison_consistent'])
                self.assertEqual(result['coverage']['4']['this_feed'],'256')
                self.assertEqual(result['finding_count'],0)
        result=check([record(geofeed='http://invalid.example/',remarks=[f'Geofeed {URL}'])])
        self.assertFalse(result['comparison_consistent'])
        self.assertEqual(result['coverage']['4']['invalid_reference'],'256')

    def test_distinct_native_and_remarks_syntax(self):
        self.assertTrue(check([record(remarks=[f'Geofeed {URL}'])])['comparison_consistent'])
        for text in (f'geofeed {URL}',f'Geofeed: {URL}',f'Geofeed {URL} {OTHER}'):
            with self.subTest(text=text):
                result=check([record(remarks=[text])])
                self.assertFalse(result['comparison_consistent'])
                self.assertEqual(result['coverage']['4']['invalid_reference'],'256')
        self.assertEqual(check([record(remarks=['Geofeedback is unrelated'])])['finding_count'],0)

    def test_most_specific_reference_and_unsigned_scope_clipping(self):
        result=check([record(geofeed=URL),record('child',CHILD['prefix'],geofeed=OTHER)])
        self.assertEqual(result['coverage']['4']['this_feed'],'128')
        self.assertEqual(result['coverage']['4']['other_feed'],'128')
        self.assertFalse(result['comparison_consistent'])
        result=check([record('child',CHILD['prefix'],geofeed=URL)])
        self.assertEqual(result['coverage']['4']['this_feed'],'128')
        self.assertEqual(result['coverage']['4']['unreferenced'],'128')
        self.assertFalse(result['comparison_consistent'])
        result=check([record(geofeed=URL),record('child',CHILD['prefix'],remarks=['Administrative comment'])])
        self.assertTrue(result['comparison_consistent'])

    def test_disjoint_references_cover_one_broader_feed_row(self):
        broader=check([record(prefix='11.22.0.0/16',geofeed=URL)])
        self.assertTrue(broader['comparison_consistent'])
        self.assertEqual(broader['coverage']['4']['total'],'256')
        result=check([record('first','11.22.33.0/25',geofeed=URL),record('second','11.22.33.128/25',geofeed=URL)])
        self.assertTrue(result['comparison_consistent'])
        self.assertEqual(result['coverage']['4']['total'],'256')

    def test_feed_nesting_is_separate_and_union_is_not_counted_twice(self):
        nested=render_csv([PARENT,CHILD],overlap_policy=LONGEST_PREFIX)
        with self.assertRaises(GeofeedError):check([record(geofeed=URL)],csv=nested)
        result=check([record(geofeed=URL),record('child',CHILD['prefix'],geofeed=OTHER)],
                     csv=nested,overlap_policy=LONGEST_PREFIX)
        self.assertEqual(result['coverage']['4']['total'],'256')
        self.assertEqual(result['coverage']['4']['this_feed'],'128')
        self.assertEqual(result['coverage']['4']['other_feed'],'128')

    def test_ipv6_counts_are_exact_decimal_strings_including_last_address(self):
        prefix='2001:4860::/32';network=ipaddress.ip_network(prefix)
        rows=[{'prefix':prefix,'location':PARENT['location']}]
        last=str(network.broadcast_address)+'/128'
        result=check([record('v6',prefix,geofeed=URL),record('last',last,geofeed=OTHER)],csv=render_csv(rows))
        self.assertEqual(result['coverage']['6']['total'],str(2**96))
        self.assertEqual(result['coverage']['6']['this_feed'],str(2**96-1))
        self.assertEqual(result['coverage']['6']['other_feed'],'1')
        self.assertEqual(result['coverage_details'][0]['end'],str(network.broadcast_address))

    def test_same_scope_and_multiple_remarks_are_explicitly_unsupported_ties(self):
        for objects in ([record('one',geofeed=URL),record('two',geofeed=OTHER)],
                        [record(remarks=[f'Geofeed {URL}',f'Geofeed {OTHER}'])]):
            with self.subTest(objects=objects):
                result=check(objects)
                self.assertFalse(result['comparison_consistent'])
                self.assertEqual(result['coverage']['4']['ambiguous_reference'],'256')
                self.assertIn('unsupported',result['findings'][0]['kind'])

    def test_empty_snapshot_does_not_pass_and_live_checks_remain_not_measured(self):
        result=check([])
        self.assertFalse(result['comparison_consistent'])
        self.assertEqual(result['coverage']['4']['unreferenced'],'256')
        self.assertEqual(result['snapshot_age_seconds'],86400)
        for key in ('live_registry_read','ownership_validation','current_allocation_validation','public_retrieval','provider_ingestion'):
            self.assertEqual(result[key],'not_measured')
        self.assertNotIn('healthy',result)

    def test_urls_are_never_followed_or_echoed_and_valid_queries_are_supported(self):
        url=URL+'?token=PRIVATE-sentinel#part'
        result=check([record(geofeed=url)],url=url)
        self.assertTrue(result['comparison_consistent'])
        self.assertNotIn('PRIVATE-sentinel',json.dumps(result))
        for invalid in ('http://example.net/feed','https://user:PRIVATE@example.net/feed','https://@example.net/feed',
                        'https://example.net/%ZZ','https://example.net:99999/feed','https://example.net/\nPRIVATE',
                        'https://example.net/'+'x'*2049):
            with self.subTest(invalid=invalid[:30]):
                result=check([record(geofeed=invalid)])
                self.assertFalse(result['comparison_consistent'])
                self.assertNotIn('PRIVATE',json.dumps(result))
                with self.assertRaises(GeofeedError) as error:check([],url=invalid)
                self.assertNotIn('PRIVATE',str(error.exception))

    def test_structural_errors_do_not_echo_values(self):
        bad_objects=([record(id='PRIVATE\ninjection')],[record(),record()],
                     [record(prefix='PRIVATE invalid')],[record(remarks='PRIVATE invalid')],
                     [record(remarks=['PRIVATE\nGeofeed '+URL])],[record(signed=True)],
                     [record(remarks=['comment']*21)])
        for objects in bad_objects:
            with self.subTest(objects=objects):
                with self.assertRaises(GeofeedError) as error:check(objects)
                self.assertNotIn('PRIVATE',str(error.exception))
        for changes in ({'schema_version':True},{'observed_at':'2999-01-01T00:00:00Z'},
                        {'observed_at':'2026-11-16'},{'extra':'PRIVATE'},{'objects':{}}):
            with self.subTest(changes=changes),self.assertRaises(GeofeedError):
                registry_check.check_snapshot(snapshot([],**changes),CSV,URL,now=NOW)

    def test_duplicate_json_keys_nonfinite_constants_and_size_limits_refuse(self):
        for data in (b'{"schema_version":1,"schema_version":1}',snapshot([record(geofeed=float('nan'))]),b' '*8_000_001):
            with self.assertRaises(GeofeedError):registry_check.check_snapshot(data,CSV,URL,now=NOW)
        with patch.object(registry_check,'MAX_OBJECTS',1):
            self.assertTrue(check([record(geofeed=URL)])['comparison_consistent'])
            with self.assertRaises(GeofeedError):check([record(geofeed=URL),record('extra','11.22.34.0/24',geofeed=URL)])
        for csv in (b'',b'192.0.2.0/24,US,US-IL,A,\r\n',b'10.0.0.0/24,US,US-IL,A,\r\n'):
            with self.assertRaises(GeofeedError):check([],csv=csv)

    def test_details_truncate_without_losing_counts_or_turning_failure_into_pass(self):
        objects=[record(str(index),f'11.22.33.{index*64}/26',geofeed='http://invalid.example/') for index in range(3)]
        with patch.object(registry_check,'MAX_DETAILS',2):result=check(objects)
        self.assertEqual(result['finding_count'],3);self.assertEqual(len(result['findings']),2)
        self.assertTrue(result['details_truncated']);self.assertFalse(result['comparison_consistent'])
        self.assertEqual(result['coverage']['4']['invalid_reference'],'192')
        self.assertEqual(result['coverage']['4']['unreferenced'],'64')

    def test_independent_per_address_oracle_for_100_small_cases(self):
        rng=random.Random(9632)
        for case in range(100):
            def net():return ipaddress.ip_network((int(BASE.network_address)+rng.randrange(256),rng.randrange(24,33)),strict=False)
            feeds=set(net() for _ in range(rng.randrange(1,5)))
            objects=[];references=[]
            for index in range(rng.randrange(10)):
                scope=net();url=rng.choice((URL,OTHER,None,'http://invalid.example/'))
                objects.append(record(str(index),str(scope),**({'geofeed':url} if url is not None else {})))
                if url is not None:references.append((scope,url))
            csv=render_csv([{'prefix':str(scope),'location':PARENT['location']} for scope in sorted(feeds)],overlap_policy=LONGEST_PREFIX)
            expected={kind:0 for kind in registry_check.KINDS}
            for address in BASE:
                if not any(address in scope for scope in feeds):continue
                choices=[(scope,url) for scope,url in references if address in scope]
                if not choices:kind='unreferenced'
                else:
                    depth=max(scope.prefixlen for scope,_ in choices)
                    winners=[url for scope,url in choices if scope.prefixlen==depth]
                    kind=('ambiguous_reference' if len(winners)>1 else 'this_feed' if winners[0]==URL
                          else 'other_feed' if winners[0]==OTHER else 'invalid_reference')
                expected[kind]+=1
            actual=check(objects,csv=csv,overlap_policy=LONGEST_PREFIX)['coverage']['4']
            self.assertEqual({kind:int(actual[kind]) for kind in expected},expected,f'case {case}')

    def test_cli_reads_no_config_credentials_or_network_and_preserves_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'records.json';feed=root/'feed.csv';status=root/'status.json'
            source.write_bytes(snapshot([record(geofeed=URL)]));feed.write_bytes(CSV);status.write_bytes(b'failed status')
            before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()}
            output=io.StringIO()
            with patch('isp_geofeed_generator.cli.load_config',side_effect=AssertionError('config read')), \
                 patch.object(CredentialStore,'get',side_effect=AssertionError('credential read')), \
                 patch.object(JsonHTTP,'request',side_effect=AssertionError('network read')), \
                 patch('isp_geofeed_generator.cli.atomic_write',side_effect=AssertionError('output write')), \
                 contextlib.redirect_stdout(output):
                self.assertEqual(main(['check-registry','--config',str(root/'missing.yaml'),'--registry-records',str(source),
                                       '--feed',str(feed),'--feed-url',URL]),0)
            self.assertTrue(json.loads(output.getvalue())['inspection_only'])
            self.assertEqual({p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()},before)
            output=io.StringIO()
            with contextlib.redirect_stderr(output):
                self.assertEqual(main(['check-registry','--registry-records',str(source),'--feed',str(feed),'--feed-url',URL,
                                       '--output',str(feed)]),1)
            self.assertEqual(feed.read_bytes(),CSV)

    def test_cli_scope_and_missing_files_stop_before_configuration(self):
        with patch('isp_geofeed_generator.cli.load_config') as config,contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['publish','--feed-url',URL]),1)
            self.assertEqual(main(['check-registry']),1)
            self.assertEqual(main(['check-registry','--registry-records','missing-snapshot','--feed','missing-feed','--feed-url',URL]),1)
        config.assert_not_called()
