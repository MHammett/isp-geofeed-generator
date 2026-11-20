# Conference platform API triage

Public sources checked on 2026-11-16 for [issue #13](https://github.com/MHammett/isp-geofeed-generator/issues/13).
The [earlier research](platform-research.md) records which conference lists supplied the
leads. Exhibiting is not evidence of API capability or market share. No customer portal,
tenant data, private API, demo login or vendor contact was used in this pass.

The search covered the named billing/OSS vendors' product, integration and developer
pages, plus the IPAM vendors' public manuals and linked SDK documentation. Search results
for unrelated products named Elements or eLation were excluded. Public retrieval gaps
are recorded below; they do not prove that private documentation or an API is absent.

## Billing and OSS leads

| Product and API family | Positive public evidence | Exact gap before an input adapter |
| --- | --- | --- |
| [GLDS BroadHub / BroadHub Link](https://www2.glds.com/oss/) | Vendor describes OSS integrations and repeatable service workflows. [Support](https://www.glds.com/support/) covers trained users. | This pass did not establish an API version, authentication/role contract, exact IPv4/IPv6 pool reads, stable pool-to-site fields or paging. A working provisioning integration does not define a geofeed export. Obtain version-specific public or shareable read docs. |
| [CDG Elements, including MBS lineage](https://cdg.us/oss-bss-elements/) | Vendor documents network elements, provisioning, reporting and an open architecture. | API family/version, pool/site reads, auth scopes and paging are not established by this product page. The current `cdg.us` pages were retrieved after searching the older `cdg.ws` name. Do not substitute another vendor's Elements API. |
| [CHR Omnia360](https://chrsolutions.com/software-oss-bss/) | Vendor explicitly describes open REST APIs and facilities/GIS functions. | Public product claims do not supply operation/response shapes, version, permissions, pool-to-facility joins or paging. This is a contract gap, not a claim that Omnia360 has no API. Third-party directories that say otherwise are not used as evidence. |
| [Amdocs connectX Inventory](https://devportal.amdocs-dbs.com/domains/Inventory) | Its developer search entry names TMF639 resource inventory and TMF634 resource catalog. [TM Forum's TMF639 specification](https://projects.tmforum.org/open-digital-architecture/open-apis/resource-inventory-management-api-TMF639/v5.0) defines a general inventory API. | The developer page returned no readable body in this pass. A standard inventory API alone does not define a deployed IP-prefix characteristic, native site relation, version or permission profile. Obtain the actual connectX product/version schema and address model. Do not label all Amdocs products as one API. |
| [Innovative Systems eLation](https://updates.innovsys.com/innovsys/elation/) | Vendor describes billing, facilities/provisioning, GIS and integrations, with a separate support portal. | No vendor-owned pool/site read schema, API version, auth scopes or paging contract was established. A search result for an external service API mentioning eLation was not treated as the vendor's native contract. eLation Health documentation is unrelated. |

## IPAM leads

On 2026-11-19, the public 9.6 Fields, Resources and Basic-authentication pages
established the narrower [initial selected-network reader](bluecat-bam.md), tracked
in [#114](https://github.com/MHammett/isp-geofeed-generator/issues/114). It uses
configured geography and an externally supplied current token. It does not claim
full OpenAPI coverage, native effective locations or automatic session renewal.

| Product and API family/version | Verified read contract | Geography, access and next step |
| --- | --- | --- |
| [Infoblox NIOS WAPI 2.13.6](https://docs.infoblox.com/download/attachments/15433773/Infoblox%20NIOS%20WAPI%209.x%20Reference%20Guide.pdf) | Public manual defines `network` and `ipv6network`, `_ref`, CIDR `network`, `network_view`, extensible attributes and token-based result paging. HTTPS Basic and certificate auth are documented; users need API rights. | Candidate for initial network reads with explicit geolocation attributes. A network view is an address namespace, not a facility. Instance read rights and populated attributes still need operator tests. Keep this NIOS contract separate from Infoblox cloud APIs. |
| BlueCat Address Manager RESTful v2, guide version 9.6.0 | [Field-selection examples](https://docs.bluecatnetworks.com/r/Address-Manager-RESTful-v2-API-Guide/Fields/9.6.0) show `/api/v2/networks` with stable IDs, IPv4/IPv6 types, CIDR range and configuration. [Paging](https://docs.bluecatnetworks.com/r/Address-Manager-RESTful-v2-API-Guide/Pagination/9.6.0) documents `data`, page `count`, links, limit and offset. | Need the chosen release's full OpenAPI schema and explicit network-to-location or custom-field profile. Page `count` is not a total inventory count. A configuration is not a physical location. Confirm API/read access rights for that release; do not mix Legacy v1 methods into v2. |
| EfficientIP SOLIDserver REST service API | Vendor [overview](https://efficientip.com/blog/getting-started-with-solidserver-rest-apis/) and public [SDK method list](https://gitlab.com/efficientip/solidserverrest/-/blob/master/docs/METHODS.md) document `ip_subnet_list`, `ip_subnet6_list`, `ip_pool_list` and `ip_site_list`. The [IPv4 subnet reference](https://gitlab.com/efficientip/solidserverrest/-/blob/master/docs/ip_subnet_list.md) lists exact boundaries, IDs, offset/limit and class metadata. | `ip_site_list` means address **spaces**, not proven physical sites. Verify class-parameter geography and boundary encoding on the selected release, plus IPv6 responses and count/paging behavior. The live SDK branch is not a pinned product schema. [Training](https://efficientip.com/support-services/training/) distinguishes REST and V2.0 courses; do not assume their routes or auth match. |
| [Incognito Address Commander](https://www.incognito.com/products/address-commander/) | Vendor documents public-IP management, native IPv4/IPv6 planning and allocation/reporting features. | This product page does not establish an API family/version, authenticated prefix/range reads, site fields or pagination. Request the exact supported export/read specification. Product capability is positively documented; this project's implementable API contract is still missing. |

The Infoblox manual's relevant sections are transport/authentication, GET paging,
`network`, `ipv6network` and extensible attributes. The SDK must treat `_ref` as opaque,
not derive geography from its text. A configured geography attribute is a declared
instance data model, not a built-in physical-site join. Missing values must stop selected
records instead of shrinking the feed silently.
Implementation is tracked in [issue #57](https://github.com/MHammett/isp-geofeed-generator/issues/57).

BlueCat also publishes a [Micetro API paper](https://bluecatnetworks.com/wp-content/uploads/2026/03/BlueCat-white-paper-Introduction-to-the-Micetro-REST-API.pdf).
Micetro is a separate product/API family. It is a further lead, not evidence that an
Address Manager adapter will work against Micetro.

## Setup gaps versus platform and adapter limits

Use these separate labels in issues and operator reports:

- **Platform capability:** a documented product feature or API operation. State its
  product, version and source. Do not generalize across a vendor's product families.
- **Instance setup:** the feature exists, but assignments, geography, API access or
  read permissions are missing on an instance. Explain the records that need attention.
- **API evidence gap:** public or accessible docs do not establish the required read
  contract. Ask creators for exact shapes; do not describe the product as incapable.
- **Adapter gap:** the contract exists, but this project has not implemented or tested it.
- **Live verification gap:** fixtures pass, but an operator has not tested a real instance.

For creators, useful public docs include canonical IPv4/IPv6 boundaries, stable IDs,
native site links or typed geography attributes, read-only permissions, complete paging
and sanitized examples. Publish enough detail to distinguish a pool from a subscriber
address, a DHCP range from its container and a physical facility from an address space.
Contributions with those docs and sanitized fixtures are welcome.

Each new source must use the existing versioned adapter contract and secure credential
stores. It must keep explicit selection, ownership, no-bogon, strict overlap and output
change guards. Test denial, incomplete reads, duplicates, invalid boundaries, missing
geography, IPv6 and loss of one required input before an initial-support opt-in. No
conference listing, standards badge or vendor integration claim substitutes for that work.
