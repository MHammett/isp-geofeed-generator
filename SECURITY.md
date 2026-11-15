# Security

Never post live tokens, application passwords, discovery exports or private configuration in a public issue.
Report a security problem privately to the repository owner through GitHub's private vulnerability reporting
when available. If it is not available, open an issue asking for a private contact without describing the flaw.

Use a read-only Sonar token and a dedicated WordPress Geofeed Publisher account.
Do not disable HTTPS certificate checks. The HTTP client refuses redirects for authenticated calls.
Rotate a credential through its owning system if it was exposed.
