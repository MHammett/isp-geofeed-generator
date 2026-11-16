# WordPress setup and recovery

Use WordPress 6.x or newer with PHP 8.0+, HTTPS, REST access and application passwords.
The plugin does not need a page-builder change or a theme change.
The [disposable integration workload](wordpress-integration.md) checks real WordPress,
database races, authentication and recovery on CI. Keep the staging checks below for
your own hosting path.

## Before installation

1. Take a full site backup. Wait until the host confirms completion.
2. Test the plugin on staging first.
3. Create a ZIP containing the `isp-geofeed-generator` folder under `wordpress/`.
4. Install and activate that ZIP in WordPress under Plugins.
5. Create a dedicated user with the **Geofeed Publisher** role.
6. Create an application password for that user. Store it in the runner's protected environment.

The role can read and publish this feed. It cannot edit pages, install plugins or manage users.
Administrators can also publish, but a dedicated user limits unattended access.
WordPress and the web server must pass the Authorization header to REST requests.

## HTTPS behind a proxy

WordPress itself must recognize the incoming request as HTTPS. The public URL showing a
padlock does not prove this when TLS ends at a reverse proxy or load balancer. WordPress's
HTTPS state controls both the plugin's write permission and application-password availability.

Have the web-server/proxy configuration pass the correct HTTPS state. If a `wp-config.php`
mapping is needed, apply it only to requests from an explicit trusted proxy address. That
proxy must replace the forwarded-protocol header, and the backend must refuse direct public
access that could spoof it. A generic rule that trusts any client's `X-Forwarded-Proto` is
not sufficient. The plugin does not trust that header or weaken its HTTPS requirement.
Use your host's supported configuration and keep the prior config for rollback.

Before the first write, use the actual public HTTPS domain to read the authenticated
`/wp-json/isp-geofeed-generator/v1/state` route with the dedicated publisher's application
password. The generator performs this read first. A 401/403 stops before any write and names
credentials, role permissions, Authorization forwarding and HTTPS recognition as possible
causes. It cannot identify a proxy problem from that status alone. Check server-side HTTPS
state on an actual web request, not a command-line PHP process.

