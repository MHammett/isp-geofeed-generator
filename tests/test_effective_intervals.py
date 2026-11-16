"""Internal nested analysis is exact; active publication still refuses nesting."""
from dataclasses import asdict
import ipaddress
import json
from pathlib import Path
import random
import unittest
from unittest.mock import patch

from isp_geofeed_generator._effective import MAX_RECORDS, compare_effective, effective_intervals
from isp_geofeed_generator.client import GeofeedError
from isp_geofeed_generator.feed import parse_feed


def record(prefix, city='A', **extra):
    return {'prefix': prefix, 'location': {'country': 'US', 'region': 'US-IL', 'city': city, **extra}}


class EffectiveIntervalsTests(unittest.TestCase):
    def test_design_vectors_match_exact_effective_counts(self):
        vectors=json.loads((Path(__file__).parent/'fixtures/nested-prefix-design.json').read_text())
        self.assertEqual(len(vectors),6)
        for vector in vectors:
            with self.subTest(vector=vector['name']):
                result=compare_effective([record(*row) for row in vector['before']],
                                         [record(*row) for row in vector['after']])
                self.assertEqual(asdict(result[4]),vector['expected'])
                self.assertEqual(asdict(result[6]),dict.fromkeys(vector['expected'],0))

    def test_random_small_ranges_match_independent_address_oracle(self):
        rng=random.Random(1601)
        parent=ipaddress.ip_network('11.22.33.0/24')
        choices=[parent]
        for length in range(25,33):choices.extend(parent.subnets(new_prefix=length))
        def sample():return [record(str(net),rng.choice('ABC')) for net in rng.sample(choices,40)]
        def oracle(rows):
            parsed=[(ipaddress.ip_network(row['prefix']),row['location']['city']) for row in rows]
            values={}
            # Test-only bounded 256-address oracle, independent of the event sweep.
            for address in parent:
                matches=[(net.prefixlen,city) for net,city in parsed if address in net]
                if matches:values[int(address)]=max(matches)[1]
            return values
        for _ in range(30):
            before,after=sample(),sample();old,new=oracle(before),oracle(after)
            retained=old.keys() & new.keys()
            expected={'old':len(old),'new':len(new),'retained':len(retained),
                      'removed':len(old.keys()-new.keys()),'relocated':sum(old[k]!=new[k] for k in retained)}
            self.assertEqual(asdict(compare_effective(before,after)[4]),expected)
            self.assertEqual(asdict(compare_effective(list(reversed(before)),list(reversed(after)))[4]),expected)

    def test_full_ipv6_depth_and_terminal_boundary_without_address_enumeration(self):
        rows=[record(str(ipaddress.IPv6Network((0,length))),str(length)) for length in range(129)]
        with patch.object(ipaddress.IPv6Network,'__iter__',side_effect=AssertionError('address enumeration')):
            intervals=effective_intervals(rows)
            result=compare_effective(rows,rows)[6]
        self.assertEqual(sum(row.stop-row.start for row in intervals),2**128)
        self.assertLessEqual(len(intervals),2*len(rows))
        self.assertEqual(intervals[0].record_index,128)
        self.assertEqual(intervals[-1].stop,2**128)
        self.assertEqual(result.retained,2**128);self.assertEqual(result.relocated,0)
        self.assertEqual(json.loads(json.dumps(result.decimal_counts()))['retained'],str(2**128))

    def test_ipv6_one_address_threshold_excess_is_exact_and_families_do_not_mix(self):
        parent=ipaddress.ip_network('2001:4860::/32');low,high=list(parent.subnets())
        before=[record(str(parent)),record('11.22.33.0/24')]
        after=before+[record(str(low),'B'),record(f'{high.network_address}/128','B')]
        result=compare_effective(before,after)
        self.assertEqual(result[6].retained,2**96)
        self.assertEqual(result[6].relocated,2**95+1)
        self.assertGreater(2*result[6].relocated,result[6].retained)
        self.assertEqual(result[4].relocated,0);self.assertEqual(result[4].retained,256)

    def test_duplicate_prefix_is_refused_even_with_matching_locations(self):
        for city in ('A','B'):
            with self.assertRaisesRegex(GeofeedError,'Duplicate'):
                effective_intervals([record('11.22.33.0/24'),record('11.22.33.0/24',city)])

    def test_every_raw_parent_and_child_requires_complete_valid_profile(self):
        valid=record('11.22.33.0/24')
        invalid=[{'prefix':'11.22.33.0/24','location':{'country':'XX','region':'','city':'Private invalid city'}},
                 {'prefix':'11.22.33.0/25','location':{'city':'Private partial child'}},
                 record('11.22.33.1/24'),record(1),record('11.22.33.0/25',latitude=42)]
        for bad in invalid:
            with self.subTest(bad=bad),self.assertRaises(GeofeedError) as caught:
                effective_intervals([bad,record('11.22.33.0/25'),record('11.22.33.128/25')]
                                    if bad['prefix']=='11.22.33.0/24' else [valid,bad])
            self.assertNotIn('Private',str(caught.exception));self.assertNotIn('XX',str(caught.exception))
        for value in (None,42,True):
            with self.assertRaisesRegex(GeofeedError,'Invalid effective interval records'):effective_intervals(value)

    def test_rich_profile_is_explicit_and_changes_the_entire_location(self):
        before=[record('11.22.33.0/24',latitude=42,longitude=-88)]
        after=before+[record('11.22.33.0/25',latitude=43,longitude=-88)]
        fields={'country','region','city','latitude','longitude'}
        self.assertEqual(compare_effective(before,after,fields=fields)[4].relocated,128)
        with self.assertRaises(GeofeedError):compare_effective(before,after)
        for fields in (set(),{'unknown'},{'latitude'},'city'):
            with self.assertRaisesRegex(GeofeedError,'profile'):effective_intervals([],fields=fields)

    def test_normalization_and_provenance_do_not_create_false_location_change(self):
        before=[record('11.22.33.0/24','Caf\u00e9')]
        after=before+[record('11.22.33.0/25','Cafe\u0301')]
        self.assertEqual(compare_effective(before,after)[4].relocated,0)
        intervals=effective_intervals(after)
        self.assertEqual([row.record_index for row in intervals],[1,0])
        self.assertEqual(intervals[0].location,intervals[1].location)

    def test_maximum_record_budget_and_one_excess_record(self):
        start=int(ipaddress.ip_address('2001:4860::'))
        rows=[record(f'{ipaddress.IPv6Address(start+n)}/128') for n in range(MAX_RECORDS)]
        result=effective_intervals(rows)
        self.assertEqual(len(result),MAX_RECORDS)
        self.assertEqual(sum(row.stop-row.start for row in result),MAX_RECORDS)
        consumed=[]
        def excess():
            for index in range(MAX_RECORDS+100):
                consumed.append(index)
                yield record(f'{ipaddress.IPv6Address(start+index)}/128')
        with self.assertRaisesRegex(GeofeedError,'record limit'):effective_intervals(excess())
        self.assertEqual(len(consumed),MAX_RECORDS+1)

    def test_empty_and_disconnected_family_boundaries_are_exact(self):
        result=compare_effective([],[])
        self.assertEqual(result[4].old,0);self.assertEqual(result[6].retained,0)
        rows=[record('255.255.255.255/32'),record('::/128'),record('ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff/128')]
        intervals=effective_intervals(rows)
        self.assertEqual([(r.version,r.start,r.stop) for r in intervals],
                         [(4,2**32-1,2**32),(6,0,1),(6,2**128-1,2**128)])

    def test_current_publication_parser_still_refuses_nested_records(self):
        rows=[b'11.22.33.0/24,US,US-IL,A,\r\n',b'11.22.33.0/25,US,US-IL,B,\r\n']
        for row in rows:self.assertEqual(len(parse_feed(row)),1)
        with self.assertRaisesRegex(GeofeedError,'Invalid or unsafe geofeed CSV'):parse_feed(b''.join(rows))


if __name__=='__main__':unittest.main()
