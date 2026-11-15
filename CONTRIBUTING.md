# Contributions welcome

We welcome code, adapters, tests, docs and feedback. You do not need to use a particular
coding assistant or own every platform to help.

Operators can test initial adapters and report what happened. Include the platform version,
command, exit status and a small sanitized example. Use the adapter feedback issue form.
Do not post credentials, raw customer exports, street addresses or private inventory.

Platform creators can help make IP pool-to-geolocation links easy to read through an API.
See [the request to platform creators](docs/platform-creators.md). Public docs, sandbox examples
and clear permission guidance help more operators use these tools safely.

## Code and adapter changes

- Open an issue describing the behavior and link your pull request to it.
- Use a separate branch. Keep private deployment values outside the checkout.
- Use [local extensions](docs/customization.md) for site-specific behavior; contribute general improvements upstream.
- Cite the public API version and response contract. Keep native capability, instance setup and adapter gaps separate.
- Add expected behavior and failure checks. A failed connection or empty read is not a passing test.
- Keep new adapters labeled initial support until operator tests are recorded. Do not promote them on fixture tests alone.
- Include a short setup and recovery guide in plain language.

In bash on Linux, run the checks:

```bash
python -m unittest discover -s tests -v
REQUIRE_PHP=1 bash tests/test.sh
```

In PowerShell on Windows, use `python -m unittest discover -s tests -v`.
PHP and POSIX checks still need Linux CI or an appropriate host.

Follow the MIT license. Check licenses before copying third-party code. Report security
problems through [SECURITY.md](SECURITY.md). Never include a live secret in an issue or PR.
