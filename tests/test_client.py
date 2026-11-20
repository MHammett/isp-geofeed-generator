import unittest
from isp_geofeed_generator.client import GeofeedError, Sonar, https_url


class FakeHTTP:
    def __init__(self, results): self.results, self.calls = list(results), []
    def request(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.results.pop(0)


def page(ids, current=1, pages=1, total=None):
    return {'data': {'ip_pools': {'entities': [{'id': str(i)} for i in ids],
        'page_info': {'page': current, 'total_pages': pages, 'total_count': len(ids) if total is None else total}}}}


class ClientTests(unittest.TestCase):
    def test_candidate_discovery_paginates_nested_connections(self):
        def conn(rows, total=None):
            return {'entities': rows, 'page_info': {'total_count': len(rows) if total is None else total}}
        def assigned(pid): return {'id': str(pid), 'ip_pool_id': str(pid)}
        assignment = conn([assigned(101)])
        site = {'id': '11', 'ip_assignments': conn([], 1),
                'inventory_items': conn([], 1)}
        item = {'id': '44', 'ip_assignments': assignment,
                'inventory_model_field_data': conn([], 1)}
        field = {'id': '55', 'ip_assignments': conn([], 1)}
        def paged(root, rows):
            return {'data': {root: {'entities': rows, 'page_info': {'page': 1, 'total_pages': 1, 'total_count': len(rows)}}}}
        http = FakeHTTP([paged('network_sites', [site]), paged('ip_assignments', [assigned(102)]),
                         paged('inventory_items', [item]), paged('inventory_model_field_data', [field]),
                         paged('ip_assignments', [assigned(103)])])
        sonar = Sonar('https://sonar.example.net', 'example-token', http=http)
        self.assertEqual(sonar.assignment_candidates([{'id': '11'}]), {'101': ['11'], '102': ['11'], '103': ['11']})
        self.assertEqual(len(http.calls), 5)

    def test_multi_page_reads_all_and_uses_string_ids(self):
        http = FakeHTTP([page([1, 2], pages=2, total=3), page([3], current=2, pages=2, total=3)])
        sonar = Sonar('https://sonar.example.net', 'example-token', http=http)
        self.assertEqual([r['id'] for r in sonar.pages('ip_pools', 'id')], ['1', '2', '3'])
        self.assertEqual(http.calls[1][1]['body']['variables']['page'], 2)

    def test_partial_errors_and_missing_data_are_failure(self):
        for result in ({'data': {}, 'errors': [{'message': 'secret upstream detail'}]}, {'data': None}, []):
            sonar = Sonar('https://sonar.example.net', 'example-token', http=FakeHTTP([result]))
            with self.assertRaisesRegex(GeofeedError, 'GraphQL') as ctx: sonar.query('{x}')
            self.assertNotIn('secret', str(ctx.exception))

    def test_pagination_guards(self):
        cases = [[page([1], total=2)], [page([1], pages=2, total=2), page([1], current=2, pages=2, total=2)],
                 [page([1], pages=2, total=2), page([2], current=2, pages=2, total=3)],
                 [page([], pages=2, total=2)], [{'data': {'ip_pools': {}}}]]
        for results in cases:
            with self.subTest(results=results), self.assertRaises(GeofeedError):
                Sonar('https://sonar.example.net', 'example-token', http=FakeHTTP(results)).pages('ip_pools', 'id')

    def test_no_pools_is_not_a_successful_measurement(self):
        with self.assertRaisesRegex(GeofeedError, 'not measured'):
            Sonar('https://sonar.example.net', 'example-token', http=FakeHTTP([page([])])).snapshot()

    def test_https_and_credentials_required(self):
        for url in ('http://example.net', 'https://user:secret@example.net', 'https://example.net/?token=x', ''):
            with self.assertRaises(GeofeedError): https_url(url)
        with self.assertRaises(GeofeedError): Sonar('https://example.net', '')
