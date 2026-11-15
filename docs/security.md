# Credentials and service access

Use a separate account or API key for this service on each source. Grant read access only to the IPAM,
site and inventory records needed by the chosen adapter. Scope WordPress to the Geofeed Publisher role.
Do not reuse a human administrator's key for a scheduled job.

Keep a recovery copy in your organization's approved secret manager.
If a credential is missing, retrieve it there first. The program never resets or rotates a credential for you.
Do not paste credentials into chat, public issues, command arguments, URLs or configuration files.

## Linux with systemd

Known deployment blocker: the strict credential-file permission check may reject systemd's
root-owned credential files with a service-user ACL. Issue #28 tracks a real root/service
end-to-end test and fix. Do not enable a timer on the strength of unit-file tests alone.

Prefer systemd encrypted credentials. The encrypted files live under `/etc/isp-geofeed-generator/credentials/`,
owned by root in a mode-0700 directory. systemd decrypts them into a private runtime credential directory.
The application reads that directory through `CREDENTIALS_DIRECTORY`.
This protects stored files; it does not protect against a compromised root account or a compromised running process.
Keep the host's encryption key and backup policy in mind when recovering onto a different machine.

In bash at a root prompt, use the secure local prompt for each needed credential:

```bash
python3 /opt/isp-geofeed-generator/tools/store_systemd_credential.py SONAR_API_TOKEN
python3 /opt/isp-geofeed-generator/tools/store_systemd_credential.py WP_APP_PASSWORD
```

The value is sent to `systemd-creds` through standard input. No plaintext temporary file is created.
Existing encrypted files are never overwritten automatically.
The helper prints only the non-secret `LoadCredentialEncrypted=` unit setting to add.
Check that the host supports encrypted credentials before enabling a schedule.

For Sonar plus WordPress, the service drop-in contains these non-secret settings:

```ini
[Service]
LoadCredentialEncrypted=SONAR_API_TOKEN:/etc/isp-geofeed-generator/credentials/SONAR_API_TOKEN.cred
LoadCredentialEncrypted=WP_APP_PASSWORD:/etc/isp-geofeed-generator/credentials/WP_APP_PASSWORD.cred
```

For NetBox, substitute `NETBOX_API_TOKEN`. Splynx needs `SPLYNX_API_KEY` and `SPLYNX_API_SECRET`.
phpIPAM needs `PHPIPAM_API_TOKEN`. Load only the credentials needed by that service.
Powercode needs `POWERCODE_API_KEY`; gaiia needs `GAIIA_API_KEY`.
URLs and the WordPress username belong in root:geofeed mode-0640 `runtime.env`.
Never place tokens or passwords in that file for the recommended systemd setup.

## Windows

Use Windows Credential Manager's Generic Credentials store, under the account that runs the task.
Store the secret as the credential password; configure only its target name:

```yaml
credentials:
  NETBOX_API_TOKEN: wincred:isp-geofeed-netbox
  WP_APP_PASSWORD: wincred:isp-geofeed-wordpress
```

Create the entries locally in Credential Manager. Do not put a password in a shell command to create them.
The credential belongs to that Windows account. A scheduled task running as another account cannot assume access.
The Windows backend reads existing entries and never writes or rotates them.

## Other runners

Protected POSIX files and environment injection from a secret manager are supported:

```yaml
credentials:
  SONAR_API_TOKEN: file:/etc/isp-geofeed-generator/secrets/sonar-token
```

Files must be absolute paths to regular files, owned by root or the current account.
Mode 0600 is preferred; mode 0640 is accepted for a service-only group. Group-write and all access by others are rejected.
Symlinks, devices and oversized files are rejected. This backend is unavailable on Windows because the adapter
does not yet validate Windows file ACLs; use Credential Manager there.

Without a configured reference, resolution uses the systemd credential directory, then a `<NAME>_FILE` path,
then the corresponding environment variable. An available systemd credential directory is authoritative:
missing credentials fail instead of silently falling back to environment values.
Environment variables are suitable for container secret injection but are not a secret store by themselves.
They may be visible to administrators or diagnostics. Do not put their values in source-controlled shell files.

## Network and output controls

- TLS certificate verification stays enabled. Authenticated redirects are refused.
- Tokens are sent in headers, never query strings. Splynx uses a signed request header.
- NetBox permits a deliberate `source.allow_http: true` exception for a private deployment that has no TLS.
  This is an operator choice, not the default.
- The program does not log request headers, response bodies, or resolved credential values.
- Resolved secrets are redacted again from reported errors.
- Source adapters contain no billing/IPAM write operations.
- A source HTTP failure is never retried blindly or reported as healthy.
- Private configuration, state, discovery exports and credential files stay outside public git.
- The publishing service runs without root and with a restricted writable state directory.

## Before enabling a timer

Check the credential backend under the actual service account, source read permissions, complete inventory,
public-address selection, WordPress permissions, public read-back and recovery.

## Local extensions

Extensions are trusted Python code with the service account's access. Install only reviewed packages.
Installation alone does not enable them. Enable exact entry-point names in private configuration.
The loader does not import disabled packages, accept module paths from YAML, fetch plugins or replace built-ins.
An incompatible adapter API version stops startup. It is not silently ignored.

Extensions can use `EXT_<NAME>` credential names through the same credential store and enrollment helper.
For example, `EXT_CUSTOM_API_TOKEN: systemd:EXT_CUSTOM_API_TOKEN` holds a reference, not a secret.
The enrollment helper validates names without importing extensions at a root prompt.
Keep extension source, wheels and install pins outside the upstream checkout; see [customization](customization.md).
The offline suite tests failure cases; it is not proof that a given host's encryption, permissions,
network path or alert delivery has been configured correctly.
