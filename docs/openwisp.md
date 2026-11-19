# OpenWISP IPAM: initial selected-subnet input

This adapter reads explicitly selected IPv4 and IPv6 subnet UUIDs in one
organization. It stays labeled **initial support** until operators test it.
No live OpenWISP instance has been queried. Contributions and sanitized response
fixtures are welcome. Remove tokens, names, descriptions and customer details
before sharing a fixture. Do not include credentials in an issue.

## Public contract

Checked on 2026-11-19:

- [IPAM REST endpoints](https://openwisp.io/docs/25.10/ipam/user/rest-api.html)
  document `GET /api/v1/ipam/subnet/<subnet-id>/`.
- [User token authentication](https://openwisp.io/docs/25.10/users/user/rest-api.html#authenticating-with-the-user-token)
  uses `Authorization: Bearer <token>`.
- The pinned [IPAM 1.3.1 source](https://github.com/openwisp/openwisp-ipam/tree/2cdcfa1bab9d6e312a957be552f29f2fc9ba5929/openwisp_ipam)
  exposes the subnet model through `api/serializers.py` and the detail view in
  `api/views.py`. `base/models.py` defines CIDR boundaries and a parent subnet.
  `tests/test_api.py::test_read_subnet_api` checks a canonical IPv6 response.

The reader needs a JSON object with `id`, `organization` and `subnet` strings.
The first two must match the selected subnet UUID and configured organization UUID.
The CIDR must be canonical with no host bits, zone identifiers, expansion or normalization needed.
Unknown fields are discarded. Names, descriptions, parent records and response
links are neither used for location nor followed.

This profile verifies one module release and the documented API route. It does not
claim every bundled OpenWISP release or custom model uses the same contract.
Other releases need sanitized response fixtures and operator testing.

## Configure the location model

The inspected subnet model does not establish a native facility relationship for
this reader. That does not prove that OpenWISP extensions cannot provide one.
An organization identifies a tenant, not a facility. A parent subnet identifies
address hierarchy, not a shared geolocation.

Select only subnets whose **entire range** belongs at the intended coarse location.
Supply `site_locations` for each synthetic `subnet:<uuid>` slot. These are private
generator settings, not facility records created or read in OpenWISP. The report
labels these mappings as `configuration`, not `native_scope`. Reuse the
same reviewed geography when several subnets belong at one facility. Do not map a
large aggregate to one town when its children serve several towns. Explicitly
select the appropriate smaller subnets instead.

The platform can hold shared subnets with a null organization. This initial reader
refuses them because it requires an exact organization match. That is a deliberate
adapter limit, not a platform limit or a reason to change shared tenant design.
Use another named input for another organization; give each input explicit access
and location settings. No list scan, child enumeration or complete-instance
inventory is claimed. New subnets must be added to the selection after review.

## Credentials and setup

Use a dedicated account with the least access needed to read the selected subnets.
Check its organization access and detail reads before scheduling. Keep the token
in an OS credential store, protected file or systemd credential. The adapter does
not accept passwords, obtain tokens, renew sessions or reset credentials.
See [credential storage](security.md). Never commit a token or production config.

The input URL is the HTTPS installation root, including a proxy mount path if
needed. Do not append `/api/v1/ipam`. Redirects are refused. Set the final canonical
HTTPS root rather than relying on a login or HTTP redirect. Requests use the
shared bounded transport with a timeout and no automatic retries. A denied or
throttled request stops the whole run. Budget the schedule against the instance's
rate limits; the adapter permits 1 to 256 selected subnet UUIDs per input and makes
one GET per selected ID on each discovery, generation or publication run.

Example with placeholders, not an allocation or ownership claim:

```yaml
inputs:
  openwisp:
    url: https://ipam.example.net
    source:
      type: openwisp
      organization_id: ab000000-0000-4000-8000-000000000001
      subnet_ids:
        - ab000000-0000-4000-8000-000000000004
        - ab000000-0000-4000-8000-000000000006
      allow_initial: false
    credentials:
      OPENWISP_API_TOKEN: file:/etc/isp-geofeed/openwisp-token
    site_locations:
      subnet:ab000000-0000-4000-8000-000000000004:
        country: US
        region: US-IL
        city: Reviewed City
      subnet:ab000000-0000-4000-8000-000000000006:
        country: US
        region: US-IL
        city: Reviewed City
allowed_prefixes:
  - YOUR_AUTHORIZED_IPV4_CIDR
  - YOUR_AUTHORIZED_IPV6_CIDR
state_dir: /var/lib/isp-geofeed
publish:
  type: file
  path: /srv/geofeed/geofeed.csv
```

Replace all placeholders and add the normal current fullbogon policy configuration.
Use `discover`, then `generate` and `validate` with the same config. Review exact
coverage and coarse location. After those checks, set `allow_initial: true` to
publish. The ordinary ownership, bogon, overlap, withdrawal, relocation and output
guards still apply. A successful selected read is not proof of address ownership.
Additional output fields, such as coordinates, use the existing typed location
settings and the output's explicit field profile; this reader invents none.

For a single legacy `source` config, the URL is `OPENWISP_URL` and the credential
name is `OPENWISP_API_TOKEN`. Named inputs use their own `url` and explicit
credential references, so multiple instances need no upstream checkout edits.

## Refusal and recovery

A missing record, ID mismatch, wrong or null organization, malformed subnet,
authentication failure or timeout refuses the whole input. A required input's
failure prevents a partial combined feed. Missing location data also stops output.
The CLI records the failure without treating it as healthy. Existing feed bytes
and recovery backups are retained.

Inspect the reported ID, selected settings and instance access read-only. Correct
the source data or private mapping, then generate and validate again. Do not remove
a required input or selected subnet merely to get a green run. For an intentional
withdrawal, use the normal change review and approval process. If you need to undo
a real publication, use the documented [publication recovery](publication-verification.md)
workflow and its ownership checks.

Platform creators: please expose stable pool/subnet IDs, exact IPv4/IPv6 boundaries,
tenant scope and explicit hosting or service-location relationships in read APIs.
Document shared controllers and parent inheritance. This avoids guessing location
from labels or tenant identity. We welcome contributions for those native joins.
