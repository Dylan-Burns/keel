# Infrastructure

The public site runs on AWS: 1 EC2 host built from `terraform/`, Docker
Compose with Caddy for HTTPS, a CloudFront distribution under `keeldd.com`,
systemd timers for the nightly refresh and backup, and an S3 bucket for the
backups. `.github/workflows/infra.yml` checks the Terraform on every change
(fmt, validate, tflint, checkov) and runs a nightly drift plan.

## Layout

| Path | Purpose |
| --- | --- |
| `terraform/` | AWS host (D-39): EC2 instance, Elastic IP, security group, S3 backup bucket, IAM instance profile with SSM, GitHub OIDC deploy role, Route 53 zone and ACM certificate for the custom domain |
| `Caddyfile` | AWS host: TLS termination, security headers, SSE pass-through |
| `systemd/` | AWS host: `keel-refresh` and `keel-backup` service and timer units |
| `deploy_host.sh` | AWS host: the deploy that `deploy-aws.yml` runs through SSM (files of the release bundle, image, first-run corpus, models, and index from the S3 bucket, health wait, timers) |
| `backup.sh` | Consistent snapshot of the index and the logs to an S3-compatible bucket; `keel backup` is the same routine in Python |

## AWS: first deploy (D-39)

The site runs on 1 EC2 `t3.large` (8 GB) in `us-east-2`. Deploys go through
SSM Run Command, so port 22 stays limited to the admin CIDR and GitHub holds
no AWS key.

1. An AWS profile for a deploy user with the permissions of the Terraform
   resources (EC2 in the region, the `keel-pilot-*` bucket, `keel-*` roles and
   instance profiles, the GitHub OIDC provider, SSM). Keep the Terraform state
   outside the repository (`.gitignore` excludes state, plans, and tfvars).
