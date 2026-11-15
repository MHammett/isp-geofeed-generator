# Changelog

## Unreleased

- Named required inputs combine selected inventories, including Sonar customer subnets and NetBox infrastructure prefixes, with scoped credentials, private provenance and shared output guards.

- Initial public implementation of ISP Geofeed Generator (development version 0.2.0).
- Read-only Sonar and NetBox sources with explicit selection, native site links and reviewed mapping options.
- Sonar IPv6 through explicitly selected subnets, including inline-device management-IP inventory links to network sites, IPv6-only runs and namespaced subnet mappings.
- Initial Splynx, phpIPAM, Powercode legacy and gaiia sources, with publication opt-in and clear verification limits.
- Exact-range RFC 8805 output, owned-space checks, withdrawal limits and private status records.
- Mandatory current IPv4/IPv6 fullbogon checks before CLI generation and publication.
- Output field capabilities and initial rich JSON support for explicitly selected coordinates and other location fields.
- Review fixes for phpIPAM location records, compatible NetBox authentication and whole-prefix WordPress special-space checks.
- File and WordPress targets with read-back, conditional updates and checked recovery.
- Versioned, explicitly enabled input/output extensions installed outside the upstream checkout.
- Secure credential stores and enrollment, including extension credential names, plus redacted errors.
- Portable tests, pinned CI actions, optional systemd deployment and operator recovery guides.
- Contribution guidance and a request for platform creators to expose pool-to-geolocation API links.
