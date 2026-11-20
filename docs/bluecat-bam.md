# BlueCat Address Manager: initial network input

`bluecat_bam` reads selected IPv4 and IPv6 networks using the Address Manager
RESTful v2 public 9.6 example contract. Support is **initial**. No live BlueCat
instance has been tested. Contributions and sanitized operator fixtures are welcome.
This profile does not claim every newer release or the complete instance schema.
Legacy v1 and Micetro are separate APIs.

## Verified public contract

Checked on 2026-11-19:

- [Fields](https://docs.bluecatnetworks.com/r/Address-Manager-RESTful-v2-API-Guide/Fields/9.6.0)
  documents numeric IDs, `IPv4Network`/`IPv6Network`, CIDR `range` and inlined
  `configuration.id`. Its IPv6 example uses uppercase text.
- [Resources](https://docs.bluecatnetworks.com/r/Address-Manager-RESTful-v2-API-Guide/Resources/9.6.0)
  defines individual resource GETs at the collection/ID URI with the full resource
  representation. The reader uses `/api/v2/networks/<id>`.
- [Basic authentication](https://docs.bluecatnetworks.com/r/Address-Manager-RESTful-v2-API-Guide/Basic-authentication/9.6.0)
  uses base64 of `username:apiToken`. A login password or Legacy v1 `BAMAuthToken`
  is not a substitute for the v2 token.

The reader checks each ID, configuration and address family. It preserves exact
CIDR boundaries and renders IPv6 canonically, including the documented uppercase
form. Host bits, zone identifiers, malformed ranges, wrong types and missing or
mismatched records refuse the whole input. Only selected detail GETs are made.
Returned HAL links, names, notes, user-defined fields and location labels are not
followed or retained. There is no collection scan or claim of complete inventory.

## Credentials and token lifecycle

Use a separate least-privilege account that can read the selected networks. Keep
both credential references outside the checkout, using the supported
[secure stores](security.md). The URL must be the final HTTPS base ending `/api/v2`,
including any trusted proxy mount. Redirects and automatic retries are refused.

This initial profile expects an **existing current API token**, provisioned outside
the generator. Tokens can expire. The adapter does not log in, refresh, reset,
persist or revoke a token. A denial or expiration stops the run and preserves the
published feed. Do not enable unattended use unless your secure credential process
supplies a valid token for each run. Automatic session lifecycle is tracked in
[#116](https://github.com/MHammett/isp-geofeed-generator/issues/116); it is an adapter
gap, not a missing platform capability. No fixed token lifetime is assumed.

## Locations and setup

A BAM configuration is an address namespace, not a facility. This initial reader
requires reviewed private `site_locations` for each `network:<id>` slot. Reports
label the mapping as `configuration`. Select only networks whose entire range
belongs at that coarse location. Use assigned ISO country/subdivision codes.

BlueCat documents native network locations and parent inheritance in its
[26.1 administration guide](https://docs.bluecatnetworks.com/r/Address-Manager-Administration-Guide/Creating-a-new-IPv4-network/26.1.0).
The effective API read contract is not yet verified by this adapter. Keep those
native assignments; this is not a request to reconfigure your instance to suit the
reader. Native joins are tracked in
[#115](https://github.com/MHammett/isp-geofeed-generator/issues/115). Missing adapter
support must not be called platform incapability or bad instance setup.

Example with placeholders:

```yaml
inputs:
  bam:
    url: https://ipam.example.net/api/v2
    source:
      type: bluecat_bam
      configuration_id: '101'
      network_ids: ['1001', '1002']
      allow_initial: false
    credentials:
      BLUECAT_BAM_USERNAME: systemd:BLUECAT_BAM_USERNAME
      BLUECAT_BAM_API_TOKEN: systemd:BLUECAT_BAM_API_TOKEN
    site_locations:
      network:1001:
        country: US
        region: US-IL
        city: Reviewed City
      network:1002:
        country: US
        region: US-IL
        city: Reviewed City
allowed_prefixes:
  - YOUR_AUTHORIZED_IPV4_CIDR
  - YOUR_AUTHORIZED_IPV6_CIDR
state_dir: /var/lib/isp-geofeed-generator
publish:
  type: file
  path: /srv/geofeed/geofeed.csv
```

Replace every placeholder and add the normal current fullbogon configuration. On
Windows, use Windows Credential Manager references from the security guide instead
of `systemd:`. Named inputs use their own URL and credential references. Legacy
single-source configs use `BLUECAT_BAM_URL` and the same two credential names.
This initial profile accepts printable ASCII username/token values without spaces;
the username cannot contain a colon. Other account-name forms need an adapter
extension. This limit does not mean those accounts are invalid in BlueCat.

Run `discover`, `generate` and `validate` before setting `allow_initial: true` for
publication. The normal allocation, bogon, overlap, withdrawal and relocation
guards remain active. One input supports 1 to 256 selected network IDs and makes
one GET per ID per run. Respect the instance's rate limits and token expiry.
Additional location types use the existing explicit output field profiles.

## Failure and recovery

Any required record failure stops generation/publication, including a late failure
after earlier successful reads. No partial input is published. Existing feed bytes
and recovery history remain unchanged. Unchanged valid runs use the normal output
verification without rewriting the feed or backup. A failed publication status is
not reported healthy.

Inspect the error and instance permissions, token validity, selected IDs and private
location settings read-only. Correct the identified issue, then generate and
validate again. Do not drop required networks merely to get a successful run.
Intentional withdrawals use the normal change review. For an actual publication
rollback, use [guarded recovery](publication-verification.md).

Platform creators can help by publishing stable effective network-to-location read
fields, inheritance rules and scoped session lifecycle contracts. Sanitized examples
from operators and contributions for those native joins are welcome.
