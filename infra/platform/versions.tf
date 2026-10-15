terraform {
  required_version = "~> 1.16"

  required_providers {
    # Community provider, one maintainer: state checked on 2026-10-15, see README.md.
    kind = {
      source  = "tehcyx/kind"
      version = "~> 0.11.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 3.3"
    }
  }
}

# Configured from the attributes of the cluster, not from a kubeconfig file:
# within the same apply, the cluster is created first and Helm then talks to it.
provider "helm" {
  kubernetes = {
    host                   = kind_cluster.this.endpoint
    client_certificate     = kind_cluster.this.client_certificate
    client_key             = kind_cluster.this.client_key
    cluster_ca_certificate = kind_cluster.this.cluster_ca_certificate
  }
}
