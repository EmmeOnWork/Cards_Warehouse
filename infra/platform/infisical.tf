# Where Argo CD installs the Infisical operator (gitops/apps/infisical-operator.yaml), and where Terraform
# puts the credential it signs in with: it must exist before Argo CD starts, so Terraform creates it.
resource "kubernetes_namespace_v1" "infisical" {
  metadata {
    name = "infisical"
    labels = {
      # As for the app: the API server refuses any pod here that could run as root or gain privileges.
      "pod-security.kubernetes.io/enforce" = "restricted"
    }
  }
}

# A write-only attribute: Terraform sends the values to the cluster and keeps them in neither
# the plan nor the state, whose bucket is versioned and would keep every old copy.
resource "kubernetes_secret_v1" "infisical_credentials" {
  metadata {
    name      = "infisical-credentials"
    namespace = kubernetes_namespace_v1.infisical.metadata[0].name
  }

  data_wo = {
    clientId     = var.infisical_client_id
    clientSecret = var.infisical_client_secret
  }
  # Not being in the state, the values cannot be compared: Terraform sends them again only when
  # this number changes. A new cluster always gets them; raise it to update a running one.
  data_wo_revision = 1
}
