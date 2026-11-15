# WordPress setup and recovery

Use WordPress 6.x or newer with PHP 8.0+, HTTPS, REST access and application passwords.
The plugin does not need a page-builder change or a theme change.

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
Multisite and unusual authentication plugins have not been tested.

## Check the first publication

Generate a candidate and check the pool-to-site list in your private configuration.
Publish it once. Open the public URL in a logged-out session.
It should return five CSV fields per row and a `text/csv` content type.
There is no column header. Country, region and city follow the IP prefix; the fifth field is empty.

The plugin asks caches not to store the public response. Exclude `/wp-json/isp-geofeed-generator/v1/*`
from any cache that overrides those headers. A CDN returning stale data will fail public read-back.
Test through your actual public domain, not just an origin or staging hostname.

## Updates and failures

The runner reads authenticated state before a write. Each write includes the hash of the state it saw.
The plugin makes a conditional database update. A stale hash or concurrent write returns HTTP 409.
The current and previous CSV are stored together in one non-autoloaded WordPress option.

A public read-back failure triggers a conditional restore of the old CSV.
The restore is checked through the public URL too. If recovery fails, exit code 1 and the status file say so.
Stop the schedule before manual recovery. Keep the local `before.csv` and the plugin's authenticated state.

## Manual rollback

Use an authenticated HTTPS GET on `/wp-json/isp-geofeed-generator/v1/state` to read `sha256`, `csv` and `previous_csv`.
Send an authenticated PUT to `/wp-json/isp-geofeed-generator/v1/feed` with JSON containing:

```json
{"csv": "the exact previous_csv value", "expected_sha256": "the current sha256 value"}
```

Use a client that reads the application password from secure storage. Do not paste it into commands, issues or logs.
If there was no previous feed, use DELETE with the current `expected_sha256` instead.
Check the public URL after recovery. An absent feed returns HTTP 404.

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