Test the trusted-proxy path and a direct/untrusted request. Correct proxy requests should
authenticate; a forged forwarding header must not make an insecure direct request publish.
Do not enable a timer until that check and staging publication/read-back/recovery succeed.
See [WordPress's HTTPS guide](https://developer.wordpress.org/advanced-administration/security/https/).
Multisite and unusual authentication plugins have not been tested.

## Check the first publication

Generate a candidate and check the pool-to-site list in your private configuration.
Publish it once. Open the public URL in a logged-out session.
It should return five CSV fields per row and a `text/csv` content type.
There is no column header. Country, region and city follow the IP prefix; the fifth field is empty.

The plugin asks caches not to store the public response. Exclude `/wp-json/isp-geofeed-generator/v1/*`
from any cache that overrides those headers. A CDN returning stale data will fail public read-back.
Test through your actual public domain, not just an origin or staging hostname.

## Line endings and refresh policy

New CSV uses CRLF line endings, as described in
[RFC 8805 section 2.1](https://www.rfc-editor.org/rfc/rfc8805.html#section-2.1).
Upgrade this plugin before upgrading the runner. The updated plugin and runner accept
uniform CRLF or legacy uniform LF, while rejecting mixed endings, bare carriage returns
and embedded control characters. This is a strict publisher validator, not a general
importer for every optional RFC feature.

The first generated CRLF feed differs in bytes and SHA-256 from its LF version. It causes
one guarded publication even when locations are unchanged. The exact old LF bytes remain
available for recovery. Later identical runs skip writes. Keep generated candidates as
binary files so an editor does not change line endings after hash review.
The CLI writes exact UTF-8 bytes to stdout. For saved candidates, prefer `generate --output`
to avoid any shell or downstream text filter changing those bytes.

The plugin retains `no-store, no-cache, must-revalidate, max-age=0`. Its priority is fresh
read-back after a write and after recovery. It does not advertise a positive refresh
interval. [RFC 8805 section 3.4](https://www.rfc-editor.org/rfc/rfc8805.html#section-3.4)
allows publishers to provide expiry hints; it does not require them. Consumers choose
their polling schedule. A zero cache age does not require continuous polling.

## Limits for large feeds

The CSV limit is **1,000,000 bytes**, including UTF-8 characters and line endings. HTTP
requests, database statements and state responses can be much larger than that CSV.
Check every layer on the actual public path before scheduling a large feed.

The disposable integration test measured a 980,230-byte Unicode CSV using a
1,842,098-byte upload, 3,693,183-byte state response and 6,434,412-byte SQL statement.
See [the measured workload](wordpress-integration.md#measured-large-feed-example).
Those values describe one synthetic feed and test stack; measure your own workload.

- The runner sends JSON. Escaping non-ASCII characters can roughly triple the CSV's
  wire size. A proxy limit of 1 MB is not enough for every valid feed. For example,
  [nginx defaults to `client_max_body_size 1m`](https://nginx.org/en/docs/http/ngx_http_core_module.html#client_max_body_size)
  and returns HTTP 413 above it. A scoped 4 MiB request-body limit gives this request
  format room; check matching CDN, WAF, web-server and PHP limits too. Use a finite
  limit, preserve route authentication and follow the host's supported setup.
- The database update contains both new and prior feeds, plus the full stored document
  in the conditional comparison. JSON and SQL escaping add more overhead. Do not size
  `max_allowed_packet` from the CSV alone. For near-limit feeds, ask the database
  administrator to measure the prepared statement and check both server and client
  packet limits. A 32 MiB budget is a starting point for this format, not a measurement
  of your host. [MySQL documents packet-limit failures and connection closure](https://dev.mysql.com/doc/refman/8.4/en/packet-too-large.html).
- The authenticated state response contains current and previous feeds. The built-in
  runner accepts up to 8,000,000 response bytes to allow JSON escaping of two valid
  Unicode feeds. The public CSV reader remains capped at 1,000,000 bytes. PHP memory,
  proxy response limits and timeouts must also handle the real workload.

An HTTP 413 now names request-body limits to investigate. HTTP 503 names server/database
logs and `max_allowed_packet` as possible causes. A 503 alone does not prove a packet
problem. Private server responses and database details are not printed. The runner does
not retry failed writes automatically; it inspects stored state and public delivery,
then performs only conditional recovery when appropriate.

On staging, publish a representative large feed, update it, run it unchanged, and test
recovery while using the same proxy and database limits as production. A small liveness
check does not establish large-feed capacity. If a limit rejects publication, stop the
timer and inspect the named layer's logs. Verify the old stored and public feeds before
changing a limit or trying again. These limits are deployment settings; no installer
changes them automatically.

## Updates and failures

The runner reads authenticated state before a write. Each write includes the hash of the state it saw.
Withdrawal and location-change limits are checked against that state before any write.
The public feed must match that state before a changed publication starts. A mismatch
stops before PUT, DELETE or replacement of the local recovery backup. Investigate cache,
routing and other publishers. An unchanged candidate is checked through the public route
and a second authenticated state read; it makes no PUT or DELETE and preserves recovery files.
An intended large move needs [exact-candidate approval](location-changes.md); that approval
does not disable the conditional write or public recovery checks.
The plugin makes a conditional database update. A stale hash or concurrent write returns HTTP 409.
The first publication uses an insert that cannot overwrite an existing option, even if a
second writer creates it after the absent-state read. Database write failures return HTTP 503;
database details are not sent to the caller. Do not retry a 409 blindly: read the current state
and review which feed won. The plugin does not retry writes automatically.
The current and previous CSV are stored together in one non-autoloaded WordPress option.

A public read-back failure triggers a conditional restore of the old CSV.
After publication and any restore, both the public feed and authenticated state are checked.
If recovery fails, exit code 1 and the status file say so.
Stop the schedule before manual recovery. Keep the local `before.csv` and the plugin's authenticated state.
See [publication verification](publication-verification.md) for unchanged runs and recovery limits.

## Manual rollback

Use an authenticated HTTPS GET on `/wp-json/isp-geofeed-generator/v1/state` to read `sha256`, `csv` and `previous_csv`.
Send an authenticated PUT to `/wp-json/isp-geofeed-generator/v1/feed` with JSON containing:

```json
{"csv": "the exact previous_csv value", "expected_sha256": "the current sha256 value"}
```

Use a client that reads the application password from secure storage. Do not paste it into commands, issues or logs.
If there was no previous feed, use DELETE with the current `expected_sha256` instead.
Check the public URL after recovery. An absent feed returns HTTP 404.

For a rollback to a runner version that accepts only LF, first stop scheduling and use
the updated runner/plugin to restore the reviewed LF backup with the current hash.
Check public delivery before changing code versions. Older plugins reject generated CRLF
feeds; retain the matching plugin until that LF recovery is complete.

Deactivating the plugin removes its routes but retains its saved document.
Do not restore the full site backup just to undo a feed update unless the site's wider state was damaged.
The full backup remains the recovery path for a failed plugin installation.

## Technical appendix

Public GET returns raw UTF-8 CSV. PUT and DELETE require HTTPS and either `publish_geofeed` or `manage_options`.
WordPress handles application-password authentication; the plugin never stores that password.
CSV validation checks field count, prefixes, location text, duplicate/overlapping ranges and a 1 MB size limit.
The generator also applies the operator's allowed-prefix list and address-space checks before any write.
The server does not independently check the operator's RIR ownership or allowed-prefix configuration.
Only trusted operators should receive the publishing capability.
