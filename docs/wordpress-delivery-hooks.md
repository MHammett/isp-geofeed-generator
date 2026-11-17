# Optional cache purge after a feed commit

The WordPress plugin exposes `isp_geofeed_generator_feed_committed`. A separately
installed local plugin can use it to call a supported host or cache purge API.
Nothing is enabled or installed automatically. Keep local integration code outside
the upstream plugin directory so a GitHub update does not replace it.

The hook runs synchronously after a changed feed commits, before the write reply.
It runs for version-1 and version-2 writes, changed deletions and conditional recovery.
Unchanged writes, failed validation, stale hashes, lost CAS races, database failures,
policy-only switches and read-only inspection do not call it.

Public read-back remains required. A callback that returns normally but clears
nothing cannot make stale public bytes pass. This does not add a wait loop, a query
probe during publication or a weaker rollback rule.

## Hook contract

The action receives one array:

| Field | Meaning |
| --- | --- |
| `schema_version` | Event contract version, currently integer `1` |
| `api_version` | The write route, integer `1` or `2` |
| `url` | WordPress's canonical REST URL for the public v1 feed |
| `sha256`, `previous_sha256` | Exact new and prior CSV hashes, including empty bytes |
| `overlap_policy` | Policy stored with the new feed |
| `operation` | `publish` or v2 `restore`; v1 recovery uses its normal write route |
| `method` | `PUT` or `DELETE` |

No CSV, password or caller-supplied callback URL is passed. This describes a completed
commit, not proof that it is still the latest state after another writer acts. A purge
callback must invalidate the URL, not publish bytes from its own copy of the feed.

Use the standard [WordPress action API](https://developer.wordpress.org/reference/functions/do_action/)
from trusted local code. Callback return values are ignored by that API. Throw an
exception when a required purge cannot be requested. Check provider errors explicitly.
Keep any remote call bounded, disable redirects and automatic retries, and load its
credential from the host's protected store. Never put a secret in the public repository,
event, URL, exception text or response.

The plugin catches callback exceptions and returns HTTP 503 with a safe message and
`feed_committed: true`. The database write is already committed. It does not retry the
callback or undo the row itself. The runner inspects actual state and uses its existing
conditional recovery. A recovery commit invokes the hook for its own bytes. Each is a
separate commit, not a blind retry of the failed publication.

A process exit, timeout or plugin fatal error may lose the reply after commit. Keep
the runner's saved baseline and publication ID. Inspect before a manual retry. An
unchanged run does not retry a failed purge; fix the cause and use the host's supported
purge operation before another publication trial.

## Optional WP Rocket example

[The example local plugin](../examples/wordpress-delivery-hook/wp-rocket.php) uses
`rocket_clean_files()` for the fixed feed URL. The vendor documents a full-URL purge
that includes paths below that URL; see [the provider contract](https://docs.wp-rocket.me/article/91-rocketcleanfiles).
It is not a whole-site purge. Whether REST responses are cached there, and whether a
separate host or CDN cache is cleared, must be checked on that installation.

WP Rocket [does not cache REST responses by default](https://docs.wp-rocket.me/article/1523-enable-caching-for-wp-rest-api).
This example matters only when REST caching has been enabled. It clears that plugin's
cache, not a separate host or CDN edge cache. Use the actual cache layer's supported
purge operation when that is where a stale response is held.

The example refuses an unexpected event URL, a query-based REST URL, HTTP, fragments
and embedded credentials. Query-based REST URLs can have the root path, which would
widen this provider's recursive purge. Use a canonical HTTPS feed path. It also throws
if its required helper is missing. It is contract-tested with a stub, not live-tested against WP Rocket.
The generic hook is tested on real disposable WordPress with a synthetic cache.
Other providers can use the same action with their verified narrow purge operation.

## Staging and recovery

1. Stop old writers and take the site's normal backup. Install the paired plugin/runner
   and a reviewed local integration on staging. Keep its source and install pin separate.
2. Confirm the integration targets only the feed URL and uses the right cache layer.
   Configure the host's canonical HTTPS URL correctly before relying on the event URL.
   Compare the event's `url` with the `url` in the runner's result. They must match
   exactly, including scheme, host (`www` or no `www`), port and path. `rest_url()` and
   the runner's `WP_SITE_URL` can otherwise name different cache keys.
3. Run a changed feed, an unchanged run, a deletion and recovery. Check actual normal
   public bytes and headers; a fresh query response alone is insufficient.
4. Force a purge failure. Publication must remain unhealthy. Check stored/public state
   and the private baseline before using [conditional recovery](wordpress-nested-output.md#conditional-recovery).
5. To undo the integration, stop the schedule, remove only the local hook plugin, and
   fix or exclude the public route from the relevant cache. Recheck before resuming.
   Removing the integration does not restore feed bytes or fix stale caches by itself.

[Issue #66](https://github.com/MHammett/isp-geofeed-generator/issues/66) stays open for
managed-host measurements and review of recovery policy. This adds an opt-in integration
point, not a claim that any production host or GeoIP consumer has refreshed.
