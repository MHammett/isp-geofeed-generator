"""Sonar subnet reads and controller evidence, without customer or production writes."""
import contextlib
import copy
import io
import ipaddress
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from isp_geofeed_generator.client import GeofeedError, Sonar
from isp_geofeed_generator.cli import load_config, main
from isp_geofeed_generator.feed import build, parse_feed
from test_client import FakeHTTP
from bogon_fixture import policy

V6 = '2001:4860:1234::/48'
SITE = {'id': '11', 'name': 'Example facility', 'addresses': {
    'page_info': {'total_count': 1}, 'entities': [{'id': '501', 'country': 'US', 'subdivision': 'US_IL', 'city': 'Example City'}]}}
POOL = {'id': '101', 'ip_range': '11.22.33.2-11.22.33.126', 'subnet_id': '101', 'subnet': {'subnet': '11.22.33.0/24'}}
SUBNET = {'id': '101', 'name': 'Service prefix', 'subnet': V6, 'type': 'ACCOUNT'}


def connection(rows, total=None):
    return {'entities': rows, 'page_info': {'total_count': len(rows) if total is None else total}}


def inline(identifier='1', ip='2001:4860::1', **changes):
    return {'id': identifier, 'ip_address': ip, 'enabled': True, 'all_subnets': False,
            'subnets': connection([{'id': '101'}]), **changes}


def owner(kind='field', site='11'):
    if kind == 'direct': return {'__typename': 'NetworkSite', 'id': site}
    item = {'__typename': 'InventoryItem', 'inventoryitemable_type': 'NetworkSite', 'inventoryitemable_id': site}
    if kind == 'address':
        item = {'__typename': 'InventoryItem', 'inventoryitemable_type': 'Address',
                'inventoryitemable': {'__typename': 'Address', 'addressable_type': 'NetworkSite', 'addressable_id': site}}
    if kind == 'field':
        return {'__typename': 'InventoryModelFieldData', 'inventory_item': owner('address', site)}
    return item


class Fixture(Sonar):
    def __init__(self, settings=None, *, pools=None, subnets=None, controllers=None, owners=None):
        super().__init__('https://sonar.example.net', 'test-token', settings=settings)
        self.rows = {'ip_pools': [POOL] if pools is None else pools,
                     'subnets': [SUBNET] if subnets is None else subnets,
                     'network_sites': [SITE], 'dhcp_servers': [],
                     'inline_devices': [inline()] if controllers is None else controllers}
        self.owners = owners or {}
        self.calls = []

    def pages(self, root, fields, **kwargs):
        self.calls.append((root, fields, kwargs))
        if root == 'ip_assignments':
            ip = kwargs['variables']['ip']
            return copy.deepcopy(self.owners.get(ip, [{'id': '701', 'subnet': ip, 'ipassignmentable': owner()}]))
        return copy.deepcopy(self.rows[root])


def settings(**extra):
    return {'pool_ids': [], 'subnet_ids': ['101'], 'site_resolution': 'controllers', **extra}


def configuration(**extra):
    return {'allowed_prefixes': ['11.22.33.0/24', '2001:4860::/32'], **extra}


