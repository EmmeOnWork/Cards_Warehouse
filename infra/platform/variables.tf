# The credential the cluster presents to Infisical: the one secret kept by hand. It lives on the PC,
# out of the repository, in ~/.cards-warehouse/platform.env, which the toolbox loads as TF_VAR_ variables.
# Ephemeral: Terraform refuses to write these values into the plan or the state.
variable "infisical_client_id" {
  description = "Client id of the cluster's machine identity in Infisical (Universal Auth)."
  type        = string
  ephemeral   = true
}

variable "infisical_client_secret" {
  description = "Client secret of the cluster's machine identity in Infisical (Universal Auth)."
  type        = string
  sensitive   = true
  ephemeral   = true
}
