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

The account was created with the new AWS sign-up experience: there is no root user, and the AWS Builder ID (with its MFA, managed in [AWS Settings](https://settings.aws.com)) owns the project account. `aws login` signs in with the Builder ID and receives temporary credentials of the project's `AccountFullAccessRole`, for up to 12 hours. IAM users can exist, but only for programmatic access: that is all `cards-warehouse-app` needs.

## Checks

```sh
make tf-check                              # format, validity and unit tests: no AWS needed
bash infra/foundations/tests/acceptance.sh # inside make shell: the real account
```

The unit tests in [tests/foundations.tftest.hcl](tests/foundations.tftest.hcl) check the plan against a mock AWS provider. The acceptance test checks what AWS actually does: the state lock, the buckets, the budget, and the app credential through a temporary access key that the test creates, never prints, and deletes before it ends.

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

Checked on 2026-10-15 against the AWS documentation of the [new sign-up experience](https://docs.aws.amazon.com/accounts/latest/reference/sign-up-for-aws.html) and the S3 price list published by AWS on 2026-10-14.

- The account is a *project* inside an AWS Organization that AWS manages. AWS service control policies pin it to one Region, **eu-north-1** (Stockholm, chosen from the contact address): creating a bucket anywhere else is denied. Only [activating advanced features](https://docs.aws.amazon.com/accounts/latest/reference/activate-advanced-features.html) would allow other Regions.
- The same policies deny console passwords for IAM users and account aliases. Access keys, IAM users and policies, S3 and Budgets are allowed. Verified on 2026-10-15 with the IAM policy simulator, which also evaluates the organization's policies.
- The free tier gives 100 USD of credits, plus up to 100 USD for completing activities. When the credits run out or the account is six months old, it [must be upgraded](https://docs.aws.amazon.com/accounts/latest/reference/upgrade-account.html) to the paid plan, which cannot be reversed. On the paid plan a project can have a spend limit (from 20 USD per month) that pauses it instead of charging more.
- S3 Standard in eu-north-1: 0.023 USD per GB-month, 0.005 USD per 1,000 PUT/LIST requests, 0.0004 USD per 1,000 GET requests. A few GB of photos and backups cost cents per month.
- Before the sixth month: upgrade to the paid plan, or move photos and backups elsewhere.
