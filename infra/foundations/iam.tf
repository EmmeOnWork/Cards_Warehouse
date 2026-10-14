# The credential the cluster uses for photos and backups. Terraform creates the user
# and its permissions but never its access key: Terraform writes everything it creates
# into the state, so the key would get a second copy outside Infisical.
# The key is created by hand in the AWS console and pasted straight into Infisical.
resource "aws_iam_user" "app" {
  name = "cards-warehouse-app"
}

locals {
  # Built from the names rather than from the bucket ARNs, so the whole policy
  # is already readable in the plan instead of being "known after apply".
  app_buckets = [for name in ["photos", "backups"] : "arn:aws:s3:::${aws_s3_bucket.this[name].bucket}"]
}

resource "aws_iam_user_policy" "app" {
  name = "photos-and-backups"
  user = aws_iam_user.app.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ListObjects"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = local.app_buckets
      },
      {
        Sid      = "ReadAndWriteObjects"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = [for bucket in local.app_buckets : "${bucket}/*"]
      },
    ]
  })
}
