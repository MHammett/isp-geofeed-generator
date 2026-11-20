# A request to platform creators

Help ISPs associate their IP pools with the right geolocation through your API.
This project welcomes your input, docs, examples and adapter contributions.

For billing, IPAM and network-management platforms, please make these records easy to read:

- A stable pool, prefix or range ID, with exact IPv4 and IPv6 boundaries.
- A stable site or facility ID linked to that pool. If the link passes through a DHCP server,
  router, inline device or inventory item, expose that path and its IDs too.
- Structured country, region and city fields on the site, with documented code formats.
- Active/archive status, complete pagination and clear read-only permissions.

Explain what the link means. A DHCP server may serve remote facilities. A customer's address,
an observed IP assignment and the facility hosting a pool are different facts. Let operators
choose their geolocation policy without guessing from object names.

Public schemas, small response examples and sandbox access make adapters easier to build and
test. Please document version changes and how an ISP should set up the native relationships.
If a platform already models them, exposing them through a read-only API can remove manual maps.

Operators are invited to test adapters and contribute sanitized feedback. The API improvement
request above is directed to the creators and maintainers of the platforms.

GeoIP data providers can also help by documenting geofeed URL registration, update APIs,
authentication, acknowledgement and withdrawal behavior. We track those output workflows in
[issue #24](https://github.com/MHammett/isp-geofeed-generator/issues/24).

Open an issue or pull request in this repository. See [the contribution guide](../CONTRIBUTING.md).
