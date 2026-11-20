# Bogon exclusion

Every CLI `generate` and `publish` run checks the full extent of every selected prefix
against both IPv4 and IPv6 fullbogon lists. Fullbogons include reserved and unallocated
space. A broad prefix that contains even part of a bogon is refused. The tool does not
subtract that space or expand a range. The operator allocation allow list still applies.

By default, the tool downloads Team Cymru's HTTPS fullbogon lists and caches them in
`state_dir/bogons`. It reuses a validated cache for four hours, matching the provider's
update interval. The timestamp inside each list must be at most 24 hours old and no more
than five minutes in the future. Both families are required, even for an IPv4-only feed.
Size, syntax, address family, overlapping entries and reserved-space controls are checked.
These controls detect common damaged or partial responses; they are not a cryptographic
proof that the provider's allocation data is complete.

Missing, malformed or stale data stops candidate generation and publication. A failed
refresh never falls back to stale data. There is no configuration switch to disable this
check. The old public feed remains in place if validation stops publication.

For networks without direct outbound access, maintain fresh local copies outside the
checkout and configure both absolute paths:

```yaml
bogons:
  ipv4_file: /var/lib/isp-geofeed-generator/lists/fullbogons-ipv4.txt
  ipv6_file: /var/lib/isp-geofeed-generator/lists/fullbogons-ipv6.txt
```

The same validation and age limits apply. These files are trusted allocation inputs;
restrict who can write them. Do not replace them with private-space-only lists.

Recovery: keep the schedule stopped, fix access to the provider or update the local
files, then generate a candidate before retrying publication. Do not edit the timestamps
to make old data appear current. Discovery can still inspect private inventory.

The enforcement boundary is the CLI before it calls any output adapter. Low-level SDK
serializers and the WordPress plugin do not fetch fullbogon data themselves. Applications
that call those functions directly must apply an equivalent current allocation check.
The plugin independently refuses static special-use ranges across the whole prefix.

Source: [Team Cymru's fullbogon service](https://www.team-cymru.com/bogon-reference-http).
Allocation data can change. A passing check does not prove authorization to publish a prefix.
