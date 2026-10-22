# CI for the infrastructure (D-39): the Terraform state lives in S3 so that
# infra.yml can run `terraform plan` on pull requests and a nightly drift
# check on main. The plan role is read-only, assumed through GitHub OIDC
# from main only; it reads no S3 object but the state (the backups hold the
# audit log), nor
# parameter, secret, or log contents. The provider lock file is committed, so
# a pull request cannot swap the provider build its plan runs.

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "tfstate" {
  #checkov:skip=CKV_AWS_145:SSE-S3 (AES256) is enough for a 1-month pilot state; KMS adds a key to manage
  #checkov:skip=CKV_AWS_18:access logs need a second bucket; versioning plus CloudTrail cover the pilot
  #checkov:skip=CKV_AWS_144:cross-region replication is out of scope for a 1-month pilot (D-39)
  #checkov:skip=CKV2_AWS_62:no consumer for event notifications on the state bucket
  bucket = "keel-${var.environment}-tfstate-${data.aws_caller_identity.current.account_id}"

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket                  = aws_s3_bucket.tfstate.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  rule {
    id     = "old-state-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 90
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

data "aws_iam_policy_document" "plan_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Only main (pushes, the nightly drift check, and runs on demand); a
    # pull request runs no code with AWS credentials.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["${var.github_subject_prefix}:ref:refs/heads/main"]
    }
  }
}

data "aws_iam_policy_document" "plan" {
  statement {
    sid       = "ReadTheState"
    actions   = ["s3:GetObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.tfstate.arn, "${aws_s3_bucket.tfstate.arn}/*"]
  }

  statement {
    sid    = "NoSecretsOrLogContents"
    effect = "Deny"
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:GetParametersByPath",
      "ssm:GetParameterHistory",
      "ssm:GetCommandInvocation",
      "ssm:ListCommandInvocations",
      "secretsmanager:GetSecretValue",
      "secretsmanager:BatchGetSecretValue",
      "logs:GetLogEvents",
      "logs:FilterLogEvents",
      "logs:GetLogRecord",
      "logs:StartQuery",
      "logs:GetQueryResults",
      "logs:StartLiveTail",
      "ec2:GetConsoleOutput",
      "ec2:GetConsoleScreenshot",
    ]
    resources = ["*"]
  }

  statement {
    sid           = "NoObjectReadsBeyondTheState"
    effect        = "Deny"
    actions       = ["s3:GetObject", "s3:GetObjectVersion"]
    not_resources = ["${aws_s3_bucket.tfstate.arn}/pilot/*"]
  }

  statement {
    sid       = "NoInstanceUserData"
    effect    = "Deny"
    actions   = ["ec2:DescribeInstanceAttribute"]
    resources = ["*"]
  }
}

resource "aws_iam_role" "plan" {
  name                 = "keel-${var.environment}-plan"
  assume_role_policy   = data.aws_iam_policy_document.plan_assume.json
  max_session_duration = 3600
}

resource "aws_iam_role_policy_attachment" "plan_read_only" {
  role       = aws_iam_role.plan.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

resource "aws_iam_role_policy" "plan" {
  name   = "terraform-plan"
  role   = aws_iam_role.plan.id
  policy = data.aws_iam_policy_document.plan.json
}
