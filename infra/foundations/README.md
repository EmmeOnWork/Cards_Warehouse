# Foundations

The AWS resources that outlive every recreation of the platform:

- `emmeonwork-cards-warehouse-tfstate`: the Terraform states, versioned, with native S3 locking (no DynamoDB);
- `emmeonwork-cards-warehouse-photos`: item photos, versioned;
- `emmeonwork-cards-warehouse-backups`: Velero backups;
- `cards-warehouse-app`: an IAM user that can only read and write objects in the photos and backups buckets;
- a monthly budget that emails above 5 USD of spending, counted before credits.

Every bucket blocks public access and is protected by `prevent_destroy`. The foundations change rarely and are never destroyed.

## Tools

Terraform and the AWS CLI run in the toolbox container, at the versions pinned in [../toolbox/Dockerfile](../toolbox/Dockerfile). From the repository root:

```sh
make shell                # a shell with terraform and aws, the repository in /work
aws login --remote        # inside the shell: temporary credentials, no access keys on disk
```

`aws login` signs in with the console user and its MFA, and keeps the session for up to 12 hours.

## Checks

```sh
make tf-check                              # format, validity and unit tests: no AWS needed
bash infra/foundations/tests/acceptance.sh # inside make shell: the real account
```

The unit tests in [tests/foundations.tftest.hcl](tests/foundations.tftest.hcl) check the plan against a mock AWS provider. The acceptance test checks what AWS actually does.

## Bootstrap, once per AWS account

The state bucket cannot hold the state that creates it before it exists. The first apply therefore keeps the state on disk, then moves it to S3. Inside `make shell`, after `aws login --remote`:

```sh
cd infra/foundations
cp terraform.tfvars.example terraform.tfvars   # then set alert_email; the file is ignored by Git

# 1. Create everything with a local state. Files named *_override.tf replace
#    the backend block of backend.tf, and Git ignores them.
printf 'terraform {\n  backend "local" {}\n}\n' > bootstrap_override.tf
terraform init
terraform apply

# 2. Move the state into the bucket just created, then delete the local copies.
rm bootstrap_override.tf
terraform init -migrate-state                  # answer "yes" to copy the state
rm terraform.tfstate terraform.tfstate.backup

# 3. Check the result.
bash tests/acceptance.sh
```

## The app credential

Terraform creates the `cards-warehouse-app` user and its permissions, never its access key: everything Terraform creates is written into the state, so the key would get a second copy outside Infisical. The key is created by hand in the IAM console and pasted straight into Infisical.

## Costs and the AWS free plan

Checked on 2026-10-14 against the [AWS free plan documentation](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier-plans.html) and the S3 price list published by AWS on 2026-10-12.

- New accounts get 100 USD of credits, plus up to 100 USD for completing activities. On the free plan nothing is ever charged.
- The free plan ends after six months or when the credits run out, whichever comes first. The account then closes, and AWS deletes its data after 90 days unless it is upgraded to the paid plan.
- Joining AWS Organizations upgrades the account to the paid plan automatically. This is why there is no IAM Identity Center here: it needs Organizations to grant access to the account.
- S3 Standard in eu-central-1: 0.0245 USD per GB-month, 0.0054 USD per 1,000 PUT/LIST requests, 0.00043 USD per 1,000 GET requests. A few GB of photos and backups cost cents per month.
- Before the sixth month: upgrade to the paid plan, or move photos and backups elsewhere.
