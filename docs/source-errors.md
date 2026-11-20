# Troubleshooting source records

Sonar, Splynx and phpIPAM now name the record type and native ID when parsing fails.
The message identifies fields to inspect without printing their values. For example:
`Sonar DHCP server 3 has an invalid or missing management IP`.

| Error names | Where to look |
| --- | --- |
| Sonar DHCP server or inline device | Open that controller by ID. Check its management IP, enabled/global flags and linked pools/subnets. |
| Sonar network site | Check that site's address and inventory connection fields. |
| Sonar IP assignment, inventory item or inventory field | Inspect that inventory record and its site/address ownership links. |
| Splynx IPv4/IPv6 network | Check network address, mask/prefix and any IPv6 range boundaries. The feed mapping key uses `ipv4:<id>` or `ipv6:<id>`. |
| phpIPAM subnet | Check subnet/mask and its native location ID. The mapping key uses `subnet:<id>`. |
| Collection and page/offset | The collection response failed before a specific record could be identified. Check API version, response shape, permissions and completeness. |

Only integer IDs or ASCII digit strings of up to 20 digits are used in these source
diagnostics. A missing, malformed or nonnumeric native ID is reported as `(unknown ID)`.
The source collection is refused; it is not silently skipped. Names, management IPs,
location values, credentials and API response bodies are not included in these messages.
Configured facility IDs in phpIPAM's configured-location mode retain their existing rules.

A malformed record can mean an instance setup problem, stale links, insufficient read
access or a different API shape. It does not establish that the platform lacks the
required feature. Compare the instance with [operator setup](operator-setup.md) and the
[platform capability and verification matrix](platforms.md).

## Recovery

If a scheduled read fails, keep the last feed and recovery files. A publication failure
records unhealthy status and exits with failure. It cannot publish a partial inventory.
Pause scheduling while correcting repeated failures in the named record or adapter setup.
Run discovery and generate a private candidate. Check the selected prefixes and locations,
then run the normal guarded publisher and verify the public result before resuming a timer.
For a code rollback, use the previous approved runner with its matching plugin/configuration;
follow the [line-ending upgrade and recovery order](wordpress.md#line-endings-and-refresh-policy).

If the ID or field is still unclear, a useful issue includes the platform/API version,
record type, safe ID, command, HTTP status and field names/types. Remove field values,
credentials and customer data. Do not attach an unredacted discovery file or API response.
Discovery files remain private inventory exports; these error-message rules do not make
those files safe to publish. See [security](security.md) for credential and log handling.
