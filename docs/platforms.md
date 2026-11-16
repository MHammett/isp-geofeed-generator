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
| Sonar v2 | IPv4 pools and explicitly selected IPv4/IPv6 subnets; site addresses, explicit mappings, controller-to-inventory resolution | Select service subnet IDs for IPv6. Link them to inline devices. Record controller management IPs on site inventory. Resolve shared/remote-controller cases explicitly. | Subnet fields and controller/site links checked read-only live; positive IPv6 output and failure cases fixture-tested. No live IPv6 subnet or production publication trial. |
| NetBox | Prefixes and ranges; explicit site/location, prefix-field or Region-hierarchy location modes | Select one location model, tag or select intended records, and supply complete data in that model. | Site-mode read-only live 4.7.3 inventory; alternate modes have synthetic CLI and installed-wheel checks, with no live alternate-model publication. |
| Splynx API v2 | Initial IPv4/IPv6 network adapter; signed authentication | Select endnet pool/static networks, map them to network sites, and set geofeed location values. Administrative locations are not assumed to identify one facility. | Vendor release-6.0 schema and synthetic fixtures. Not live-tested. |
| phpIPAM | Initial subnet/location adapter | Select intended subnets, assign locations, and set geofeed location values. | Public API reference and synthetic fixtures. Not live-tested. |
| Powercode legacy API | Initial exact-range adapter for the public V20 `readAddressRanges` contract | Select ranges and define reviewed facility IDs, pool mappings and coarse locations. The export does not supply a native site join. | Public operation definitions, form transport and synthetic failure checks. Not live-tested; current REST and native joins remain separate work. |
| VISP | API investigation tracked separately | Public docs describe access and GraphQL. A usable IPAM/site query shape still needs verification. | Authentication docs reviewed; no adapter claimed. |
| Azotel SIMPLer | API investigation tracked separately | Public docs describe SOAP/REST access. IP pool/site read operations still need verification. | Documentation reviewed; no adapter claimed. |
| Vision by Fibersmith | Research only | Native IP pool and hardware/location models exist. Check the company's API version and export/report access. | Public generic OpenAPI reviewed; no pool-read contract or live test claimed. |
| Nucleo | Research only | Internal sites can have subnets. API read/export shape needs verification. | Public migration model reviewed; no adapter claimed. |
| UISP | Research only | Maintain infrastructure sites and device assignments; verify pool hosting separately from CRM customer endpoints. | Vendor API/site guides and existing integration code reviewed; no adapter claimed. |
| gaiia | Initial native network-site/IP-block adapter | Assign IP blocks and structured addresses to sites; select native site or block IDs; grant only required reads. | Queries validated against the published schema, plus synthetic paging/failure checks. No authenticated tenant reads or live publication measured. |
| BillMax | Next API candidate | Verify native pool/site reads, permissions and pagination for the chosen version. | Public API entry point found. No adapter claimed. |
| Other conference leads | Discovery only | Product and module may differ. | See the dated [research record](platform-research.md); no support claimed. |

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

See [platform research](platform-research.md) for the named vendors, conference leads and source links.
See [prior art](prior-art.md) for existing NetBox generators, ISP integration code and validator limits.
