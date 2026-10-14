# Unit tests of the foundations. They check the plan against a mock AWS,
# so they need no credentials, cost nothing and run in a few seconds.
mock_provider "aws" {}

variables {
  alert_email = "owner@example.com"
}

run "photos_bucket_keeps_previous_versions" {
  command = plan

  assert {
    condition     = aws_s3_bucket_versioning.this["photos"].versioning_configuration[0].status == "Enabled"
    error_message = "The photos bucket must keep the previous version of every object."
  }
}

run "state_bucket_keeps_previous_versions" {
  command = plan

  assert {
    condition     = aws_s3_bucket_versioning.this["tfstate"].versioning_configuration[0].status == "Enabled"
    error_message = "The state bucket must keep previous versions, to recover from a corrupted state."
  }
}

run "no_project_bucket_is_public" {
  command = plan

  assert {
    condition = alltrue([
      for name in ["tfstate", "photos", "backups"] : alltrue([
        aws_s3_bucket_public_access_block.this[name].bucket == "emmeonwork-cards-warehouse-${name}",
        aws_s3_bucket_public_access_block.this[name].block_public_acls,
        aws_s3_bucket_public_access_block.this[name].block_public_policy,
        aws_s3_bucket_public_access_block.this[name].ignore_public_acls,
        aws_s3_bucket_public_access_block.this[name].restrict_public_buckets,
      ])
    ])
    error_message = "The state, photos and backups buckets must block every kind of public access."
  }
}

run "app_credential_reaches_only_the_photos_and_backups_buckets" {
  command = plan

  assert {
    condition     = aws_iam_user_policy.app.user == "cards-warehouse-app"
    error_message = "The permissions must belong to the app user."
  }

  assert {
    condition = toset(flatten([for s in jsondecode(aws_iam_user_policy.app.policy).Statement : s.Resource])) == toset([
      "arn:aws:s3:::emmeonwork-cards-warehouse-photos",
      "arn:aws:s3:::emmeonwork-cards-warehouse-photos/*",
      "arn:aws:s3:::emmeonwork-cards-warehouse-backups",
      "arn:aws:s3:::emmeonwork-cards-warehouse-backups/*",
    ])
    error_message = "The app credential may reach the photos and backups buckets and nothing else, not even the state."
  }

  assert {
    condition = alltrue(flatten([
      for s in jsondecode(aws_iam_user_policy.app.policy).Statement : [
        for action in s.Action : s.Effect == "Allow" && startswith(action, "s3:") && !strcontains(action, "*")
      ]
    ]))
    error_message = "The app credential may only be granted explicit S3 actions, without wildcards."
  }
}

run "budget_emails_when_monthly_spending_passes_a_few_dollars" {
  command = plan

  assert {
    condition = alltrue([
      aws_budgets_budget.monthly.budget_type == "COST",
      aws_budgets_budget.monthly.time_unit == "MONTHLY",
      aws_budgets_budget.monthly.limit_unit == "USD",
      tonumber(aws_budgets_budget.monthly.limit_amount) <= 5,
    ])
    error_message = "The budget must watch the monthly cost against a limit of at most 5 USD."
  }

  assert {
    condition = anytrue([
      for n in aws_budgets_budget.monthly.notification :
      n.notification_type == "ACTUAL" && n.comparison_operator == "GREATER_THAN" &&
      n.threshold_type == "PERCENTAGE" && n.threshold <= 100 &&
      contains(n.subscriber_email_addresses, "owner@example.com")
    ])
    error_message = "The budget must email the owner once the actual spending passes the limit."
  }

  assert {
    condition     = aws_budgets_budget.monthly.cost_types[0].include_credit == false
    error_message = "The budget must count spending before credits, or the free plan credits would keep it silent."
  }
}
