"""Whole-prefix bootstrap plans must not guess a server, authority or health."""
import contextlib
from datetime import datetime, timezone
import io
import ipaddress
import json
from pathlib import Path
import random
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from isp_geofeed_generator import rdap_bootstrap
from isp_geofeed_generator.cli import main
from isp_geofeed_generator.client import GeofeedError, JsonHTTP
from isp_geofeed_generator.credentials import CredentialStore
from isp_geofeed_generator.feed import digest

ARIN='https://rdap.arin.net/registry/'
RIPE='https://rdap.db.ripe.net/'
STAMP='2020-01-01T00:00:00Z'
NOW=datetime(2026,11,19,tzinfo=timezone.utc)


def saved(services=None, **changes):
    value={'version':'1.0','publication':'2019-06-07T19:00:02Z',
           'services':[[['11.0.0.0/8'],[ARIN]]] if services is None else services,
           'description':'PRIVATE ignored description',**changes}
    return json.dumps(value).encode()


def plan(data=None,prefix='11.22.33.0/24',stamp=STAMP):
    return rdap_bootstrap.plan_bootstrap(saved() if data is None else data,prefix,stamp,now=NOW)


class RdapBootstrapTests(unittest.TestCase):
    def test_ipv4_and_ipv6_preserve_prefix_and_build_the_standard_lookup_path(self):
        for prefix,parent in (('11.22.33.0/24','11.0.0.0/8'),('2001:4860:1234::/48','2001:4800::/23')):
            with self.subTest(family=ipaddress.ip_network(prefix).version):
                data=saved([[[parent],[ARIN]]]);report=plan(data,prefix)
                self.assertEqual(report['requested_prefix'],prefix)
                self.assertEqual(report['rdap_lookup_url'],ARIN+'ip/'+prefix)
                self.assertEqual(report['rdap_base_url'],ARIN)
                self.assertEqual(report['bootstrap_sha256'],digest(data))
                self.assertEqual(report['bootstrap_match'],'single_service_for_entire_prefix')
                self.assertTrue(report['inspection_only'] and report['planning_only'])
                self.assertNotIn('PRIVATE',json.dumps(report));self.assertNotIn('healthy',report)
                for field in ('bootstrap_authenticity','live_registry_read','ownership_validation',
                              'current_allocation_validation','signature_validation','public_retrieval','provider_ingestion'):
                    self.assertEqual(report[field],'not_measured')

    def test_most_specific_service_wins_in_both_families_and_orders(self):
        cases=[('11.22.33.0/24','11.0.0.0/8','11.22.0.0/16'),
               ('2001:4860:1234::/48','2001:4800::/23','2001:4860::/32')]
        for requested,parent,child in cases:
            rows=[[[parent],[ARIN]],[[child],[RIPE]]]
            for order in (rows,list(reversed(rows))):
                with self.subTest(requested=requested,reverse=order!=rows):
                    report=plan(saved(order),requested)
                    self.assertEqual(report['rdap_base_url'],RIPE)
                    self.assertEqual(report['bootstrap_matched_scope_count'],1)

    def test_entire_prefix_must_use_one_service_not_only_the_first_address(self):
        for parent,child in (('11.22.33.0/24','11.22.33.128/25'),
                             ('2001:4860:1234::/124','2001:4860:1234::8/125')):
            with self.subTest(family=ipaddress.ip_network(parent).version):
                with self.assertRaisesRegex(GeofeedError,'multiple bootstrap services'):
                    plan(saved([[[parent],[ARIN]],[[child],[RIPE]]]),parent)

    def test_complete_adjacent_scopes_and_fully_shadowed_routes_are_supported(self):
        rows=[[['11.22.33.0/25','11.22.33.128/25'],[ARIN]]]
        report=plan(saved(rows));self.assertEqual(report['bootstrap_matched_scope_count'],2)
        # A differently served parent is irrelevant when children cover all of it.
        rows.append([['11.22.33.0/24'],[RIPE]])
        self.assertEqual(plan(saved(rows))['rdap_base_url'],ARIN)
        # Two /128s cover exactly this IPv6 /127, with no address enumeration in production.
        report=plan(saved([[['2001:4860:1234::/128','2001:4860:1234::1/128'],[ARIN]]]),'2001:4860:1234::/127')
        self.assertEqual(report['bootstrap_matched_scope_count'],2)

    def test_gaps_and_missing_families_never_become_a_plan(self):
        for rows,prefix in (([[['11.22.33.0/25'],[ARIN]]],'11.22.33.0/24'),
                            ([[['11.22.34.0/24'],[ARIN]]],'11.22.33.0/24'),
                            ([[['2001:4860:1234::/128'],[ARIN]]],'2001:4860:1234::/127')):
            with self.subTest(prefix=prefix),self.assertRaisesRegex(GeofeedError,'entire requested prefix'):
                plan(saved(rows),prefix)

    def test_https_is_preferred_over_its_exact_legacy_http_counterpart(self):
        for base in sorted(rdap_bootstrap.SERVICE_BASES):
            urls=[base,base.replace('https://','http://',1)]
            for order in (urls,list(reversed(urls))):
                self.assertEqual(plan(saved([[['11.0.0.0/8'],order]]))['rdap_base_url'],base)
        for urls in ([ARIN.replace('https://','http://',1)],[ARIN,RIPE],[ARIN,ARIN],[]):
            with self.subTest(url_count=len(urls)),self.assertRaises(GeofeedError):
                plan(saved([[['11.0.0.0/8'],urls]]))

    def test_unknown_unsafe_or_changed_service_bases_are_not_advertised(self):
        for url in ('https://PRIVATE.invalid/','https://127.0.0.1/','https://user:PRIVATE@rdap.arin.net/registry/',
                    ARIN+'?PRIVATE=1',ARIN+'#PRIVATE',ARIN+'../',ARIN.rstrip('/'),ARIN.upper()):
            with self.subTest(kind=url.split('/')[2]):
                with self.assertRaises(GeofeedError) as caught:plan(saved([[['11.0.0.0/8'],[url]]]))
                self.assertNotIn('PRIVATE',str(caught.exception))
        for other in ('http://PRIVATE.invalid/',True,None,42):
            with self.subTest(kind=type(other).__name__),self.assertRaises(GeofeedError):
                plan(saved([[['11.0.0.0/8'],[ARIN,other]]]))

    def test_duplicate_equal_scopes_are_refused_even_with_the_same_service(self):
        for rows in ([[['11.0.0.0/8','11.0.0.0/8'],[ARIN]]],
                     [[['11.0.0.0/8'],[ARIN]],[['11.0.0.0/8'],[RIPE]]],
                     [[['11.0.0.0/8'],[ARIN]],[['11.0.0.0/8'],[ARIN]]]):
            with self.subTest(rows=len(rows)),self.assertRaisesRegex(GeofeedError,'repeats a prefix'):plan(saved(rows))

    def test_query_prefixes_are_canonical_public_and_cannot_inject_urls(self):
        invalid=('10.0.0.0/8','100.64.0.0/10','192.0.2.0/24','224.0.0.0/4','0.0.0.0/0',
                 '2001:db8::/32','fc00::/7','2002::/16','3fff::/20','11.22.33.1/24',
                 '11.22.33.0','11.22.33.0/024','11.22.33.0/24?PRIVATE','11.22.33.0/24\nPRIVATE',
                 '2001:4860:ABCD::/48','2001:4860::%PRIVATE/64',None,True,42)
        for prefix in invalid:
            with self.subTest(kind=type(prefix).__name__):
                with self.assertRaises(GeofeedError) as caught:plan(prefix=prefix)
                self.assertNotIn('PRIVATE',str(caught.exception))

    def test_dates_separate_publication_from_the_supplied_download_age(self):
        report=plan(stamp='2026-11-19T00:00:00Z')
        self.assertEqual(report['bootstrap_snapshot_age_seconds'],0)
        self.assertGreater(report['bootstrap_publication_age_seconds'],365*86400)
        self.assertEqual(report['bootstrap_observed_at_source'],'operator_supplied')
        for stamp,publication in ((None,'2019-06-07T19:00:02Z'),('2999-01-01T00:00:00Z','2019-06-07T19:00:02Z'),
                                  ('2020-01-01T00:00:00-00:00','2019-06-07T19:00:02Z'),
                                  (STAMP,'2020-01-02T00:00:00Z'),(STAMP,'2999-01-01T00:00:00Z'),
                                  ('2020-02-30T00:00:00Z','2019-06-07T19:00:02Z')):
            with self.subTest(stamp=stamp),self.assertRaises(GeofeedError):plan(saved(publication=publication),stamp=stamp)
        self.assertIn('.123456',plan(stamp='2020-01-01T00:00:00.123456+00:00')['bootstrap_observed_at'])

    def test_unused_metadata_is_ignored_and_never_executed_or_reported(self):
        data=saved(extra={'PRIVATE':'__import__("os")','number':1.25,'links':['https://PRIVATE.invalid/']},description=None)
        with patch('builtins.eval',side_effect=AssertionError('evaluation')), \
             patch('builtins.exec',side_effect=AssertionError('execution')):report=plan(data)
        self.assertNotIn('PRIVATE',json.dumps(report));self.assertEqual(report['rdap_base_url'],ARIN)

    def test_malformed_and_partial_inputs_refuse_with_no_value_echo(self):
        data=[b'NaN',b'{"PRIVATE":1e9999}',b'{"version":"1.0","version":"1.0"}',b'\xff',b'['*1100,
              b'x'*(rdap_bootstrap.MAX_BYTES+1),saved([]),saved([[]]),saved([['PRIVATE',[ARIN]]]),
              saved([[['2001:4860::/32'],[ARIN]]]),saved([[['11.1.0.0/8'],[ARIN]]]),
              saved(version='2.0'),saved(publication=None),saved([[[None],[ARIN]]])]
        for index,value in enumerate(data):
            with self.subTest(vector=index):
                with self.assertRaises(GeofeedError) as caught:plan(value)
                self.assertNotIn('PRIVATE',str(caught.exception))

    def test_service_prefix_url_and_byte_budgets_are_enforced(self):
        rows=[[['11.22.33.0/25','11.22.33.128/25'],[ARIN]]]
        with patch.object(rdap_bootstrap,'MAX_PREFIXES',2):self.assertEqual(plan(saved(rows))['bootstrap_prefix_count'],2)
        with patch.object(rdap_bootstrap,'MAX_PREFIXES',1),self.assertRaises(GeofeedError):plan(saved(rows))
        with patch.object(rdap_bootstrap,'MAX_SERVICES',1):
            self.assertEqual(plan()['bootstrap_prefix_count'],1)
            with self.assertRaises(GeofeedError):plan(saved([[['11.0.0.0/8'],[ARIN]],[['12.0.0.0/8'],[ARIN]]]))
        with patch.object(rdap_bootstrap,'MAX_URLS',1):
            self.assertEqual(plan()['rdap_base_url'],ARIN)
            with self.assertRaises(GeofeedError):plan(saved([[['11.0.0.0/8'],[ARIN,ARIN.replace('https://','http://',1)]]]))
        raw=saved()
        with patch.object(rdap_bootstrap,'MAX_BYTES',len(raw)):self.assertEqual(plan(raw)['bootstrap_sha256'],digest(raw))
        with patch.object(rdap_bootstrap,'MAX_BYTES',len(raw)-1),self.assertRaises(GeofeedError):plan(raw)

    def test_invalid_unselected_authority_rows_cannot_be_silently_dropped(self):
        for row in ([['12.0.0.0/8'],['https://PRIVATE.invalid/']], [['12.1.0.0/8'],[ARIN]],
                    [['2001:4860::/32'],[ARIN]], [[],[ARIN]]):
            with self.subTest(kind=len(row)),self.assertRaises(GeofeedError):
                plan(saved([[['11.0.0.0/8'],[ARIN]],row]))

    def test_cli_reads_only_the_saved_file_and_preserves_private_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);bootstrap=root/'bootstrap.json';bootstrap.write_bytes(saved())
            (root/'feed.csv').write_bytes(b'baseline');(root/'status.json').write_bytes(b'failed status')
            (root/'before.csv').write_bytes(b'recovery')
            before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()}
            args=['plan-rdap','--bootstrap-records',str(bootstrap),'--bootstrap-observed-at',STAMP,'--rdap-prefix','11.22.33.0/24']
            output=io.StringIO()
            with patch('isp_geofeed_generator.cli.load_config',side_effect=AssertionError('config read')), \
                 patch.object(CredentialStore,'get',side_effect=AssertionError('credential read')), \
                 patch.object(JsonHTTP,'request',side_effect=AssertionError('HTTP call')), \
                 patch('socket.getaddrinfo',side_effect=AssertionError('DNS lookup')), \
                 patch('urllib.request.urlopen',side_effect=AssertionError('URL open')), \
                 patch('isp_geofeed_generator.cli.atomic_write',side_effect=AssertionError('write')), \
                 contextlib.redirect_stdout(output):self.assertEqual(main(args),0)
            report=json.loads(output.getvalue());self.assertEqual(report['rdap_lookup_url'],ARIN+'ip/11.22.33.0/24')
            self.assertNotIn(str(bootstrap),output.getvalue());self.assertNotIn('PRIVATE',output.getvalue())
            self.assertEqual({p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()},before)
            bootstrap.write_bytes(saved([[['11.22.33.0/25'],[ARIN]]]))
            prior=(bootstrap.read_bytes(),bootstrap.stat().st_mtime_ns);output=io.StringIO();error=io.StringIO()
            with contextlib.redirect_stdout(output),contextlib.redirect_stderr(error):self.assertEqual(main(args),1)
            self.assertEqual(output.getvalue(),'');self.assertIn('entire requested prefix',error.getvalue())
            self.assertEqual((bootstrap.read_bytes(),bootstrap.stat().st_mtime_ns),prior)
            self.assertEqual({p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir() if p!=bootstrap},
                             {key:value for key,value in before.items() if key!=bootstrap.name})

    def test_command_flags_cannot_enable_other_operations_or_read_bad_files(self):
        base=['--bootstrap-records','absent','--bootstrap-observed-at',STAMP,'--rdap-prefix','11.22.33.0/24']
        with patch('isp_geofeed_generator.cli.load_config',side_effect=AssertionError('config read')), \
             patch.object(rdap_bootstrap,'read_output',side_effect=AssertionError('input read')):
            for args in (['publish',*base],['check-registry',*base],['generate',*base],['plan-rdap'],
                         ['plan-rdap',*base,'--output','out'],['plan-rdap',*base,'--feed','feed'],
                         ['plan-rdap',*base,'--probe-cache'],['plan-rdap',*base,'--rdap-language','en']):
                output=io.StringIO();error=io.StringIO()
                with contextlib.redirect_stdout(output),contextlib.redirect_stderr(error):self.assertEqual(main(args),1)
                self.assertEqual(output.getvalue(),'')

    def test_event_sweep_matches_an_independent_per_address_oracle(self):
        rng=random.Random(9224);matched=refused=0
        for family,parent in ((4,'11.22.33.0/24'),(6,'2001:4860:1234::/120')):
            container=ipaddress.ip_network(parent)
            options=[net for length in (container.prefixlen,container.prefixlen+1,container.prefixlen+2,
                       container.prefixlen+3,container.prefixlen+4) for net in container.subnets(new_prefix=length)]
            for _ in range(100):
                networks=rng.sample(options,rng.randint(1,8));routes={net:rng.choice((ARIN,RIPE)) for net in networks}
                requested=rng.choice(list(container.subnets(new_prefix=container.prefixlen+4)))
                expected=set()
                for value in range(int(requested.network_address),int(requested.broadcast_address)+1):
                    address=ipaddress.ip_address(value) if family==4 else ipaddress.IPv6Address(value)
                    candidates=[net for net in routes if address in net]
                    expected.add(routes[max(candidates,key=lambda net:net.prefixlen)] if candidates else None)
                rows=[[[str(net)],[base]] for net,base in routes.items()]
                if len(expected)==1 and None not in expected:
                    self.assertEqual(plan(saved(rows),str(requested))['rdap_base_url'],next(iter(expected)));matched+=1
                else:
                    with self.assertRaises(GeofeedError):plan(saved(rows),str(requested))
                    refused+=1
        self.assertGreater(matched,0);self.assertGreater(refused,0)
        print('RDAP BOOTSTRAP ORACLE OBSERVATION: '+json.dumps({'cases':200,'families':[4,6],'matched':matched,'refused':refused}))

    def test_private_selection_guard_removals_cause_assertion_failures(self):
        text=Path(rdap_bootstrap.__file__).read_text(encoding='utf-8')
        controls=[('service-profile','if base not in SERVICE_BASES:','if False:',
                   'test_unknown_unsafe_or_changed_service_bases_are_not_advertised'),
                  ('longest-prefix','-routes[index][0].prefixlen','routes[index][0].prefixlen',
                   'test_most_specific_service_wins_in_both_families_and_orders'),
                  ('entire-prefix','if len(selected) != 1:','if not selected:',
                   'test_entire_prefix_must_use_one_service_not_only_the_first_address')]
        def run(method):
            result=unittest.TestResult();RdapBootstrapTests(method).run(result);return result
        positive='test_ipv4_and_ipv6_preserve_prefix_and_build_the_standard_lookup_path'
        for name,find,replacement,method in controls:
            with self.subTest(mutation=name):
                self.assertTrue(run(positive).wasSuccessful());self.assertTrue(run(method).wasSuccessful())
                self.assertEqual(text.count(find),1)
                module=types.ModuleType('isp_geofeed_generator._private_bootstrap_control');module.__package__='isp_geofeed_generator'
                with patch.dict(sys.modules,{module.__name__:module}):
                    exec(compile(text.replace(find,replacement),'<private bootstrap control>','exec'),module.__dict__)
                    with patch.object(rdap_bootstrap,'plan_bootstrap',module.plan_bootstrap):result=run(method)
                self.assertEqual(result.errors,[]);self.assertGreater(len(result.failures),0)
                self.assertTrue(run(method).wasSuccessful());self.assertTrue(run(positive).wasSuccessful())
                print('RDAP BOOTSTRAP MUTATION OBSERVATION: '+json.dumps({'mutation':name,
                    'assertion_failures':len(result.failures),'errors':0,'intact_before_after':True}))
