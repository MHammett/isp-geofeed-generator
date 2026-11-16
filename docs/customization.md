# Local changes that survive updates

Keep three things separate:

- The upstream Git checkout contains the tool and its tests.
- Your private configuration contains mappings, location policy and credential references.
- Your extension package contains local input/output code in a separate repository.

Use an absolute `--config` path outside the checkout, such as `/etc/isp-geofeed-generator/config.yaml`.
Keep discovery exports, state and credentials outside it too. The installer copies runtime files;
it does not copy examples over your configuration or clear installed extension packages.
Do not edit built-in adapters for local behavior that belongs in an extension.

## Start from the example

Copy `examples/local-extension` to a separate working folder or repository, then edit that copy.
Give the distribution and entry points your own names. The example reads a reviewed normalized
JSON file and writes through the core's checked file publisher. Neither adapter contacts a platform.

Install into the same interpreter that runs the generator. In bash on Linux:

```bash
/path/to/venv/bin/python -m pip install /path/to/approved/upstream-checkout
/path/to/venv/bin/python -m pip install --no-deps /path/to/my-extension
```

In PowerShell on Windows, use the same commands with `C:\path\to\venv\Scripts\python.exe`.
Use reviewed local source or pinned wheels. Keep the extension install list and wheel hashes in
your own deployment files outside the upstream repository. The tool never downloads extensions.
If you rebuild the virtual environment, reinstall those pinned packages before starting the service.

Enable exact entry-point names in your private YAML:

```yaml
extensions:
  sources: [local_json]
  targets: [local_file]
source:
  type: local_json
  input_path: /etc/isp-geofeed-generator/inventory.json
  allow_initial: false
publish:
  type: local_file
  path: /var/lib/isp-geofeed-generator/public/geofeed.csv
  allow_initial: false
```

Add your normal allocation allow list, pool/site mappings and private state directory.
The example file must contain the normalized `pools` and `sites` model. Generate a candidate
first. Both example adapters default to initial support, so publication remains blocked until
you explicitly opt in to the tested source and target. These flags do not certify an extension.

## Extension contract

Use the supported `isp_geofeed_generator.sdk` imports. The adapter API version is `1`.
Declare installed entry points in these groups:

```toml
[project.entry-points."isp_geofeed_generator.sources.v1"]
my_source = "my_package:SOURCE"

[project.entry-points."isp_geofeed_generator.targets.v1"]
my_target = "my_package:TARGET"
```

`SOURCE` must be a `SourceAdapter`; `TARGET` must be a `TargetAdapter`.
Each declares a factory, allowed setting names, an `initial` flag and its `api_version`.
Inputs may provide a `validate(settings)` callback for their own configuration rules.
Factories receive that adapter's settings and a credential store. For custom secret names,
use `EXT_<NAME>` with secure store references. Do not read secrets from YAML values or command arguments.

The loader rejects missing or duplicate entry points, built-in name collisions and incompatible
API versions. Registries are scoped to that run. Enabling an extension in one configuration
does not silently enable it for another. No module-path or shell-command hook is accepted.

Version-2 targets have a separate `isp_geofeed_generator.targets.v2` entry-point group
and explicit `extensions.targets_v2` list. Declare `api_version=TARGET_API_VERSION`
and `overlap_policies` on their `TargetAdapter`. The CLI passes `overlap_policy` as
a required publish keyword. Version 1 remains strict-only and receives its old call.
The installed example includes `local_file_v2`, which demonstrates the new contract
while supporting strict output only. A version number alone never enables nesting.
See [nested-prefix policy](nested-prefixes.md) for the policy-bound state and recovery
contract a nested-capable target must implement. Shipped nested publication is not ready.

Local input adapters can wrap a built-in source, but must return the documented normalized
model. Use the SDK's `builtin_source(name, settings, credentials)` and
`builtin_target(name, settings, credentials)` helpers to create those wrapped adapters.
The core still validates exact ranges, owned space and locations. Local targets must
meet the [output contract](adapters.md), including read-back and recovery. They can reuse
`publish_file` or `publish_wordpress` from the SDK instead of duplicating those safeguards.
For richer provider data, declare output capabilities and use normalized records as described
in [output formats](output-formats.md). The CLI applies current fullbogon checks before calling
the selected target. Direct SDK callers must apply that policy themselves.
Keep module imports free of network calls and credential reads; do that work only when the selected factory runs.
For named input instances, use SDK `source_url(credentials, environment_name, default)` rather
than reading a process-wide endpoint. Built-in wrappers already honor the instance's URL.
See [multiple inputs](multiple-inputs.md) for credential aliases and ID scope.

## Update and recover

Stop the timer, update the upstream checkout to the approved version, run tests and install it
into the existing environment. Keep your private configuration and extension repository untouched.
Run discovery and candidate generation with the real service account before a publication trial.
If an extension fails its contract check, leave the timer stopped and keep the last good feed.
Restore the prior approved core version or install a compatible extension, then repeat the trial.

API versioning detects declared contract breaks. It cannot promise that arbitrary local code
will work forever. Re-test local extensions before upgrading. The integration test replaces
the core runtime, runs the actual publisher again and checks that external configuration,
extension files and published bytes remain intact.
