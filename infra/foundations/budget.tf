# Emails as soon as the month's spending passes 5 USD (AWS Budgets works in dollars).
resource "aws_budgets_budget" "monthly" {
  name         = "cards-warehouse-monthly"
  budget_type  = "COST"
  time_unit    = "MONTHLY"
  limit_amount = "5"
  limit_unit   = "USD"

  # On the free plan, credits pay for everything: counted after credits, the
  # spending would stay at zero and the alert would never fire.
  cost_types {
    include_credit = false
  }

  notification {
    notification_type          = "ACTUAL"
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    subscriber_email_addresses = [var.alert_email]
  }
}