2. `terraform init -backend-config=backend.hcl && terraform apply` with a
   `terraform.tfvars` that sets
   `region`, `admin_cidr`, `ssh_key_name`, and `backup_bucket_name`. The
   outputs give `public_ip`, `instance_id`, `deploy_role_arn`, `backup_bucket`,
   and `hostname` (`<ip with dashes>.sslip.io` when no DNS zone is set; Caddy
   obtains a Let's Encrypt certificate for it).
3. Write `/opt/keel/.env` on the host, mode 0600: `ANTHROPIC_API_KEY`,
   `KEEL_API_TOKEN`, `KEEL_HOSTNAME` (the `hostname` output), and
   `KEEL_BACKUP_BUCKET` (the `backup_bucket` output). The deploy script adds
   `KEEL_IMAGE`.
4. In GitHub, on the `production` environment (required reviewer): the
   variables `AWS_DEPLOY_ROLE_ARN`, `AWS_REGION`, `KEEL_INSTANCE_ID`, and
   `KEEL_HOSTNAME`. The deploy role trusts only jobs of this environment.
5. Put the corpus zip and the index archive (with its `.sha256`) in the
   bucket under `keel/bootstrap/` (`edgar_corpus.zip`,
   `index-v1/keel-<stamp>.tar.gz`). The repository is private, so the host
   fetches nothing from GitHub.
6. Release through release-please, then run `deploy-aws.yml` with the
   version. The job checks out the release, uploads a bundle of the compose
   file, the Caddyfile, the backup script, the systemd units, and
   `infra/deploy_host.sh` to `keel/deploy/<version>-<commit>.tgz`, and runs
   the bundled script on the host through SSM: the image from GHCR (public);
   on the first run the corpus, the models, and the index (through
   `keel restore`) from the bucket; then the app and Caddy, a wait for the
   version on `/api/health`, and the nightly refresh and backup timers.

To run the same deploy by hand: build the bundle from a checkout of the
tag, copy it to the bucket, and run `bash infra/deploy_host.sh <version>
<bundle dir>` on the host through `aws ssm send-command --document-name
AWS-RunShellScript`, or over SSH as `ubuntu` from the admin CIDR.

## AWS: the public address

`cloudfront.tf` puts a CloudFront distribution in front of the host: the
free `*.cloudfront.net` name with its certificate (the `cloudfront_url`
output, the GitHub variable `KEEL_PUBLIC_URL`). Caching is off and every
viewer header but `Host` reaches the origin, so the bearer token and the SSE
streams pass through unchanged. The origin is Caddy on the host over HTTPS
under its `sslip.io` name.

## AWS: the custom domain

`dns.tf` serves the distribution under `domain_name` (D-40: `keeldd.com`)
and `www.<domain_name>`. With `domain_name` set, Terraform creates a Route 53
hosted zone, an ACM certificate for both names in `us-east-1` (validated
through DNS), the CloudFront aliases with the policy `TLSv1.2_2021`, `A` and
`AAAA` alias records for both names, a `CAA` record (ACM and Let's Encrypt
only), and records that say the domain sends no mail: a null `MX`,
`v=spf1 -all`, and a DMARC policy `p=reject`. With `domain_name` empty,
nothing changes and the site keeps the `*.cloudfront.net` name. The origin
stays Caddy on the host under its `sslip.io` name, so `KEEL_HOSTNAME` and the
host `.env` do not change.

The certificate validates only once the registrar delegates to the zone, so
the first apply runs in 2 steps:

1. Add `domain_name = "keeldd.com"` to `terraform.tfvars`, then
   `terraform apply -target=aws_route53_zone.keel`. Read the 4 name servers
   with `terraform output name_servers`, or in the Route 53 console.
2. At the registrar of the domain, replace the name servers of `keeldd.com`
   with those 4 (custom DNS, not the registrar's own DNS). Turn off any
   parking or forwarding there. Check the delegation with
   `dig +short NS keeldd.com`; it can take from minutes to a few hours.
3. `terraform apply`. The run waits for ACM to issue the certificate, then
   updates the distribution in place (a few minutes).
4. In GitHub, set the repository variable `TF_DOMAIN_NAME` to `keeldd.com`
   (`infra.yml` passes it to the nightly plan, so the plan shows no drift),
   and set `KEEL_PUBLIC_URL` on the `production` environment to
   `https://keeldd.com` (the `cloudfront_url` output), so `deploy-aws.yml`
   smoke tests the new address.
5. Check `curl -fsS https://keeldd.com/api/health` and
   `curl -fsSI https://www.keeldd.com/`.

The read-only plan role already reads Route 53 and ACM through
`ReadOnlyAccess`. The zone costs 0.50 USD a month; the certificate is free.

## AWS: CI and CD

| Workflow | When | What |
| --- | --- | --- |
| `infra.yml` job `terraform` | every pull request and push that touches `infra/` | `fmt`, `validate`, `tflint`, `checkov` (soft fail, SARIF to code scanning) |
| `infra.yml` job `plan` | pushes to main that touch `infra/`, nightly at 06:17 UTC, and on demand | `terraform plan` against the live account through the read-only role `keel-pilot-plan` (GitHub OIDC, trusted for main only); the step summary lists the changed resources; a non-empty plan fails the job as drift. Pull requests get no AWS credentials (the repository is public) |
| `release.yml` | a `v*.*.*` tag from release-please | image to GHCR with SBOM, Trivy scan, provenance; then it starts `deploy-aws.yml` for the version |
| `deploy-aws.yml` | started by the release, or by hand | waits for the reviewer of the `production` environment, assumes `keel-pilot-deploy` through OIDC, uploads the release bundle to S3 and runs its `infra/deploy_host.sh` through SSM, smoke tests HTTPS |

The state sits in `s3://keel-pilot-tfstate-<account>/pilot/terraform.tfstate`
(versioned, encrypted, native lock file); run `terraform init
-backend-config=backend.hcl`. GitHub holds no AWS key: the repository
variables `AWS_PLAN_ROLE_ARN`, `AWS_REGION`, `TF_SSH_KEY_NAME`, and
`TF_BACKUP_BUCKET`, the secret `TF_ADMIN_CIDR`, and on the `production`
environment `AWS_DEPLOY_ROLE_ARN`, `KEEL_INSTANCE_ID`, and `KEEL_HOSTNAME`.
The plan role has `ReadOnlyAccess` with explicit denies: no S3 object but
the state, no parameter, secret, or log contents, no SSM command output, no
instance user data or console output. It trusts only `main`, through
GitHub's immutable OIDC subject (`repo:<owner>@<id>/<name>@<id>:...`).

## Prebuilt index

The full index build needs about 6.6 GB of memory. A smaller host can
restore a prebuilt index instead: build it elsewhere with `keel index` and
`keel backup --index-only --out dist/`, publish the archive and its
`.sha256`, and set `KEEL_INDEX__URL` to the archive. The bootstrap
downloads it over HTTPS under control S-11, checks it, and restores it
(about 6 s for the 133 MB archive of index 1.2.0) instead of building. A
failed download or check falls back to the build.

## Restore

1. Download the archive and check it:
   `aws s3 cp s3://<bucket>/keel/<stamp>/keel-<stamp>.tar.gz . && sha256sum -c keel-<stamp>.tar.gz.sha256`
2. Stop the app: `docker compose stop app`.
3. Extract into `<index dir>/restore`, move `current` to `previous`, move
   `restore` to `current`.
   `keel restore keel-<stamp>.tar.gz` does steps 1 (the checksum) and 3:
   it checks the manifest checksums, rebuilds the vector shards, points
   `previous` at the old build and `current` at the restored one, and puts
   the archived audit log under `<logs dir>/restored-<stamp>/`.
4. Start the app and check `/api/health` and `/api/ready`.

Last tested on 2026-10-22: index 1.2.0 into an empty index directory in
6.2 s.
