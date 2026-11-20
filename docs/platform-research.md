# Platform research and conference leads

Reviewed on 2026-11-15. Read the [capability matrix](platforms.md) for implemented support
and [prior art](prior-art.md) for existing projects. Research findings do not by themselves claim adapter support.
Powercode and gaiia now have initial adapters; their setup and limits are in [the operator guide](operator-setup.md).

## Named platform checks

| Platform | Positive evidence | Remaining contract or access work | Operator setup |
| --- | --- | --- | --- |
| Vision by Fibersmith | Public OpenAPI schema; hardware has `LocationUUID`. Vendor documents modeled IP pools. | No dedicated pool/range read operation found in the reviewed generic schema. Check reports/components or a vendor-provided version. | Request company API access; confirm the exact schema and read permissions. Maintain hardware/location records. |
| Powercode | Legacy API 1.5.1 documents `readAddressRanges`, returning IDs and exact address ranges. Product has Network Locations. | That range response does not document a Network Location ID. Verify a native join or use a reviewed explicit range-to-site map. Check current REST separately. | Set Network Location on ranges where appropriate. Keep a dedicated API key with only required reads. |
| Nucleo at getnucleo.com | Internal site import model includes Primary Subnet, Secondary Subnet, city and state. | Public docs reviewed do not establish authenticated read paths, paging or export responses. Import columns are not API endpoints. | Model infrastructure as internal sites and maintain site subnet links. Verify API access with the vendor. |
| VISP | Vendor documents GraphQL access. LibreQoS provides an equipment/site/upstream integration example. | Verify vendor-supported IPAM pool/range queries, version, tenant handling and geography fields. | Populate IRM site and upstream relationships. Subscriber CPE addresses do not locate an entire pool. |
| UISP Network and CRM | Vendor confirms separate APIs. Network has infrastructure sites; subscriber endpoints are a different site type. | Obtain the target console's Network API schema. Verify IP range/subnet to device/site joins and read-only token permissions. | Maintain device-to-site assignments. Monitored discovery subnets and CRM service IPs are not automatically hosting pools. |

Powercode legacy reads use POST to `/api/1/index.php` with an action, including
`readAddressRanges`. HTTP POST alone does not make a documented read operation a mutation.
The reviewed range result contains `addressRangeID`, `name`, `range` and `freeIPs`.
`readNetworkEquipment(networkLocationID)` is also documented, but its response includes
SNMP information. Do not collect equipment secrets to solve a range-to-site join.
The REST collection and legacy API must be evaluated separately; absence in one is not
proof of absence in the other.

Vision's generic Swagger UI and linked schema were publicly readable during this review.
Live data access still requires company credentials. No vendor login was attempted.

## Conference discovery

Reviewed the full public company lists linked by these conferences, then selected relevant
billing, OSS and IPAM candidates. An exhibitor name identifies a research lead. It proves
neither a suitable API nor market share.