class SonarSubnetTests(unittest.TestCase):
    def test_ipv6_only_exact_subnet_and_inline_site_without_pool_permissions(self):
        source = Fixture(settings())
        snap = source.snapshot()
        selected = source.for_publication(snap)
        csv, report = build(selected, configuration())
        self.assertEqual(csv, (V6 + ',US,US-IL,Example City,\r\n').encode())
        self.assertEqual(report[0]['pool_id'], 'subnet:101')
        self.assertNotIn('ip_pools', [call[0] for call in source.calls])
        self.assertNotIn('dhcp_servers', [call[0] for call in source.calls])
        self.assertEqual(snap['controller_candidates']['subnet:101']['controllers'][0]['kind'], 'inline')

    def test_legacy_default_does_not_read_subnets_or_change_ids(self):
        source = Fixture()
        snap = source.snapshot()
        self.assertNotIn('subnets', [call[0] for call in source.calls])
        self.assertEqual(source.for_publication(snap), snap)
        csv, _ = build(snap, configuration(pool_sites={'101': '11'}))
        self.assertEqual(sum(net.num_addresses for net in parse_feed(csv)), 125)

    def test_mixed_families_preserve_distinct_pool_and_subnet_ids(self):
        source = Fixture(settings(pool_ids=['101']))
        rows = source.for_publication(source.snapshot())['pools']
        self.assertEqual({r['id'] for r in rows}, {'101', 'subnet:101'})
        csv, _ = build({'pools': rows, 'sites': [dict(SITE, addresses=SITE['addresses']['entities'])]}, configuration())
        self.assertEqual({n.version for n in parse_feed(csv)}, {4, 6})
        self.assertEqual(sum(n.num_addresses for n in parse_feed(csv) if n.version == 4), 125)

    def test_empty_subnet_selection_is_discovery_only(self):
        source = Fixture(settings(subnet_ids=[]))
        snap = source.snapshot()
        self.assertEqual(snap['pools'][0]['id'], 'subnet:101')
        with self.assertRaisesRegex(GeofeedError, 'explicitly selected'): source.for_publication(snap)

    def test_ipv6_only_instance_works_without_ipv4_pools(self):
        source = Fixture({'subnet_ids': ['101'], 'site_resolution': 'controllers'}, pools=[])
        self.assertEqual(source.for_publication(source.snapshot())['pools'][0]['id'], 'subnet:101')

    def test_missing_selected_ids_fail_instead_of_silently_losing_a_family(self):
        for options in (settings(subnet_ids=['999']), settings(pool_ids=['999'])):
            source = Fixture(options)
            with self.assertRaisesRegex(GeofeedError, 'no longer exist'): source.for_publication(source.snapshot())

    def test_subnet_ids_are_validated_before_network_access(self):
        for value in (None, '101', [101], ['101', '101'], ['subnet:101'], ['0'], ['1\n'], [True]):
            with self.subTest(value=value), self.assertRaisesRegex(GeofeedError, 'digit-string'):
                Fixture(settings(subnet_ids=value))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'config.yaml'; path.write_text('source: {type: sonar, subnet_ids: [101]}')
            with self.assertRaisesRegex(GeofeedError, 'digit-string'): load_config(path)

    def test_bad_prefix_type_and_excluded_subnet_fail_safely(self):
        for changes in ({'subnet': 'private upstream garbage'}, {'subnet': '2001:4860:1234::1/48'}, {'type': None}, {'id': 'private street'}):
            with self.subTest(changes=changes), self.assertRaises(GeofeedError) as caught:
                Fixture(settings(), subnets=[{**SUBNET, **changes}]).snapshot()
            self.assertNotIn('private', str(caught.exception))
        source = Fixture(settings(), subnets=[{**SUBNET, 'type': 'EXCLUDED'}])
        with self.assertRaisesRegex(GeofeedError, 'EXCLUDED'): source.for_publication(source.snapshot())

    def test_all_supported_inventory_owners_and_exact_host_assignments(self):
        ip = '2001:4860::1'
        for kind in ('direct', 'item', 'address', 'field'):
            assignments = [{'id': '1', 'subnet': ip+'/128', 'ipassignmentable': owner(kind)},
                           {'id': '2', 'subnet': '2001:4860::/32', 'ipassignmentable': owner('direct', '999')}]
            source = Fixture(settings(), owners={ip: assignments})
            self.assertEqual(source.snapshot()['pools'][0]['site_id'], '11')

    def test_disabled_global_unlinked_and_missing_management_assignment_do_not_guess(self):
        for controllers, owners in (([inline(enabled=False)], {}), ([inline(all_subnets=True)], {}),
                                    ([inline(subnets=connection([]))], {}), ([inline()], {'2001:4860::1': []})):
            source = Fixture(settings(), controllers=controllers, owners=owners)
            snap = source.for_publication(source.snapshot())
            self.assertNotIn('site_id', snap['pools'][0])
            with self.assertRaisesRegex(GeofeedError, 'no pool_sites'): build(snap, configuration())
            self.assertIn(b',US,US-IL,', build(snap, configuration(pool_sites={'subnet:101': '11'}))[0])

    def test_conflicting_controller_sites_require_reviewed_override(self):
        source = Fixture(settings(), controllers=[inline(), inline('2', '2001:4860::2')],
                         owners={'2001:4860::2': [{'id': '2', 'subnet': '2001:4860::2', 'ipassignmentable': owner('direct', '12')}]})
        source.rows['network_sites'].append({**SITE, 'id': '12'})
        snap = source.for_publication(source.snapshot())
        self.assertIsNone(snap['controller_candidates']['subnet:101']['site_id'])
        with self.assertRaisesRegex(GeofeedError, 'conflicting'): build(snap, configuration())
        build(snap, configuration(pool_sites={'subnet:101': '11'}))

    def test_dhcp_pool_link_cannot_be_mistaken_for_same_numbered_subnet(self):
        source = Fixture(settings(pool_ids=['101']), controllers=[])
        source.rows['dhcp_servers'] = [{'id': '1', 'enabled': True, 'serves_all_pools': False,
                                      'ip_address': '11.0.0.1', 'ip_pools': connection([{'id': '101'}])}]
        snap = source.snapshot()
        self.assertEqual(snap['controller_candidates']['101']['site_id'], '11')
        self.assertIsNone(snap['controller_candidates']['subnet:101']['site_id'])

    def test_malformed_or_duplicate_inline_link_metadata_is_not_accepted(self):
        for changes in ({'enabled': 'false'}, {'all_subnets': None},
                        {'subnets': connection([{'id': None}])},
                        {'subnets': connection([{'id': '101'}, {'id': '101'}])},
                        {'subnets': connection([{'id': '101'}], total=0)}):
            with self.assertRaises(GeofeedError): Fixture(settings(), controllers=[inline(**changes)]).snapshot()

    def test_selected_ipv4_subnets_work_and_overlap_is_still_rejected(self):
        subnet = {**SUBNET, 'subnet': '11.22.33.0/24'}
        source = Fixture(settings(), subnets=[subnet])
        self.assertEqual(build(source.for_publication(source.snapshot()), configuration())[0].split(b',')[0], b'11.22.33.0/24')
        source = Fixture(settings(pool_ids=['101']), subnets=[subnet])
        with self.assertRaisesRegex(GeofeedError, 'Overlapping'): build(source.for_publication(source.snapshot()), configuration())

    def test_real_subnet_pagination_and_nested_controller_link_pagination(self):
        def page(root, rows, current=1, pages=1, total=None):
            return {'data': {root: {'entities': copy.deepcopy(rows), 'page_info': {'page': current, 'total_pages': pages, 'total_count': len(rows) if total is None else total}}}}
        source = Sonar('https://example.net', 'token', settings=settings(site_resolution='configured'), http=FakeHTTP([
            page('subnets', [SUBNET], pages=2, total=2), page('subnets', [{**SUBNET, 'id': '102'}], current=2, pages=2, total=2), page('network_sites', [SITE])]))
        self.assertEqual(len(source.snapshot()['pools']), 2)
        self.assertIn('id name subnet type', source.http.calls[0][1]['body']['query'])
        responses = [{'data': {'inline_devices': {'entities': [{'id': '1', 'subnets': {
            'page_info': {'page': n, 'total_pages': 2, 'total_count': 2}, 'entities': [{'id': str(100+n)}]}}]}}} for n in (1, 2)]
        source = Fixture(settings(), controllers=[inline(subnets=connection([{'id': '101'}], total=2))])
        source.http = FakeHTTP(responses)
        self.assertEqual(source.snapshot()['pools'][0]['site_id'], '11')
        source = Fixture(settings(), controllers=[inline(subnets=connection([{'id': '101'}], total=2))])
        source.http = FakeHTTP([{'data': {'inline_devices': {'entities': [{'id': '1', 'subnets': {
            'page_info': {'page': 1, 'total_pages': 1, 'total_count': 1}, 'entities': [{'id': '101'}]}}]}}}])
        with self.assertRaisesRegex(GeofeedError, 'count changed'): source.snapshot()


