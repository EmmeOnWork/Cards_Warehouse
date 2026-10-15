output "state_bucket" {
  description = "Bucket that holds the Terraform states: these foundations and the platform."
  value       = aws_s3_bucket.this["tfstate"].bucket
}

output "photos_bucket" {
  description = "Bucket of the item photos, read and written by the app."
  value       = aws_s3_bucket.this["photos"].bucket
}

output "app_user" {
  description = "IAM user whose access key, created by hand, goes into Infisical."
  value       = aws_iam_user.app.name
}

output "backups_bucket" {
  description = "Bucket of the Velero backups."
  value       = aws_s3_bucket.this["backups"].bucket
}
