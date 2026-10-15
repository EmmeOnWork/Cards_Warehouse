locals {
  # Where the Argo CD UI listens on the cluster node; cluster.tf publishes it on the PC.
  argocd_node_port = 30080
}

resource "helm_release" "argocd" {
  name             = "argocd"
  repository       = "https://argoproj.github.io/argo-helm"
  chart            = "argo-cd"
  version          = "10.9.7" # Argo CD v3.5.4
  namespace        = "argocd"
  create_namespace = true

  values = [yamlencode({
    configs = {
      # Plain HTTP: the UI is published only on the PC's loopback, where TLS
      # would add nothing but a certificate warning.
      params = { "server.insecure" = true }
    }
    server = {
      service = {
        type         = "NodePort"
        nodePortHttp = local.argocd_node_port
      }
    }
    # Unused: single sign-on, notifications and generated applications.
    # Fewer pods, so the platform starts faster and weighs less on the PC.
    dex            = { enabled = false }
    notifications  = { enabled = false }
    applicationSet = { replicas = 0 }
  })]
}

# The root application: Argo CD applies whatever gitops/apps holds, Application
# manifests included, so everything else reaches the cluster through Git.
# A chart rather than a kubernetes_manifest, which needs the cluster already at plan time.
resource "helm_release" "root_app" {
  name       = "root-app"
  repository = "https://argoproj.github.io/argo-helm"
  chart      = "argocd-apps"
  version    = "2.0.6"
  namespace  = "argocd"
  # The Application kind exists only once Argo CD is installed.
  depends_on = [helm_release.argocd]

  values = [yamlencode({
    applications = {
      root = {
        namespace = "argocd"
        project   = "default"
        # Argo CD polls GitHub: GitHub cannot reach a cluster on the PC.
        source = {
          repoURL        = "https://github.com/EmmeOnWork/Cards_Warehouse.git"
          targetRevision = "main"
          path           = "gitops/apps"
        }
        destination = {
          server    = "https://kubernetes.default.svc"
          namespace = "argocd"
        }
        syncPolicy = {
          automated = {
            prune    = true
            selfHeal = true
          }
        }
      }
    }
  })]
}
