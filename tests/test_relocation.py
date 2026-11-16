"""Location changes are measured by retained address coverage, not row count."""
import contextlib
import copy
import io
import ipaddress
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from isp_geofeed_generator.client import GeofeedError
from isp_geofeed_generator.feed import change_guard, digest
from isp_geofeed_generator.publish import publish_file, publish_wordpress
from isp_geofeed_generator.records import publish_records_file
from isp_geofeed_generator.cli import main
from isp_geofeed_generator.adapters import SOURCES
from isp_geofeed_generator.contracts import SourceAdapter
from test_publish import FakeWP, OLD, NEW
from test_feed import snapshot
from bogon_fixture import policy


def csv(prefix, city='City', country='US', region='US-IL'):
    return f'{prefix},{country},{region},{city},\n'.encode()


class RelocationTests(unittest.TestCase):
    def test_default_file_guard_stops_move_before_writing_or_replacing_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'public.csv';publish_file(target,OLD,tmp)
            backup=(Path(tmp)/'before.csv').read_bytes()
            with self.assertRaisesRegex(GeofeedError,'location changes'):publish_file(target,NEW,tmp)
            self.assertEqual(target.read_bytes(),OLD);self.assertEqual((Path(tmp)/'before.csv').read_bytes(),backup)

    def test_default_wordpress_guard_stops_move_before_any_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            wp=FakeWP()
            with self.assertRaisesRegex(GeofeedError,'location changes'):publish_wordpress(wp,NEW,tmp)
            self.assertEqual(wp.writes,[]);self.assertEqual(wp.csv,OLD)

    def test_equivalent_split_merge_and_order_do_not_count_as_relocation(self):
        old=csv('11.0.0.0/24')
        split=csv('11.0.0.128/25')+csv('11.0.0.0/25')
        change_guard(old,split,max_relocated_fraction=0)
        change_guard(split,old,max_relocated_fraction=0)

    def test_country_region_and_city_changes_are_guarded_without_location_leaks(self):
        for new in (csv('11.0.0.0/24','Private New City'),csv('11.0.0.0/24',region='US-CA'),
                    csv('11.0.0.0/24',country='CA',region='CA-ON')):
            with self.assertRaisesRegex(GeofeedError,'IPv4 location changes') as caught:change_guard(csv('11.0.0.0/24'),new)
            self.assertNotIn('Private New City',str(caught.exception));self.assertNotIn('CA-ON',str(caught.exception))

    def test_many_changed_rows_with_small_address_coverage_can_pass(self):
        new=b''.join(csv(f'11.0.0.{n}/32','Other City') for n in range(16))
        new+=b''.join(csv(net) for net in ipaddress.summarize_address_range(ipaddress.ip_address('11.0.0.16'),ipaddress.ip_address('11.0.0.255')))
        change_guard(csv('11.0.0.0/24'),new)

    def test_address_families_are_measured_separately(self):
        old=csv('11.0.0.0/24')+csv('2001:4860::/32')
        for new,family in ((csv('11.0.0.0/24','Other')+csv('2001:4860::/32'),'IPv4'),
                           (csv('11.0.0.0/24')+csv('2001:4860::/32','Other'),'IPv6')):
            with self.assertRaisesRegex(GeofeedError,family+' location changes'):change_guard(old,new)

    def test_ipv6_threshold_uses_exact_integer_coverage(self):
        net=ipaddress.ip_network('2001:4860::/32');low,high=list(net.subnets())
        exact=csv(low,'Other')+csv(high)
        change_guard(csv(net),exact,max_relocated_fraction=0.5)
        # One address above a 50% threshold disappears in a floating-point ratio.
        extra=csv(low,'Other')+csv(str(high.network_address)+'/128','Other')
        extra+=b''.join(csv(n) for n in ipaddress.summarize_address_range(high.network_address+1,high.broadcast_address))
        with self.assertRaisesRegex(GeofeedError,'IPv6 location changes'):change_guard(csv(net),extra,max_relocated_fraction=0.5)

    def test_removal_cannot_dilute_changed_retained_location_coverage(self):
        old=csv('11.0.0.0/24');new=csv('11.0.0.0/25','Other')
        with self.assertRaisesRegex(GeofeedError,'removal'):change_guard(old,new)
        with self.assertRaisesRegex(GeofeedError,'location changes'):change_guard(old,new,1.0)

    def test_ipv6_withdrawal_boundary_cannot_round_away_one_address(self):
        net=ipaddress.ip_network('2001:4860::/32');_,high=list(net.subnets())
        remaining=b''.join(csv(n) for n in ipaddress.summarize_address_range(high.network_address+1,high.broadcast_address))
        with self.assertRaisesRegex(GeofeedError,'IPv6 feed removal'):change_guard(csv(net),remaining,0.5)

    def test_new_space_and_first_publication_have_no_relocation_baseline(self):
        change_guard(b'',csv('11.0.0.0/24','Other'))
        change_guard(csv('11.0.0.0/24'),csv('11.0.0.0/24')+csv('11.0.1.0/24','Other'))

    def test_unicode_normalization_and_numeric_representation_do_not_move_locations(self):
        change_guard(csv('11.0.0.0/24','Caf\u00e9'),csv('11.0.0.0/24','Cafe\u0301'),max_relocated_fraction=0)
        from isp_geofeed_generator.relocation import relocation_guard
        old=[{'prefix':'11.0.0.0/24','location':{'latitude':1,'longitude':2}}]
        new=[{'prefix':'11.0.0.0/24','location':{'latitude':1.0,'longitude':2.0}}]
        relocation_guard(old,new,0)

    def test_invalid_relocation_thresholds_fail(self):
        for value in (-1,2,True,float('nan'),float('inf'),'0.1'):
            with self.assertRaises(GeofeedError):change_guard(OLD,NEW,max_relocated_fraction=value)

    def test_json_coordinates_and_profile_changes_are_guarded(self):
        records=[{'prefix':'11.0.0.0/24','location':{'latitude':41.9,'longitude':-88.7}}]
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'records.json';publish_records_file(target,records,tmp)
            before=target.read_bytes()
            for changed in ({'latitude':42.0,'longitude':-88.7}, {'country':'US','region':'US-IL','city':'City'},
                            {'latitude':41.9,'longitude':-88.7,'accuracy_km':10}):
                with self.assertRaisesRegex(GeofeedError,'location changes'):
                    publish_records_file(target,[{'prefix':'11.0.0.0/24','location':changed}],tmp)
                self.assertEqual(target.read_bytes(),before)


