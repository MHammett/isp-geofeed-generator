# How pools relate to network sites

The project checked Sonar's public docs, a local documentation crawl, and the live v2 schema on November 15, 2026.
The live schema supported the fields used by the discovery workload.

The [IPAM overview](https://docs.sonar.expert/networking/ipam-overview) shows a pool's subnet,
DHCP servers, LTE EPCs and IP assignments. It does not define a hosting-site field.
The [pool API type](https://api.sonar.software/ippool.doc.html) has the same relationships.
The [network-site API type](https://api.sonar.software/networksite.doc.html) exposes addresses,
inventory and IP assignments, but no pool-ownership relationship.

The [IP assignment guide](https://docs.sonar.expert/networking/assigning-an-ip-address-using-sonar-s-ipam-how-to)
and [reports guide](https://docs.sonar.expert/reporting/understanding-sonar-reports) explain the indirect link.
An assignment has an `ip_pool_id` and an owner. The owner may be a site, an inventory item,
or an inventory model field on that item. The item's holder can be a network site.

Discovery follows these paths:

```text
Network site -> IP assignment -> IP pool
Network site -> Inventory item -> IP assignment -> IP pool
Network site -> Inventory item -> Model field -> IP assignment -> IP pool
```

An address from a shared pool can be used at more than one site. It may also be used by site equipment
that is a customer of another facility. An unused pool may have no assignments at all.
For those reasons, the discovered site IDs are candidates, even when only one is found.

The publisher can use the operator's reviewed `pool_sites` mapping. It reads fresh site locations each run.
It does not infer ownership from names, pollers, or one observed customer-address assignment.
It does not fall back to a default city when a mapping is missing.

An additional controller path is now supported. Pools link to DHCP servers and parent subnets link to inline devices.
When the controller's exact management IP is assigned to site inventory, its hosting site can be resolved.
`source.site_resolution: controllers` enables that policy. Global/disabled controllers are excluded,
and missing or conflicting site assignments require explicit configuration.
This describes the controller's hosting facility, which can differ from the customer service area.
See [operator setup](operator-setup.md) for the records needed and provisioning considerations.

All paginated results must be complete. Nested results use a bounded first page and a separately paginated
query when needed. Duplicate records, changing totals and count mismatches stop the run.
Sonar is not a transactional snapshot API, so an edit that preserves all counts can still occur during a read.
Avoid running discovery during major IPAM changes and review the resulting candidate feed.
