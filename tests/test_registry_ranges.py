"""Exact registry ranges, containment order and an independent address oracle."""
import contextlib
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

from isp_geofeed_generator.cli import main
from isp_geofeed_generator.client import GeofeedError, JsonHTTP
from isp_geofeed_generator.credentials import CredentialStore
from isp_geofeed_generator.feed import render_csv
from isp_geofeed_generator.overlap import LONGEST_PREFIX
from isp_geofeed_generator import registry_check
from test_registry_check import BASE, CSV, NOW, URL, OTHER, PARENT, check, record, snapshot


def interval(identity='range', start='11.22.33.1', end='11.22.33.254', **changes):
    return {'id':identity,'start':start,'end':end,**changes}


class RegistryRangeTests(unittest.TestCase):
    def test_exact_inclusive_range_does_not_widen_or_drop_endpoints(self):
        result=check([interval(geofeed=URL)])
        self.assertEqual(result['coverage']['4']['this_feed'],'254')
        self.assertEqual(result['coverage']['4']['unreferenced'],'2')
        self.assertEqual([(v['start'],v['end']) for v in result['coverage_details']],
                         [('11.22.33.0','11.22.33.0'),('11.22.33.255','11.22.33.255')])
        self.assertFalse(result['comparison_consistent'])
        self.assertEqual(result['scope'],'supplied_unsigned_range_snapshot')
        self.assertEqual(result['registry_scope_formats'],{'cidr':0,'address_range':1})

    def test_cidr_and_range_scopes_share_containment_order_without_splitting(self):
        objects=[record(geofeed=URL),interval('child','11.22.33.63','11.22.33.192',geofeed=OTHER),
                 record('grandchild','11.22.33.128/26',geofeed=URL),
                 interval('no-reference','11.22.33.65','11.22.33.70')]
        result=check(objects)
        self.assertEqual(result['coverage']['4']['this_feed'],'190')
        self.assertEqual(result['coverage']['4']['other_feed'],'66')
        self.assertEqual(result['registry_scope_formats'],{'cidr':2,'address_range':2})
        self.assertEqual(check([record(geofeed=URL)])['scope'],'supplied_unsigned_cidr_snapshot')

    def test_equal_bounds_are_an_unsupported_tie_in_either_input_form(self):
        objects=[record(geofeed=URL),interval('same','11.22.33.0','11.22.33.255',geofeed=URL)]
        result=check(objects)
        self.assertEqual(result['coverage']['4']['ambiguous_reference'],'256')
        self.assertFalse(result['comparison_consistent'])
        self.assertEqual(result['findings'][0]['kind'],'same_scope_resolution_unsupported')

    def test_same_start_same_end_and_adjacent_scopes_have_exact_order(self):
        objects=[interval('parent','11.22.33.0','11.22.33.200',geofeed=URL),
                 interval('child','11.22.33.0','11.22.33.99',geofeed=OTHER),
                 interval('single','11.22.33.0','11.22.33.0',geofeed=URL),
                 interval('sibling','11.22.33.201','11.22.33.255',geofeed=URL)]
        result=check(objects)
        self.assertEqual(result['coverage']['4']['this_feed'],'157')
        self.assertEqual(result['coverage']['4']['other_feed'],'99')
        objects.append(interval('same-end','11.22.33.50','11.22.33.99',geofeed=URL))
        self.assertEqual(check(list(reversed(objects)))['coverage']['4']['other_feed'],'49')

    def test_ipv6_large_range_and_last_address_remain_exact_without_enumeration(self):
        net=ipaddress.ip_network('2001:4860::/32')
        csv=render_csv([{'prefix':str(net),'location':PARENT['location']}])
        objects=[interval('v6',str(net.network_address+1),str(net.broadcast_address-1),geofeed=URL),
                 interval('one',str(net.broadcast_address-1),str(net.broadcast_address-1),geofeed=OTHER)]
        result=check(objects,csv=csv)
        self.assertEqual(result['coverage']['6']['this_feed'],str(2**96-3))
        self.assertEqual(result['coverage']['6']['other_feed'],'1')
        self.assertEqual(result['coverage']['6']['unreferenced'],'2')
        self.assertEqual(result['coverage']['6']['total'],str(2**96))
        root=interval('root','::','ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff',geofeed=URL)
        self.assertTrue(check([root],csv=csv)['comparison_consistent'])

    def test_crossing_referring_scopes_refuse_without_guessing_precedence(self):
        cases=[
            [interval('left','11.22.33.0','11.22.33.130',geofeed=URL),
             interval('right','11.22.33.100','11.22.33.254',geofeed=OTHER+'?PRIVATE')],
            [interval('left','11.22.33.1','11.22.33.200',geofeed=URL),record('right','11.22.33.0/25',geofeed=OTHER)],
            [interval('left','11.22.33.0','11.22.33.10',geofeed=URL),
             interval('right','11.22.33.10','11.22.33.20',geofeed=OTHER)],
            [record(geofeed=URL),interval('outside-a','11.22.40.1','11.22.40.100',geofeed=URL),
             interval('outside-b','11.22.40.50','11.22.40.200',geofeed=URL)],
        ]
        for objects in cases:
            for order in (objects,list(reversed(objects))):
                with self.subTest(objects=order):
                    with self.assertRaisesRegex(GeofeedError,'crossing referring scopes') as error:
                        check(order)
                    self.assertNotIn('PRIVATE',str(error.exception))
                    self.assertNotIn('11.22.',str(error.exception))

    def test_crossing_scope_without_a_reference_does_not_shadow_parent(self):
        result=check([interval('parent','11.22.33.0','11.22.33.200',geofeed=URL),
                      interval('administrative','11.22.33.100','11.22.33.254')])
        self.assertEqual(result['coverage']['4']['this_feed'],'201')
        self.assertEqual(result['coverage']['4']['unreferenced'],'55')

    def test_invalid_scope_forms_are_bounded_and_not_echoed(self):
        bad=[interval(prefix=str(BASE)),interval(end=None),interval(start=1),interval(start=True),
             interval(start=[]),interval(start={}),interval(start='PRIVATE invalid'),
             interval(start='11.22.33.2',end='11.22.33.1'),interval(start='11.22.33.01'),
             interval(end='2001:4860::1'),interval(start=' 11.22.33.1'),interval(end='11.22.33.254\n'),
             interval(start='1'*46),interval(start='2001:4860::1%PRIVATE',end='2001:4860::2'),
             interval(start='2001:4860:0:0:0:0:0:1',end='2001:4860::2'),
             interval(start='2001:486A::1',end='2001:486a::2')]
        missing=interval();del missing['end'];bad.append(missing)
        missing=interval();del missing['start'];bad.append(missing)
        for obj in bad:
            with self.subTest(obj=obj):
                with self.assertRaises(GeofeedError) as error:check([obj])
                self.assertNotIn('PRIVATE',str(error.exception))

    def test_600_mixed_family_cases_match_independent_containment_oracle(self):
        rng=random.Random(9632002);valid=crossing=0
        for case in range(600):
            base=ipaddress.ip_network('11.22.33.0/24' if case%2 else '2001:4860::/120')
            first=int(base.network_address);address=type(base.network_address)
            pool=[(0,255)];frontier=pool[:]
            for depth in range(3):
                children=[]
                for left,right in frontier:
                    if right-left>3:
                        middle=rng.randrange(left+1,right-1)
                        children.extend(((left,middle),(middle+1,right)))
                pool.extend(children);frontier=children
            objects=[];references=[]
            for index in range(rng.randrange(1,12)):
                if case%3:
                    left,right=rng.choice(pool)
                else:
                    left,right=sorted((rng.randrange(256),rng.randrange(256)))
                kind=rng.choice(('this_feed','other_feed','invalid_reference',None))
                url={'this_feed':URL,'other_feed':OTHER,'invalid_reference':'http://invalid.example/'}.get(kind)
                obj=interval(str(index),str(address(first+left)),str(address(first+right)))
                cidrs=list(ipaddress.summarize_address_range(address(first+left),address(first+right)))
                if len(cidrs)==1 and rng.randrange(2):
                    obj=record(str(index),str(cidrs[0]))
                if kind is not None:
                    obj['geofeed']=url;references.append((left,right,kind))
                objects.append(obj)
            feeds={ipaddress.ip_network((address(first+rng.randrange(256)),rng.randrange(base.prefixlen,base.max_prefixlen+1)),strict=False)
                   for _ in range(rng.randrange(1,5))}
            csv=render_csv([{'prefix':str(net),'location':PARENT['location']} for net in sorted(feeds)],overlap_policy=LONGEST_PREFIX)
            # Pairwise containment and per-address enumeration are intentionally
            # independent of the production stack and width-priority sweep.
            incompatible=any(a<c<=b<d or c<a<=d<b for a,b,_ in references for c,d,_ in references)
            if incompatible:
                with self.assertRaisesRegex(GeofeedError,'crossing referring scopes'):
                    check(objects,csv=csv,overlap_policy=LONGEST_PREFIX)
                crossing+=1;continue
            expected={kind:0 for kind in ('this_feed','other_feed','invalid_reference','unreferenced','ambiguous_reference')}
            for value in range(256):
                if not any(address(first+value) in net for net in feeds):continue
                active=[ref for ref in references if ref[0]<=value<=ref[1]]
                winners=[ref for ref in active if not any(other[0]>=ref[0] and other[1]<=ref[1]
                         and other[:2]!=ref[:2] for other in active)]
                kind='unreferenced' if not winners else 'ambiguous_reference' if len(winners)>1 else winners[0][2]
                expected[kind]+=1
            actual=check(objects,csv=csv,overlap_policy=LONGEST_PREFIX)['coverage'][str(base.version)]
            self.assertEqual({kind:int(actual[kind]) for kind in expected},expected,f'case {case}')
            valid+=1
        self.assertGreater(valid,350);self.assertGreater(crossing,70)

    def test_range_cli_preserves_files_and_never_accesses_configuration_credentials_or_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'registry.json';feed=root/'feed.csv';status=root/'status.json'
            source.write_bytes(snapshot([interval('whole','11.22.33.0','11.22.33.255',geofeed=URL)]))
            feed.write_bytes(CSV);status.write_bytes(b'failed status')
            before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()}
            output=io.StringIO()
            with patch('isp_geofeed_generator.cli.load_config',side_effect=AssertionError('config read')), \
                 patch.object(CredentialStore,'get',side_effect=AssertionError('credential read')), \
                 patch.object(JsonHTTP,'request',side_effect=AssertionError('network read')), \
                 patch('isp_geofeed_generator.cli.atomic_write',side_effect=AssertionError('output write')), \
                 contextlib.redirect_stdout(output):
                self.assertEqual(main(['check-registry','--config',str(root/'missing.yaml'),'--registry-records',str(source),
                                       '--feed',str(feed),'--feed-url',URL]),0)
            self.assertEqual(json.loads(output.getvalue())['registry_scope_formats'],{'cidr':0,'address_range':1})
            self.assertEqual({p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in root.iterdir()},before)

    def test_private_mutations_fail_the_relevant_controls_with_intact_code_passing(self):
        source=Path(registry_check.__file__).read_text(encoding='utf-8')
        controls=[
            ('inclusive-end','events[scope.end + 1]','events[scope.end]',
             'test_exact_inclusive_range_does_not_widen_or_drop_endpoints'),
            ('specificity','(scope.end - scope.start, index)','(-(scope.end - scope.start), index)',
             'test_cidr_and_range_scopes_share_containment_order_without_splitting'),
            ('crossing-guard','    _check_hierarchy(references)\n','    # Removed only in this private control copy.\n',
             'test_crossing_referring_scopes_refuse_without_guessing_precedence'),
        ]
        def run(method):
            result=unittest.TestResult()
            RegistryRangeTests(method).run(result)
            return result
        for name,find,replacement,method in controls:
            with self.subTest(mutation=name):
                self.assertTrue(run(method).wasSuccessful(),'intact control passes before mutation')
                self.assertEqual(source.count(find),1,'mutation changes exactly one guard')
                module=types.ModuleType('isp_geofeed_generator._private_range_control')
                module.__package__='isp_geofeed_generator'
                with patch.dict(sys.modules,{module.__name__:module}):
                    exec(compile(source.replace(find,replacement),'<private registry range control>','exec'),module.__dict__)
                    with patch.object(registry_check,'check_snapshot',module.check_snapshot):
                        result=run(method)
                self.assertEqual(result.errors,[],'mutation is detected by assertions, not setup errors')
                self.assertGreater(len(result.failures),0,'removed guard must fail the relevant control')
                self.assertTrue(run(method).wasSuccessful(),'intact control passes after mutation')
                print('REGISTRY RANGE MUTATION OBSERVATION: '+json.dumps({'mutation':name,'assertion_failures':len(result.failures),
                    'errors':len(result.errors),'intact_before_after':True}))