| Conference source | Relevant candidates seen | Follow-up |
| --- | --- | --- |
| [WISPAPALOOZA 2026 exhibitor list](https://mobile.map-dynamics.com/exhibitors-g2app.php?Show_ID=18319&embed=true), linked by [the organizer](https://www.wispaevents.org/wpalooza26/exhlist) | BillMax, CHR Solutions, Fibersmith, gaiia, Nucleo, Sonar, VISP | Check billing/IPAM reads and exact product versions. |
| [Fiber Connect 2026 company list](https://fiberconnect2026.eventscribe.net/SearchByExpoCompany.asp?pfp=BrowseByCompany) | Amdocs, CDG, CHR Solutions, Fibersmith, gaiia, GLDS, Incognito, Innovative Systems | Add product-specific research. Billing, network inventory and IPAM may be separate modules. |
| [EDUCAUSE 2026 exhibitor profile](https://s23.a2zinc.net/clients/EDUCAUSE/E26/Public/eBooth.aspx?BoothID=105410&FromPage=Exhibitors.aspx&IndexInList=95&ListByBooth=true&Nav=False&ParentBoothID=) | EfficientIP | Check SOLIDserver subnet/site metadata and public API examples. |
| [NANOG annual report for 2023](https://storage.googleapis.com/site-media-prod/documents/NANOG-Annual_report-2023.pdf) | BlueCat and Infoblox | Historical discovery evidence only. Check current product-specific APIs. |

On 2026-11-16, BillMax's linked Core v1 Swagger schema established selected AP
`networkMask` reads and native `_pop` expansion. These support an [initial narrow adapter](billmax.md).
Its general pool, other mask and IPv6 contracts remain separate work.
gaiia's published schema verified `networkSites`, `networkSite(id)` and the site's paginated
`ipBlocks` connection. That contract now supports an initial adapter. GLDS/BroadHub, CDG, CHR, Amdocs and
Innovative Systems are discovery leads, with no IPAM read contract claimed by this review.
Incognito's Address Commander is an IPAM product with documented integration options;
an implementable public read schema still needs review.

For dedicated IPAM, also track Infoblox NIOS WAPI, BlueCat Address Manager REST v2 and
EfficientIP SOLIDserver as separate adapters. Their API families exist; their geofeed
mapping rules and live instances have not been verified here. Keep cloud products and
on-premises API versions separate rather than treating one vendor name as one contract.

## Sources

- [Vision API access guide](https://support.fibersmith.systems/resources/blog-posts/public-api-guide), [generic schema](https://customer-api.fibersmith.systems/doc/customerapi.json), and [service activation model](https://support.fibersmith.systems/resources/blog-posts/Fiber-Service-Activation).
- [Powercode API index](https://api.powercode.com/), [legacy operation definitions](https://api.powercode.com/v1-7/api_data.js), [REST reference](https://restapi.powercode.com/), and [range location setup](https://kb.powercode.com/?ht_kb=ip-address-range-import).
- [Nucleo docs](https://getnucleo.com/docs) and [site model](https://getnucleo.com/docs/data-migration/sites). This is the ISP platform, not similarly named commerce or AI products.
- [VISP API guide](https://visp.net/help_documentation/visp-api/) and [official examples](https://github.com/VISPdevteam/Visp-UBO-API-Sample-Code).
- [UISP API usage](https://help.uisp.com/hc/en-us/articles/22590956856087-UISP-CRM-API-Usage) and [site model](https://help.uisp.com/hc/en-us/articles/22590965763991-UISP-Site-Device-Management). The vendor points to each console's Network API documentation; verify the path for that deployment.
- [BillMax API](https://billmax.com/api-reference/) and [gaiia Network Sites and API starting points](https://support.gaiia.com/hc/en-us/articles/49758568394267-Network-Sites).
- [Incognito IPAM](https://www.incognito.com/products/address-commander/), [BlueCat REST v2 guide](https://docs.bluecatnetworks.com/r/Address-Manager-RESTful-v2-API-Guide/v1-REST-API-to-RESTful-v2-API-migration-guide/25.1.0), [Infoblox WAPI guide](https://docs.infoblox.com/download/attachments/15433773/Infoblox%20NIOS%20WAPI%209.x%20Reference%20Guide.pdf), and [EfficientIP API course](https://efficientip.com/wp-content/uploads/2026/01/SOLIDserver-REST-API-Course.pdf).

For each new adapter, verify exact prefix boundaries, stable IDs, complete pagination,
permissions, native site links and missing/conflicting data. Report setup gaps separately
from API gaps. Never invent a pool location from a matching name or one observed subscriber.

The [2026-11-16 API triage](platform-api-triage.md) follows the nine conference leads
through product-specific public docs and records exact contract, setup and verification
gaps. It identifies NIOS WAPI as a concrete initial-adapter candidate and keeps distinct
BlueCat and EfficientIP API families separate.
