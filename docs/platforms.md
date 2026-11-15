# Platform capability, setup and verification

These are three separate questions:

1. Can the platform model and expose the required data?
2. Does this operator's instance contain the required records and access settings?
3. Has this adapter been verified against that instance and version?

A missing site assignment is a configuration gap when the platform supports it.
An absent field in the API is an API/model limit for that particular relationship.
An unimplemented adapter or a missing live test is a project gap, not proof that a platform is incapable.

| Source | Implementation | Instance setup | Verification |
| --- | --- | --- | --- |
| Sonar v2 | Pools, site addresses, explicit mappings, optional controller-to-inventory resolution | Link pools to DHCP servers or subnets to inline devices. Record controller management IPs on site inventory. Resolve shared/remote-controller cases explicitly. | Read-only live source queries; synthetic failure tests. Full production publication still needs a trial. |
| NetBox | Prefixes and ranges; site/location scope; explicit selection | Assign scopes, tag or select intended records, and provide structured geofeed location values. | Read-only live 4.7.3 inventory; synthetic generation and failure tests. |
| Splynx API v2 | Initial IPv4/IPv6 network adapter; signed authentication | Select endnet pool/static networks, map them to network sites, and set geofeed location values. Administrative locations are not assumed to identify one facility. | Vendor release-6.0 schema and synthetic fixtures. Not live-tested. |
| phpIPAM | Initial subnet/location adapter | Select intended subnets, assign locations, and set geofeed location values. | Public API reference and synthetic fixtures. Not live-tested. |
| Powercode | API investigation tracked separately | The platform has address ranges and network locations. Needed IPAM read endpoints still need verification for the API/version chosen. | Public REST collection reviewed; no IPAM adapter claimed. |
| VISP | API investigation tracked separately | Public docs describe access and GraphQL. A usable IPAM/site query shape still needs verification. | Authentication docs reviewed; no adapter claimed. |
| Azotel SIMPLer | API investigation tracked separately | Public docs describe SOAP/REST access. IP pool/site read operations still need verification. | Documentation reviewed; no adapter claimed. |

Initial adapters allow discovery and candidate generation. Publication requires an explicit
`source.allow_initial: true` after an operator has checked the candidate and the public publishing path.
That flag records an operator choice. It does not upgrade an adapter to live-verified status.

## Sources used

- [Sonar DHCP setup](https://docs.sonar.expert/networking/setting-up-a-sonar-controlled-mikro-tik-dhcp-server)
- [Sonar DHCP API type](https://api.sonar.software/dhcpserver.doc.html) and [inline-device type](https://api.sonar.software/inlinedevice.doc.html)
- [NetBox prefix scope](https://netboxlabs.com/docs/netbox/models/ipam/prefix/) and [site fields](https://netboxlabs.com/docs/netbox/models/dcim/site/)
- [Splynx public API schema](https://api-doc.splynx.com/release-6.0.json)
- [phpIPAM public API reference](https://phpipam.net/api/api_reference/)
- [Powercode API index](https://api.powercode.com/) and [REST collection](https://restapi.powercode.com/)
- [VISP API introduction](https://visp.net/help_documentation/visp-api/)
- [Azotel API](https://wiki.azotel.com/frequently-asked-questions/simpler-api)

Documentation review never substitutes for a live operator check. Report the version, read permissions,
sanitized response shape and exact failure when contributing feedback. Never post tokens or customer records.
