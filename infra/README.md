# Infrastructure

The public site runs on Railway (D-41): 1 service built from the
`Dockerfile` with the service settings below, 1 volume at `/data`,
and the custom domain `www.keeldd.com`. The AWS path below (Terraform,
Docker Compose, Caddy, CloudFront, systemd timers, and an S3 bucket, D-39
and D-40) stays in the repository as the alternative, and
`.github/workflows/infra.yml` still checks it on every change (fmt,
validate, tflint, checkov).

## Layout

| Path | Purpose |
| --- | --- |
| `terraform/` | AWS host (D-39): EC2 instance, Elastic IP, security group, S3 backup bucket, IAM instance profile with SSM, GitHub OIDC deploy role, Route 53 zone and ACM certificate for the custom domain |
| `Caddyfile` | AWS host: TLS termination, security headers, SSE pass-through |
| `systemd/` | AWS host: `keel-refresh` and `keel-backup` service and timer units |
| `deploy_host.sh` | AWS host: the deploy that `deploy-aws.yml` runs through SSM (files of the release bundle, image, first-run corpus, models, and index from the S3 bucket, health wait, timers) |
| `backup.sh` | Consistent snapshot of the index and the logs to an S3-compatible bucket; `keel backup` is the same routine in Python |

## Railway: first deploy (D-41)

Use Railway CLI 5.x (`npx @railway/cli@5`); 4.x silently ignores
`environment edit`. Railway retires `railway.toml` on 2026-12-01, so the
repository keeps no config file: the settings below live on the service.

1. `railway init -n keel`, then `railway add --service keel`, then
   `railway volume add --mount-path /data`, then
   `railway scale us-east=1` (a new project can land in another region).
2. Set the service variables. The image runs as the non-root `keel` user,
   and every path the app writes lives on the volume:

   ```text
   KEEL_AUTH__PUBLIC=1
   KEEL_CORPUS__DIR=/data/corpus/edgar
   KEEL_CORPUS__URL=https://github.com/Dylan-Burns/keel/releases/download/corpus-v1/edgar_corpus.zip
   KEEL_INDEX__DIR=/data/index
   KEEL_INDEX__URL=https://github.com/Dylan-Burns/keel/releases/download/index-v1/keel-2026-10-22T144539Z.tar.gz
   KEEL_LOGS__DIR=/data/logs
   KEEL_EDGAR__CACHE_DIR=/data/cache/edgar
   KEEL_AUTH__USERS_FILE=/data/state/users.yaml
   KEEL_SCHEDULER__BACKUP_DIR=/data/backups
   KEEL_EVAL__REPORT_DIR=/data/logs/eval
   HF_HOME=/data/cache/hf
   RAILWAY_RUN_UID=0
   PORT=8000
   ```

   Railway probes the health check on `PORT`, so `PORT` must match
   `KEEL_SERVER__PORT` (8000 in the image).

   Railway mounts the volume as root. `RAILWAY_RUN_UID=0` lets the start
   command below run `chown` on `/data`, then `setpriv` drops
   to the `keel` user before `keel serve` starts. The server never runs
   as root.

   Public mode needs no `ANTHROPIC_API_KEY`: visitors ask with their own
   key or read the answer cache that ships in the image. The companies
   dictionary stays at the image copy, because the public site runs no
   `keel add` and no refresh.
   The answer cache also stays in the image (`demo/answer_cache`), so
   the example answers ship with each build, and answers that visitors
   paid for last only until the next deploy.
3. Set the deploy settings through the GraphQL API, with the IDs from
   `railway status`:

   ```text
   railway api 'mutation { serviceInstanceUpdate(
     serviceId: "<service id>", environmentId: "<environment id>",
     input: {
       startCommand: "sh -c \'chown -R keel:keel /data && exec setpriv --reuid=keel --regid=keel --init-groups keel serve --bootstrap\'"
       healthcheckPath: "/api/health", healthcheckTimeout: 300,
       restartPolicyType: ON_FAILURE, restartPolicyMaxRetries: 3 }) }'
   ```

4. `railway up --detach` from the repository root. The Railway builder
   rejects bind mounts and cache mounts without a service id, so the
   `Dockerfile` uses no `RUN --mount`. On the first start,
   `keel serve --bootstrap` answers `/api/health` at once, downloads the
   corpus and the `index-v1` archive in the background, checks the
   `.sha256`, and restores the index. `/api/ready` reports
   `index_loaded: false` until the restore ends.
5. Fill the model cache once. `keel serve` sets `HF_HUB_OFFLINE=1`, so the
   server never downloads the pinned models itself:

   ```text
   railway ssh -- setpriv --reuid=keel --regid=keel --init-groups \
     keel doctor --download-models
   railway restart
   ```

   Without the models, retrieval falls back to lexical search only and
   the log says `run keel doctor --download-models`. The cache lives on
   the volume, so later deploys keep it.

## Railway: the custom domain

1. `railway domain www.keeldd.com --port 8000` prints a CNAME target and a
   `_railway-verify.www` TXT token.
2. In Squarespace (Domains, `keeldd.com`, DNS settings, Custom records),
   point the `www` CNAME at that target and add the TXT record. Keep the
   email presets (SPF `-all`, DMARC `p=reject`): the domain sends no mail.
3. Squarespace has no ALIAS record at the apex, so forward `keeldd.com` to
   `https://www.keeldd.com` (Domain forwarding, a permanent 301).
4. Railway issues the certificate once it sees both records. Check
   `curl -fsS https://www.keeldd.com/api/health` and
   `curl -fsSI https://keeldd.com/`.

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

### DNS at another provider (Squarespace)

To keep the DNS at the registrar, set `dns_zone = "external"` with
`domain_name`. Terraform then creates no zone: the certificate covers
`www.<domain_name>` only, CloudFront serves `www`, and the apex forwards to
it at the provider (most providers, Squarespace included, have no ALIAS
record that could point the apex at CloudFront).

1. `terraform apply -target=aws_acm_certificate.keel`, then
   `terraform output dns_records_to_add`: the certificate validation CNAME
   and the `www` CNAME.
2. At the provider, add both CNAMEs, and forward the apex to
   `https://www.<domain_name>` (Squarespace: Domains, DNS settings, then
   Domain forwarding, a permanent 301).
3. `terraform apply`. It waits until ACM sees the validation record (up to
   2 hours), then adds `www` to the distribution.
4. Set `KEEL_PUBLIC_URL` to `https://www.<domain_name>`, and the repository
   variables `TF_DOMAIN_NAME` and `TF_DNS_ZONE=external`.

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