class SonarSubnetWorkloadTests(unittest.TestCase):
    def test_cli_dual_stack_publication_and_failures_preserve_last_good_feed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); config = root/'config.yaml'; output = root/'public.csv'; candidate = root/'candidate.csv'
            def write(selection='["101"]'):
                config.write_text(f'source: {{type: sonar, subnet_ids: {selection}, site_resolution: controllers}}\n'
                                  f'state_dir: {root.as_posix()}/state\nallowed_prefixes: [11.22.33.0/24, 2001:4860::/32, "4000::/3"]\n'
                                  f'publish: {{type: file, path: {output.as_posix()}}}\n')
            write()
            with patch('isp_geofeed_generator.adapters.Sonar', wraps=Sonar) as factory, patch('isp_geofeed_generator.cli.load_policy', side_effect=lambda c: policy()), patch.dict('os.environ', {'SONAR_API_TOKEN': 'test-token'}), contextlib.redirect_stderr(io.StringIO()) as errors:
                source = Fixture({'subnet_ids': ['101'], 'site_resolution': 'controllers'})
                factory.return_value = source
                self.assertEqual(main(['generate', '--config', str(config), '--output', str(candidate)]), 0)
                self.assertEqual(main(['publish', '--config', str(config)]), 0)
                good = output.read_bytes(); self.assertEqual(good, candidate.read_bytes())
                for failure in ('missing', 'scope', 'bogon', 'withdrawal'):
                    source = Fixture({'subnet_ids': ['101'], 'site_resolution': 'controllers'})
                    if failure == 'missing': source.subnet_ids = {'999'}
                    if failure == 'scope': source.rows['inline_devices'] = []
                    if failure == 'bogon': source.rows['subnets'][0] = {**SUBNET, 'subnet': '4000::/48'}
                    if failure == 'withdrawal': source.subnet_ids = set(); write('[]')
                    factory.return_value = source
                    self.assertEqual(main(['publish', '--config', str(config)]), 1, failure)
                    self.assertEqual(output.read_bytes(), good, failure)
                self.assertIn('bogon', errors.getvalue()); self.assertIn('removal', errors.getvalue())
