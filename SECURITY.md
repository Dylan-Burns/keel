# Security

## Reporting

Report a vulnerability through GitHub's private vulnerability reporting on
this repository (Security tab, "Report a vulnerability"). Do not open a
public issue. Expect an acknowledgement within 2 business days.

## Scope

Keel processes public SEC filings and sends question text plus filing
excerpts to the model provider over HTTPS. The threat model and the
controls S-01 to S-20, each with where it lives in the code and how it is
tested, are in [docs/SECURITY.md](docs/SECURITY.md).

The public site at <https://keeldd.com> runs in a bring-your-own-key mode.
A visitor may send their own Anthropic API key in the `X-Anthropic-Api-Key`
header; the service uses it for that request only, never stores or logs
it, and Caddy strips the header from its access log. Visitors without a
key get cached answers only, and no visitor can reach the status, debug,
or admin routes. Reports about the handling of visitor keys are
especially welcome.

## Supported versions

| Version | Supported |
| --- | --- |
| Latest release on `main` | Yes |
| Older tags | No |

## Dependencies

Dependencies are pinned in `uv.lock` and `web/package-lock.json`, scanned
by `pip-audit` on every PR and by Dependabot weekly. Container images are
scanned by Trivy at release.
