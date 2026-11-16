# ISP Geofeed Generator

Generate and safely publish public IP geolocation feeds from ISP billing and IPAM platforms.
CSV output follows [RFC 8805](https://www.rfc-editor.org/rfc/rfc8805.html).
Publish to WordPress or write a file. Rich JSON supports separately selected location fields.

This is an independent community project. Contributions are welcome.
Built-in source adapters are read-only.
Combine Sonar customer space and NetBox infrastructure space with [named inputs](docs/multiple-inputs.md).
No customer records or street addresses are published. Coordinates require explicit output selection.

## Sources and verification

| Source | Status |
| --- | --- |
| Sonar v2 | IPv4 pools and explicitly selected IPv4/IPv6 subnets; controller-to-site discovery. Subnet API/site links checked live; IPv6 output fixture-tested |
| NetBox | Read-only live 4.7.3 checks; native site/location scope and range-parent resolution |
| Splynx API v2 | Initial support, based on vendor schema and synthetic fixtures; not live-tested |
| phpIPAM | Initial support, based on public docs and synthetic fixtures; not live-tested |
| Powercode legacy API | Initial support for documented range reads and explicit facility mappings; not live-tested |
| gaiia | Initial support for native site/IP-block links; public-schema and fixture checks; not live-tested |

[The platform matrix](docs/platforms.md) separates platform capability, instance setup and adapter verification.
For a failed source read, see [record-level troubleshooting](docs/source-errors.md).
A missing assignment does not mean the platform cannot do the job. An untested adapter is not called production-ready.
Initial adapters require an explicit opt-in before publishing.
VISP, Azotel and other platforms can be added when their needed API operations are verified.

## How it works

Read-only inputs -> selected exact public prefixes and site links -> validation -> one output.

- Handles each API's documented pagination and bounded responses.
- Uses native site links or reviewed configuration; never guesses from names.
- Converts exact ranges to CIDR without expanding to the parent subnet.
- Applies an operator-owned public-prefix allow list and rejects overlaps.
- Refuses bogons using current reserved and unallocated space lists; see [bogon policy](docs/bogons.md).
- Publishes country, region and city in CSV, or selected [rich location fields](docs/output-formats.md) in JSON.
- Stops on missing data or large withdrawals and keeps the last good feed.
- Guards large location changes separately for IPv4 and IPv6, with [exact-candidate approval](docs/location-changes.md) for reviewed moves.
- Uses conditional WordPress writes, public read-back and guarded rollback.

## Quick start

Requires Python 3.11+. The core runs on Linux or Windows. The optional systemd deployment is separate.

In bash on Linux:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp config.netbox.yaml.example config.yaml
```

Set the source URL and choose secure credential-store references before running a source query.
See [credential storage](docs/security.md). The examples use systemd credentials; Windows operators can use
`wincred:<target-name>` references with Windows Credential Manager. Never put secret values in YAML or command arguments.

In bash on Linux, discover and generate without publishing:

```bash
.venv/bin/python -m isp_geofeed_generator discover --config config.yaml --output output/discovery.json
.venv/bin/python -m isp_geofeed_generator generate --config config.yaml --output output/candidate.csv
```

In PowerShell on Windows, use `.\.venv\Scripts\python.exe` instead of `.venv/bin/python`.
After `pip install .`, the command is `isp-geofeed-generator`.
No Sonar account is needed when using a different source.
Keep discovery exports private; they contain network inventory.
Keep operator configuration outside the Git checkout when you plan to update from GitHub.
See [local customization](docs/customization.md) for separately installed input/output extensions.

## Set up the platform and feed

[The operator setup guide](docs/operator-setup.md) describes the required records, permissions and location decisions.

1. Choose `source.type` and its publication selection.
2. Set `allowed_prefixes` to public allocations you may publish.
3. Use native site links or `pool_sites` for reviewed overrides.
4. Use structured site values or private `site_locations` for country, region and city.
5. Explain exclusions in `exclude_pools` and choose a private writable `state_dir`.

The example allocation `192.0.2.0/24` is documentation space and cannot be published. Replace it.
Do not select a parent prefix and overlapping children together.
Record IDs are digit strings for Sonar pools and `subnet:<id>` for Sonar subnets, `prefix:<id>`/`range:<id>` for NetBox,
`ipv4:<id>`/`ipv6:<id>` for Splynx, `subnet:<id>` for phpIPAM and `range:<id>` for Powercode.
gaiia uses native GlobalID values for selection and normalized IDs for overrides; discovery reports both.

## Sonar controller discovery

Sonar links pools directly to DHCP servers and links parent subnets to inline devices.
The generator can follow a controller's management IP through its assignment and inventory holder to a network site.
Inventory may belong directly to a site or to a site's address.
Use `source.site_resolution: controllers` after those records are set up correctly.
For IPv6, explicitly choose `source.subnet_ids`. Sonar assigns IPv6 directly from subnets,
not pools. The generator follows each subnet's dedicated inline-device links through exact
management-IP assignments to site inventory. See [Sonar subnet setup](docs/operator-setup.md#sonar)
and [the IPv6 example](config.sonar-ipv6.yaml.example). Use `source.pool_ids: []` for IPv6-only runs.

In bash on Linux, inspect evidence:

```bash
.venv/bin/python -m isp_geofeed_generator discover --controller-candidates --config config.yaml --output output/controllers.json
```

Global or disabled controllers do not identify one pool's host. Missing or conflicting assignments need review.
The controller's facility can differ from the subscriber's town; override it for your chosen geolocation policy.
Separate `--assignment-candidates` discovery shows where pool addresses are used, which does not prove pool hosting.

## Publish and schedule

For WordPress, install the included plugin and create a dedicated Geofeed Publisher account.
Follow [WordPress setup and recovery](docs/wordpress.md), including backup and staging checks.
Set `WP_SITE_URL`, `WP_USERNAME` and a secure `WP_APP_PASSWORD` reference.

In bash on Linux, after reviewing the candidate:

```bash
.venv/bin/python -m isp_geofeed_generator publish --config config.yaml
```

The public route is `https://www.example.net/wp-json/isp-geofeed-generator/v1/feed`.
It serves raw UTF-8 CSV without login, a column header or a JSON wrapper.
Generated CSV uses CRLF line endings. Upgrade the WordPress plugin before the runner;
both updated validators accept existing LF feeds for guarded migration and recovery.
Publishing uses a hash to prevent concurrent overwrites. Failed read-back triggers a conditional rollback.
If recovery cannot be verified, the result says so and exits with failure.

For a file target, set `publish.type: file` and `publish.path`.
Local write/read-back does not prove public HTTPS access; check the web-server path separately.
Unchanged runs verify the existing feed without replacing it or its recovery backup.
WordPress checks both authenticated state and public delivery before deciding to skip a write.
See [publication checks and recovery](docs/publication-verification.md), including local locking limits.
[The optional systemd runbook](docs/systemd.md) uses a dedicated account and restricted state directory.
Enable a schedule only after the actual workload succeeds.

The default withdrawal limit is 10% of previous address coverage, checked separately for IPv4 and IPv6.
The default location-change limit is 10% of retained address coverage per family. A stopped
move needs investigation or approval of the exact reviewed candidate; see [location changes](docs/location-changes.md).
The private state directory holds status and recovery CSVs. Stop the schedule before manual recovery.
Exit code 1 includes failed measurements; it is never a health result.

Publishing and feed discovery are separate. Add the final HTTPS URL through your registry's supported process.
[RFC 9632](https://www.rfc-editor.org/rfc/rfc9632.html) describes discovery.
The tool does not change registry records, sign feeds with RPKI or promise when databases will apply an update.

## Tests and contributions

In bash on Linux:

```bash
python -m unittest discover -s tests -v
REQUIRE_PHP=1 bash tests/test.sh
```

The full harness needs PHP 8.0+ CLI. Offline tests do not replace a real WordPress staging trial.
See [verification evidence](docs/verification.md) and [review issues](https://github.com/MHammett/isp-geofeed-generator/issues).
New adapters need public source docs, synthetic fixtures, failure tests, setup instructions and an honest verification level.
See [adapter contracts](docs/adapters.md), [prior art](docs/prior-art.md), and [platform research](docs/platform-research.md).
Feedback should include platform version and sanitized response shapes. Never include credentials or raw customer exports.
See [CONTRIBUTING.md](CONTRIBUTING.md). We welcome adapters, tests, docs and operator feedback.
We also invite [platform creators](docs/platform-creators.md) to make IP pool-to-geolocation links easier to read through their APIs.

Source code is under `isp_geofeed_generator/`; the plugin is under `wordpress/`.
Guides are under `docs/`. Licensed under [MIT](LICENSE).
