# Infrastructure

Railway hosts the pilot by default (chapter 29.9): it builds the `Dockerfile`,
mounts one volume at `/data`, and gives an HTTPS subdomain. No DNS access, no
certificate, no SSH key. The AWS path (Terraform, Docker Compose, Caddy,
systemd timers) stays here as the alternative that the panel can read, and
`.github/workflows/infra.yml` checks it on every change (fmt, validate,
tflint, checkov).

## Layout

| Path | Purpose |
| --- | --- |
| `../railway.toml` | Railway build and start settings |
| `terraform/` | AWS pilot host (D-39): EC2 instance, Elastic IP, security group, S3 backup bucket, IAM instance profile with SSM, GitHub OIDC deploy role, optional Route 53 record |
| `Caddyfile` | AWS pilot host: TLS termination, security headers, SSE pass-through |
| `systemd/` | AWS pilot host: `keel-refresh` and `keel-backup` service and timer units |
| `deploy_host.sh` | AWS pilot host: the deploy that `deploy-aws.yml` runs through SSM (files of the tag, image, first-run corpus, models, and index, health wait, timers) |
| `backup.sh` | Consistent snapshot of the index and the logs to an S3-compatible bucket; the in-app scheduler calls the same routine on Railway |

## Railway: first deploy

1. Create a Railway project from the GitHub repository. In the service
   settings, turn off the automatic deploy on push; `deploy.yml` deploys
   tagged versions on purpose.
2. Add a volume with the mount path `/data`. Set the service memory to 4 GB
   or more.
3. Set the service variables: `ANTHROPIC_API_KEY`, `KEEL_API_TOKEN`,
   `KEEL_CORPUS__DIR=/data/corpus/edgar`, `KEEL_INDEX__DIR=/data/index`,
   `KEEL_LOGS__DIR=/data/logs`, `KEEL_EDGAR__CACHE_DIR=/data/cache/edgar`,
   `KEEL_CACHE__ANSWERS_DIR=/data/cache/answers`,
   `HF_HOME=/data/cache/hf`, `KEEL_SCHEDULER__ENABLED=1`,
   `KEEL_SCHEDULER__BACKUP_DIR=/data/backups`,
   `KEEL_SCHEDULER__BACKUP_BUCKET=<bucket>`, the bucket credentials
   (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_ENDPOINT_URL`), and
   `KEEL_CORPUS__URL` with the download URL of the corpus zip. The release
   asset option needs no token:
   `KEEL_CORPUS__URL=https://github.com/Dylan-Burns/keel/releases/download/corpus-v1/edgar_corpus.zip`.
4. Put the corpus zip at that URL: the release asset `corpus-v1` above, or
   a Railway bucket object with a signed URL. The host of the URL joins the
   outbound allow list (control S-11) on its own; the GitHub release asset
   hosts are on it already.
5. Generate the domain in the Railway networking settings. In GitHub, create
   the `production` environment with a required reviewer, the secret
   `RAILWAY_TOKEN` (a project token), and the variable `KEEL_HOSTNAME` with
   the generated domain.
6. Release through release-please, then run `deploy.yml` with the version.
   On the first start, `keel serve --bootstrap` starts the server, then a
   background task downloads the zip when `/data/corpus` is empty and
   builds the index when `/data/index/current` is absent. `/api/health`
   answers at once, and `/api/ready` reports `index_loaded: false` until the
   build ends. Later starts find the index and skip the build.

### The index on a 4 GB host (Option A)

The full index build needs about 6.6 GB, more than the 4 GB service. Build
it off the host and let the bootstrap restore it:

1. On a machine with the memory: `keel index`, then
   `keel backup --index-only --out dist/` (no audit log, no user data: the
   release is public).
2. `gh release create index-v1 dist/keel-*.tar.gz*` (the archive and its
   `.sha256`).
3. On the host, set
   `KEEL_INDEX__URL=https://github.com/Dylan-Burns/keel/releases/download/index-v1/<archive>`,
   where `<archive>` is the `keel-<stamp>.tar.gz` name from step 1. No
   `GH_TOKEN` and no `gh` are needed: the bootstrap downloads the archive
   and its `.sha256` over https under control S-11 and restores it (about
   6 s for the 133 MB archive of index 1.2.0) instead of building. With
   `KEEL_INDEX__RELEASE_TAG=index-v1`, `GH_TOKEN`, and `gh` on the PATH, it
   tries `gh release download` first. A failed download or check falls back
   to the build.

The volume is mounted by Railway with its own ownership rules. If the
non-root `keel` user cannot write `/data` on the first start, follow the
current Railway volume documentation for the ownership setting; do not
switch the image to root.

## Railway: nightly work

The in-app scheduler (`scheduler.enabled`) runs `refresh` at 02:00 and the
backup at 02:30 inside the app, because a Railway cron service cannot share
the app's volume. The backup writes the same checksummed archive as
`backup.sh` to `scheduler.backup_dir` on the volume and keeps the newest 7.
The upload to the S3-compatible bucket is not implemented yet
(`BackupUploadError`, see the gaps in `docs/BUILD_REPORT.md`).

## AWS: first deploy (the pilot host, D-39)

The pilot runs on 1 EC2 `t3.large` (8 GB) in `us-east-2`. Deploys go through
SSM Run Command, so port 22 stays limited to the admin CIDR and GitHub holds
no AWS key.

1. An AWS profile for a deploy user with the permissions of the Terraform
   resources (EC2 in the region, the `keel-pilot-*` bucket, `keel-*` roles and
   instance profiles, the GitHub OIDC provider, SSM). Keep the Terraform state
   outside the repository (`.gitignore` excludes state, plans, and tfvars).
2. `terraform init && terraform apply` with a `terraform.tfvars` that sets
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
5. Release through release-please, then run `deploy-aws.yml` with the
   version. It runs `infra/deploy_host.sh` of the release tag on the host:
   the compose file, the Caddyfile, the backup script, and the systemd units
   of the tag; the image from GHCR; on the first run the corpus (release
   `corpus-v1`), the models, and the index (release `index-v1` through
   `keel restore`); then the app and Caddy, a wait for the version on
   `/api/health`, and the nightly refresh and backup timers.

To run the same deploy by hand: `aws ssm send-command --document-name
AWS-RunShellScript` with `curl -fsSL <raw URL of infra/deploy_host.sh at the
tag> | bash -s <version>`, or SSH as `ubuntu` from the admin CIDR.

## Restore (both hosts)

1. Download the archive and check it:
   `aws s3 cp s3://<bucket>/keel/<stamp>/keel-<stamp>.tar.gz . && sha256sum -c keel-<stamp>.tar.gz.sha256`
2. Stop the app (Railway: scale the service to 0; AWS: `docker compose stop app`).
3. Extract into `<index dir>/restore`, move `current` to `previous`, move
   `restore` to `current`.
   `keel restore keel-<stamp>.tar.gz` does steps 1 (the checksum) and 3:
   it checks the manifest checksums, rebuilds the vector shards, points
   `previous` at the old build and `current` at the restored one, and puts
   the archived audit log under `<logs dir>/restored-<stamp>/`.
4. Start the app and check `/api/health` and `/api/ready`.

Test the restore once before the pilot and record the date in
`docs/BUILD_REPORT.md`. Last tested on 2026-10-22 (index 1.2.0 into an
empty index directory, 6.2 s); repeat it on the pilot host.

## Vercel

Vercel cannot host the API: serverless functions have no persistent disk
and a bundle size limit far below PyTorch. The interview demo runs on a
laptop at `http://localhost:8000` and needs no host at all.
