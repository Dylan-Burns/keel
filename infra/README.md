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
| `terraform/` | AWS alternative: EC2 instance, Elastic IP, security group, S3 backup bucket, IAM instance profile, optional Route 53 record |
| `Caddyfile` | AWS alternative: TLS termination, security headers, SSE pass-through |
| `systemd/` | AWS alternative: `keel-refresh` and `keel-backup` service and timer units |
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
   `KEEL_CORPUS__URL` with the download URL of the corpus zip.
4. Put the corpus zip at that URL: a Railway bucket object with a signed URL,
   or a release asset of the repository. Add the URL host to the outbound
   allow list (control S-11) in `config/keel.yaml`.
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

The volume is mounted by Railway with its own ownership rules. If the
non-root `keel` user cannot write `/data` on the first start, follow the
current Railway volume documentation for the ownership setting; do not
switch the image to root.

## Railway: nightly work

The in-app scheduler (`scheduler.enabled`) runs `refresh` at 02:00 and the
backup at 02:30 inside the app, because a Railway cron service cannot share
the app's volume. The backup writes the same checksummed archive as
`backup.sh` to the S3-compatible bucket.

## AWS alternative: first deploy

1. `cd infra/terraform && terraform init && terraform apply` with a
   `terraform.tfvars` that sets `admin_cidr`, `ssh_key_name`, and
   `backup_bucket_name`. The output prints the public IP and the bucket.
2. Point a DNS name at the IP, set `route53_zone_id` and `hostname` in the
   tfvars to let Terraform create the record, or use the free
   `<public-ip>.sslip.io` name as `KEEL_HOSTNAME`; Caddy obtains a Let's
   Encrypt certificate for any of them.
3. On the host: `sudo mkdir -p /opt/keel && sudo chown ubuntu /opt/keel`,
   copy `docker-compose.yml`, `infra/`, `.env` (with `KEEL_HOSTNAME`,
   `KEEL_IMAGE`, `KEEL_BACKUP_BUCKET`), and the `corpus/` directory.
4. `docker compose --profile production up -d`, then install the timers:
   `sudo cp infra/systemd/* /etc/systemd/system/ && sudo systemctl enable --now keel-refresh.timer keel-backup.timer`.
5. In GitHub: the `production` environment, the secrets `DEPLOY_HOST`,
   `DEPLOY_USER`, `DEPLOY_SSH_KEY`, and the variable `KEEL_HOSTNAME`.
   Releases deploy through `deploy-aws.yml`.

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
`docs/BUILD_REPORT.md`.

## Vercel

Vercel cannot host the API: serverless functions have no persistent disk
and a bundle size limit far below PyTorch. The interview demo runs on a
laptop at `http://localhost:8000` and needs no host at all.
