output "state_bucket" {
  description = "Bucket that holds the Terraform states: these foundations and the platform."
  value       = aws_s3_bucket.this["tfstate"].bucket
}
