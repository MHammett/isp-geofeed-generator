# Install with systemd

This runbook is optional. Operators can run the CLI with their own scheduler.
No operator's hostname, tenant, facility IDs or credentials are part of the runtime code.

The supplied deployment expects Debian with Python 3.11+, `python3-venv` and systemd.
It uses the built-in lock and status writer. No private shared library or alert unit is required.

Use a GitHub source hub on `main` and a separate worktree for each change.
The deploy script installs the source version it is run from. It never fetches or merges git changes.
Do not deploy a feature branch by accident.

In bash on the Linux host, as the development user:

```bash
PYTHON=/path/to/python-with-PyYAML bash tests/test.sh
bash deploy-update.sh --dry-run
```

After the version has been approved, in bash at a root prompt:

```bash
bash /path/to/isp-geofeed-generator/deploy-update.sh
```

The installer creates the `geofeed` account, `/opt/isp-geofeed-generator`, `/etc/isp-geofeed-generator`,
and `/var/lib/isp-geofeed-generator`. It installs the units and an accounting slice.
It preserves private configuration and does not enable the timer.
The standalone accounting slice can be moved into the host's central slice inventory when adopted there.

Create `/etc/isp-geofeed-generator/config.yaml` and `/etc/isp-geofeed-generator/runtime.env` from the examples.
Both must be `root:geofeed` mode `0640`. Never copy credentials into a source worktree or a world-readable test stage.
Set `state_dir: /var/lib/isp-geofeed-generator` and `publish.type: wordpress`.

The environment file holds non-secret settings such as source URLs and `WP_USERNAME`.
Load secrets with systemd encrypted credentials as described in [security.md](security.md).
Use a dedicated WordPress publisher account and a read-only source credential.

After the WordPress plugin has passed a staging check and its backup gate, in bash at a root prompt:

```bash
bash /path/to/isp-geofeed-generator/enable-timer.sh
```

That script runs a real publication first. It enables the daily timer only if the workload succeeds.
The schedule is 03:15 UTC with up to 30 minutes of random delay.

In bash on the Linux host, inspect the result:

```bash
systemctl status isp-geofeed-generator.service isp-geofeed-generator.timer
journalctl -u isp-geofeed-generator.service -n 50 --no-pager
```

The journal and private status file distinguish failure from success. No alert is silenced automatically.
The service is a one-shot task; deployment does not restart it or trigger a publication.
For a file-publishing target outside `/var/lib/isp-geofeed-generator`, an operator must add the target directory
to the unit's `ReadWritePaths` and grant the service account access.

## Stop and recovery

In bash at a root prompt:

```bash
systemctl disable --now isp-geofeed-generator.timer
```

This stops future scheduled runs and leaves the current public feed in place.
Inspect the failure and follow the WordPress recovery runbook before restarting.
For a code rollback, deploy a known-good source revision after previewing its dry run.
The installer does not prune removed runtime files; remove only named stale files from an approved release.

## Verification limits

Unit tests and deployment dry runs do not prove WordPress authentication, public reachability, cache behavior,
or failure-alert delivery. Test those with the actual service account and public domain before enabling the timer.
Complete your hosting provider's required backup before installing or changing a plugin.
If local policy requires a new host backup for every feed update too, keep the timer disabled until
the operator's backup workflow runs before each publication. This generic tool does not call a hosting provider's backup API.

## Optional local integrations

Configure and test failure notification before enabling the timer. The default unit records failures in the
journal and private status file. It does not assume an email, webhook or monitoring system.
Use a local systemd drop-in with your chosen `OnFailure=` unit.
If your host uses compatible `scripting-common` modules, add
`Environment=SCRIPTING_COMMON_PATH=/opt/scripting-common` in that drop-in and grant the service account
only the groups those modules need. Check their lock and status behavior before enabling the timer.
