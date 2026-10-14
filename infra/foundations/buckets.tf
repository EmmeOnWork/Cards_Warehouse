locals {
  # Bucket names are global across AWS: the prefix makes them unique.
  prefix = "emmeonwork-cards-warehouse"
}

resource "aws_s3_bucket" "this" {
  for_each = toset(["tfstate", "photos", "backups"])

  bucket = "${local.prefix}-${each.key}"

  # The foundations outlive every recreation of the platform: never destroyed.
  lifecycle {
    prevent_destroy = true
  }
}

# Previous versions recover a corrupted state or a photo deleted by mistake.
# Backups need none: Velero keeps several of them and expires the old ones itself.
resource "aws_s3_bucket_versioning" "this" {
  for_each = toset(["tfstate", "photos"])

  bucket = aws_s3_bucket.this[each.key].bucket
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each = aws_s3_bucket.this

  bucket                  = each.value.bucket
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
