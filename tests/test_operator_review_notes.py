import ipaddress
import unittest
from isp_geofeed_generator.client import GeofeedError
from isp_geofeed_generator.relocation import relocation_guard


class OperatorNotes(unittest.TestCase):
    def test_ipv6_location_stop_reports_readable_coverage_and_limit(self):
        parent=ipaddress.ip_network('2001:4860::/32')
        first,second=list(parent.subnets(prefixlen_diff=1))
        host=ipaddress.ip_network(str(second.network_address)+'/128')
        def record(net,city):return {'prefix':str(net),'location':{'country':'US','region':'US-IL','city':city}}
        old=[record(parent,'Old City')]
        half=[record(first,'New City'),record(second,'Old City')]
        tiny=[record(net,'Old City') for net in parent.address_exclude(host)]+[record(host,'New City')]
        boundary=[record(first,'New City')]+[record(net,'Old City') for net in second.address_exclude(host)]+[record(host,'New City')]
        for new,limit,expected in ((half,.1,'50.00%'),(tiny,0,'<0.01%'),(boundary,.5,'50.00% (rounded down)')):
            with self.subTest(limit=limit,expected=expected),self.assertRaises(GeofeedError) as caught:
                relocation_guard(old,new,limit)
            message=str(caught.exception)
            self.assertIn(expected,message);self.assertIn('limit',message)
            self.assertIn('compared exactly',message)
            self.assertNotIn(str(parent.num_addresses),message)
