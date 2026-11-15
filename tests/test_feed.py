import copy
import ipaddress
import unittest
from isp_geofeed_generator.client import GeofeedError
from isp_geofeed_generator.feed import build, change_guard, location, parse_feed, prefixes, public


def snapshot():
    return {'pools': [{'id': '101', 'name': 'Example pool', 'ip_range': '11.22.33.2-11.22.33.126',
                      'subnet': {'subnet': '11.22.33.0/25'}}],
            'sites': [{'id': '11', 'name': 'Example facility', 'addresses': [
                {'id': '501', 'city': 'Example City', 'country': 'US', 'subdivision': 'US_IL'}]}]}


def config():
    return {'pool_sites': {'101': '11'}, 'allowed_prefixes': ['11.22.33.0/24']}


class FeedTests(unittest.TestCase):
    def test_exact_range_does_not_expand_to_parent_subnet(self):
        data, report = build(snapshot(), config())
        networks = parse_feed(data)
        self.assertEqual(sum(n.num_addresses for n in networks), 125)
        self.assertEqual(networks[0].network_address, ipaddress.ip_address('11.22.33.2'))
        self.assertEqual(networks[-1].broadcast_address, ipaddress.ip_address('11.22.33.126'))
        self.assertIn(b',US,US-IL,Example City,\n', data)
        self.assertEqual(report[0]['site_id'], '11')

    def test_unmapped_public_pool_fails(self):
        c = config(); c['pool_sites'] = {}
        with self.assertRaisesRegex(GeofeedError, 'no pool_sites'):
            build(snapshot(), c)

    def test_unknown_and_conflicting_mappings_fail(self):
        for c in ({**config(), 'pool_sites': {'101': '999'}},
                  {**config(), 'pool_sites': {'999': '11'}},
                  {**config(), 'exclude_pools': {'101': 'reason'}}):
            with self.subTest(config=c), self.assertRaises(GeofeedError): build(snapshot(), c)

    def test_exclusions_need_reason_and_cannot_empty_feed(self):
        for reason in ('', 'unused'):
            c = config(); c['pool_sites'] = {}; c['exclude_pools'] = {'101': reason}
            with self.assertRaises(GeofeedError): build(snapshot(), c)

    def test_nonpublic_pool_never_published(self):
        s = snapshot()
        s['pools'].append({'id': '102', 'ip_range': '100.64.0.1-100.64.0.10'})
        data, report = build(s, config())
        self.assertNotIn(b'100.64', data)
        self.assertEqual(report[-1]['result'], 'nonpublic')
        for n in ('10.0.0.0/8', '100.64.0.0/10', '192.0.2.0/24', '224.0.0.0/4',
                  'fc00::/7', 'ff00::/8', '2001:db8::/32', '3fff::/20', '2000::/3'):
            self.assertFalse(public(ipaddress.ip_network(n)), n)

    def test_ipv6_exact_range(self):
        nets = prefixes('2001:4860:1234::2-2001:4860:1234::e')
        self.assertEqual(sum(n.num_addresses for n in nets), 13)
        self.assertTrue(all(public(n) for n in nets))

    def test_bad_ranges_rejected(self):
        for value in ('11.0.0.9-11.0.0.2', '11.0.0.1/24', 'oops', '11.0.0.1-::1'):
            with self.subTest(value=value), self.assertRaises(GeofeedError): prefixes(value)

    def test_pool_must_fit_parent_and_owned_space(self):
        s = snapshot(); s['pools'][0]['subnet']['subnet'] = '11.22.34.0/24'
        with self.assertRaisesRegex(GeofeedError, 'parent subnet'): build(s, config())
        c = config(); c['allowed_prefixes'] = ['11.22.34.0/24']
        with self.assertRaisesRegex(GeofeedError, 'allowed_prefixes'): build(snapshot(), c)

    def test_duplicate_or_overlapping_pools_fail(self):
        s = snapshot(); p = copy.deepcopy(s['pools'][0]); p['id'] = '102'; s['pools'].append(p)
        c = config(); c['pool_sites']['102'] = '11'
        with self.assertRaisesRegex(GeofeedError, 'Overlapping'): build(s, c)

    def test_ambiguous_site_addresses_require_selection(self):
        s = snapshot(); site = s['sites'][0]; a = dict(site['addresses'][0]); a['id'] = '502'; site['addresses'].append(a)
        with self.assertRaisesRegex(GeofeedError, 'exactly one'): build(s, config())
        c = config(); c['site_locations'] = {'11': {'address_id': '501'}}
        build(s, c)

    def test_location_validation_and_privacy(self):
        site = snapshot()['sites'][0]
        site['addresses'][0].update({'line1': 'secret street', 'zip': '99999'})
        self.assertEqual(location(site), ('US', 'US-IL', 'Example City', ''))
        for override in ({'city': 'Town, State'}, {'city': 'Bad\nCity'}, {'city': '#x'},
                         {'country': ''}, {'region': 'GB-ENG'}, {'city': ''}):
            with self.subTest(override=override), self.assertRaises(GeofeedError): location(site, override)

    def test_parse_rejects_noncanonical_html_and_duplicate_ranges(self):
        for data in (b'<html>no</html>', b'11.0.0.0/24,US,US-IL,City,12345\n',
                     b'11.0.0.1/24,US,US-IL,City,\n', b'11.0.0.0/24,US,US-IL,"City",\n',
                     b'11.0.0.0/24,US,US-IL,City,\n' * 2,
                     b'11.0.0.0/24,US,US-IL,City,\r\n'):
            with self.subTest(data=data), self.assertRaises(GeofeedError): parse_feed(data)

    def test_removal_guard_measures_addresses_not_rows(self):
        old = b'11.0.0.0/24,US,US-IL,City,\n'
        equivalent = b'11.0.0.0/25,US,US-IL,City,\n11.0.0.128/25,US,US-IL,City,\n'
        change_guard(old, equivalent)
        with self.assertRaisesRegex(GeofeedError, 'removal'): change_guard(old, equivalent.splitlines(keepends=True)[0])
        with self.assertRaises(GeofeedError): change_guard(old, b'')

    def test_ipv6_family_removal_guard(self):
        old = b'2001:4860:1234::/64,US,US-IL,City,\n11.0.0.0/24,US,US-IL,City,\n'
        with self.assertRaisesRegex(GeofeedError, 'IPv6'): change_guard(old, b'11.0.0.0/24,US,US-IL,City,\n')
