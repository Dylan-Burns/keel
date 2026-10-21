# Security

## Reporting

Report a vulnerability through GitHub's private vulnerability reporting on
this repository (Security tab, "Report a vulnerability"). Do not open a
public issue. Expect an acknowledgement within 2 business days.

## Scope

Keel processes public SEC filings and sends question text plus filing
excerpts to the model provider over HTTPS. No private data is in scope for
the demo or the pilot. The controls that ship, and the ones that do not,
are listed in `docs/15_security.md` (S-01 to S-17) and summarized in
`docs/27_pilot_ready_product_features.md`.

## Supported versions

| Version | Supported |
| --- | --- |
| Latest release on `main` | Yes |
| Older tags | No |

## Dependencies

Dependencies are pinned in `uv.lock`, scanned by `pip-audit` on every PR and
by Dependabot weekly. Container images are scanned by Trivy at release.