class RelocationApprovalTests(unittest.TestCase):
    def test_cli_approval_binds_exact_candidate_and_keeps_other_guards(self):
        value=snapshot();value['pools'][0]['ip_range']='11.22.33.0/24';value['pools'][0]['subnet']={'subnet':'11.22.33.0/24'}
        class Source:
            def snapshot(self):return copy.deepcopy(value)
            def for_publication(self,data):return data
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target=root/'feed.csv';path=root/'config.yaml';candidate=root/'candidate.csv'
            path.write_text(f'source: {{type: fixture}}\nstate_dir: {root.as_posix()}/state\nallowed_prefixes: [11.22.33.0/24, 14.102.240.0/20]\npool_sites: {{"101": "11"}}\npublish: {{type: file, path: {target.as_posix()}}}\n')
            args=['publish','--config',str(path)]
            with patch.dict(SOURCES,fixture=SourceAdapter(lambda s,c:Source(),initial=False)),patch('isp_geofeed_generator.cli.load_policy',side_effect=lambda c:policy()),contextlib.redirect_stderr(io.StringIO()) as errors,contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(args),0);old=target.read_bytes()
                value['sites'][0]['addresses'][0]['city']='Reviewed City'
                self.assertEqual(main(args),1);self.assertEqual(target.read_bytes(),old)
                self.assertEqual(main(['generate','--config',str(path),'--output',str(candidate)]),0)
                approved=digest(candidate.read_bytes())
                self.assertEqual(main(args+['--approve-location-changes','0'*64]),1);self.assertEqual(target.read_bytes(),old)
                self.assertEqual(main(args+['--approve-location-changes',approved]),0)
                self.assertEqual(target.read_bytes(),candidate.read_bytes())
                status=json.loads((root/'state/status.json').read_text())['data']
                self.assertEqual(status['location_change_approval_sha256'],approved)
                good=target.read_bytes()
                value['pools'][0]['ip_range']='11.22.33.0/25'
                self.assertEqual(main(['generate','--config',str(path),'--output',str(candidate)]),0)
                self.assertEqual(main(args+['--approve-location-changes',digest(candidate.read_bytes())]),1)
                self.assertEqual(target.read_bytes(),good)
                value['pools'][0].update(ip_range='14.102.240.0/24',subnet={'subnet':'14.102.240.0/20'})
                self.assertEqual(main(args+['--approve-location-changes',approved]),1)
                self.assertEqual(target.read_bytes(),good);self.assertIn('bogon',errors.getvalue())

    def test_approval_option_is_publish_only_and_requires_a_sha256(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['generate','--approve-location-changes','a'*64]),1)
            self.assertEqual(main(['publish','--approve-location-changes','invalid']),1)
