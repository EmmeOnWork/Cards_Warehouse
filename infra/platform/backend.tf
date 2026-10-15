# Same bucket as the foundations, separate key: destroying the platform
# never touches the foundations state.
terraform {
  backend "s3" {
    bucket       = "emmeonwork-cards-warehouse-tfstate"
    key          = "platform/terraform.tfstate"
    region       = "eu-north-1"
    use_lockfile = true
  }
}
