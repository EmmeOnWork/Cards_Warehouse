# The state lives in a bucket that these same foundations create: README.md
# describes the one-time bootstrap that moves it here from the local disk.
terraform {
  backend "s3" {
    bucket = "emmeonwork-cards-warehouse-tfstate"
    key    = "foundations/terraform.tfstate"
    region = "eu-north-1"
    # Native locking: a lock file next to the state, created with an S3
    # conditional write, so no DynamoDB table is needed.
    use_lockfile = true
  }
}
