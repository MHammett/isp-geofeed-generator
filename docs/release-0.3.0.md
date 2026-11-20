# Version 0.3.0 release and first deployment

Release preparation checked on 2026-11-20. This is a candidate, not a production
deployment or approval to enable a timer.

## Code scope and evidence

The candidate runtime is commit `f152f06ad3fa0faff24f692ca1be62dfcfda9bcc`.
It contains the complete dependency chain from #7 through #119. All 56 open feature
PR heads were checked as ancestors of that commit. The release PR targets `main`
so the complete reviewed implementation can be considered as one release.
The earlier PRs retain the change history and independent reviews.

Both exact-code workflows passed all nine jobs:
[push](https://github.com/MHammett/isp-geofeed-generator/actions/runs/44610567858)
and [PR](https://github.com/MHammett/isp-geofeed-generator/actions/runs/44610582042).
Each Python job ran 554 tests. Installed-package, conformance, credential, native
file/recovery and disposable real-WordPress workloads passed. Those checks do not
verify an operator's live inventory, service credentials or hosting cache.

On 2026-11-20, the packaged wheel was installed in a private, unprivileged directory
on the intended Debian/Python 3.13 runner. The existing installed-package workload,
deployment shell syntax and deployment inventory coverage passed there. Public
source and wheel hashes were checked before extraction. The production installer,
service, timer and WordPress plugin were not activated.
The runner also downloaded and validated both live fullbogon families. Allocated
test controls passed and reserved-space controls were refused. This proves that
guard's provider access and failure path on the runner, not ownership of any
operator allocation. A scoped CA bundle verified both private and public TLS roots.

## Artifacts

Keep the runner and WordPress plugin at matching 0.3.0 versions. Candidate artifacts
were built from the exact runtime above:

| Artifact | SHA-256 |
| --- | --- |
| `isp_geofeed_generator-0.3.0-py3-none-any.whl` | `8ccb687b84208e10b1b62333bfb27f631f2ef94da8f4743d480bf48c4c388eeb` |
| `isp-geofeed-generator-f152f06-source.tar` | `866a9e8e2358aca0d997cfca60608d4a48b3807acf445220b0154017cf77d056` |
| `isp-geofeed-generator-wordpress-0.3.0-f152f06.zip` | `900c217ecd9d899ee6cb000831ad0cc4de530e10afee45ff6c5616f492e9fb6e` |

The ZIP includes the plugin folder and its ISO data/notices. The source archive
contains tracked public files only. Private operator inventory, configuration and
credentials are not release artifacts. Hashes identify these files; they are not
a signature or a substitute for obtaining them through a trusted maintainer path.

The release branch may add preparation and review notes after the runtime commit.
Before merging, confirm that runtime, plugin, dependencies and deployment files
still match this tested code. Any later code change needs its own affected checks
and new artifact hashes. Do not move a published tag to different bytes.

## First-operator sequence

1. Complete the private source-selection and facility review. Do not include all
   public records automatically: IPAM can hold allocation containers, customer
   subnets, DHCP ranges and infrastructure in overlapping representations.
2. Supply the approved allocation allow list. Keep current fullbogon checks active.
   Resolve every selected record's facility and country/region/city. Keep strict
   overlap refusal unless a reviewed nested policy is required on both outputs.
3. Provision dedicated source read credentials and a WordPress Geofeed Publisher
   account. Store secrets through the supported secure stores. Keep configuration
   and inventory outside the checkout. Do not deploy a human administrator's key.
4. Verify TLS from the service host. For a private CA, use a scoped bundle containing
   the normal public roots and the required private root. Do not disable verification
   or replace public roots with only the private root. Rehearse under the real
   service account before publication.
5. Identify the WordPress staging environment and wait for its full backup to
   complete. Install the matching plugin there. Use the staging URL and its own
   publisher credential. Verify authenticated state, anonymous CSV delivery,
   unchanged output, a controlled changed feed and guarded recovery.
6. After a specific production cutover is approved, confirm the live-site backup,
   install the matched plugin and runner, and keep the timer disabled. Generate
   and validate the exact candidate. Perform one publication and verify stored and
   anonymous public bytes. Enable scheduling only after the workload succeeds.
7. Add registry references through the operator's supported process. Verify scope
   and provider ingestion separately. Publication alone does not establish either.

For the initial installation, rollback means leave the timer disabled and deactivate
the new plugin if its staging/live path fails. Preserve private diagnostics. If a
feed was committed, use [guarded recovery](publication-verification.md) before
changing the installation; do not overwrite another writer's feed.

The runner rehearsal does not establish service-account permission checks, encrypted
credential availability, a completed site backup or the host's public cache behavior.
These remain explicit first-deployment checks under #2. A missing location or link is
an instance setup issue; it does not prove the source platform cannot model it.

See [operator setup](operator-setup.md), [credential storage](security.md),
[multiple inputs](multiple-inputs.md) and [WordPress setup](wordpress.md).
Contributions and sanitized operator verification results are welcome.
