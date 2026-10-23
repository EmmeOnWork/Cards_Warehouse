# Unit tests of the platform. They check the plan against mock providers,
# so they need no Docker, no cluster and no AWS, and run in a few seconds.
mock_provider "kind" {}
mock_provider "helm" {}
mock_provider "kubernetes" {}

run "argocd_ui_is_published_only_on_the_pc_loopback" {
  command = plan

  assert {
    condition = contains([
      for m in flatten([for node in flatten(kind_cluster.this.kind_config[*].node) : node.extra_port_mappings]) : m.host_port
    ], 8090)
    error_message = "The cluster must publish the Argo CD UI on port 8090 of the PC."
  }

  assert {
    condition = alltrue([
      for m in flatten([for node in flatten(kind_cluster.this.kind_config[*].node) : node.extra_port_mappings]) :
      m.listen_address == "127.0.0.1"
    ])
    error_message = "Every port the cluster publishes must listen on 127.0.0.1 only, never on the home network."
  }
}

run "the_pc_port_leads_to_the_argocd_ui" {
  command = plan

  assert {
    condition = (
      yamldecode(helm_release.argocd.values[0]).server.service.type == "NodePort" &&
      contains([
        for m in flatten([for node in flatten(kind_cluster.this.kind_config[*].node) : node.extra_port_mappings]) :
        m.container_port if m.host_port == 8090
      ], yamldecode(helm_release.argocd.values[0]).server.service.nodePortHttp)
    )
    error_message = "Port 8090 of the PC must lead to the node port where the Argo CD server listens."
  }
}

run "the_pc_port_8000_leads_to_the_app" {
  command = plan

  assert {
    condition = contains([
      for m in flatten([for node in flatten(kind_cluster.this.kind_config[*].node) : node.extra_port_mappings]) :
      m.container_port if m.host_port == 8000
    ], 30000)
    error_message = "Port 8000 of the PC must lead to node port 30000, where the chart publishes the app."
  }
}

run "root_application_follows_production_and_undoes_manual_changes" {
  command = plan

  assert {
    condition = yamldecode(helm_release.root_app.values[0]).applications.root.source == {
      repoURL        = "https://github.com/EmmeOnWork/Cards_Warehouse.git"
      targetRevision = "production"
      path           = "gitops/apps"
    }
    error_message = "The root application must read gitops/apps from the production branch of the public repository."
  }

  assert {
    condition = yamldecode(helm_release.root_app.values[0]).applications.root.syncPolicy.automated == {
      prune    = true
      selfHeal = true
    }
    error_message = "The root application must sync on its own, undo manual changes and delete what leaves Git."
  }
}

# Fake values: the real credential lives only on the PC, out of the repository.
variables {
  infisical_client_id     = "a-client-id"
  infisical_client_secret = "a-client-secret"
}

run "the_infisical_credential_is_where_the_app_chart_looks_for_it" {
  command = plan

  assert {
    condition = yamldecode(file("../../chart/values.yaml")).infisical.credentials == {
      name      = kubernetes_secret_v1.infisical_credentials.metadata[0].name
      namespace = kubernetes_secret_v1.infisical_credentials.metadata[0].namespace
    }
    error_message = "The Secret holding the Infisical credential must have the name and namespace the app's chart reads it from."
  }
}

run "the_infisical_operator_runs_where_terraform_and_the_app_chart_expect_it" {
  command = plan

  assert {
    condition     = yamldecode(file("../../gitops/apps/infisical-operator.yaml")).spec.destination.namespace == kubernetes_namespace_v1.infisical.metadata[0].name
    error_message = "Argo CD must install the Infisical operator in the namespace Terraform creates for it."
  }

  assert {
    condition = (
      yamldecode(file("../../gitops/apps/infisical-operator.yaml")).spec.source.helm.valuesObject.defaultInfisicalConnection.enabled &&
      yamldecode(file("../../chart/values.yaml")).infisical.connection == {
        name      = "default"
        namespace = kubernetes_namespace_v1.infisical.metadata[0].name
      }
    )
    error_message = "The app's chart must use the default connection the operator's chart creates in the operator's namespace."
  }
}

# The phone opens https://<node name>, no port, and gets what a browser on the PC opens: the Tailscale node
# serves HTTPS on 443 only, its certificate named after the node, and proxies only to the port of the PC
# where the cluster publishes the node port of the app's chart.
run "the_phone_https_address_leads_to_the_app" {
  command = plan

  assert {
    condition = (
      jsondecode(file("../tailscale/serve/serve.json")).TCP == { "443" = { HTTPS = true } } &&
      keys(jsondecode(file("../tailscale/serve/serve.json")).Web) == ["$${TS_CERT_DOMAIN}:443"] &&
      toset(flatten([
        for site in values(jsondecode(file("../tailscale/serve/serve.json")).Web) : [
          for handler in values(site.Handlers) : handler.Proxy
        ]
        ])) == toset([
        for m in flatten([for node in flatten(kind_cluster.this.kind_config[*].node) : node.extra_port_mappings]) :
        "http://${m.listen_address}:${m.host_port}" if m.container_port == yamldecode(file("../../chart/values.yaml")).service.nodePort
      ])
    )
    error_message = "Tailscale must serve only HTTPS on 443 under the node's name, proxied only to the port of the PC that leads to the app."
  }
}

# Neither the home network nor the internet reaches the app: the cluster publishes its port only on the PC's
# loopback, and the Tailscale node serves it without Funnel, which would put it on the internet.
run "only_the_pc_and_the_tailnet_reach_the_app" {
  command = plan

  assert {
    condition = alltrue([
      for m in flatten([for node in flatten(kind_cluster.this.kind_config[*].node) : node.extra_port_mappings]) :
      m.listen_address == "127.0.0.1" if m.container_port == yamldecode(file("../../chart/values.yaml")).service.nodePort
    ]) && !anytrue(values(try(jsondecode(file("../tailscale/serve/serve.json")).AllowFunnel, {})))
    error_message = "The app's port must listen only on the PC's loopback, and Tailscale must never turn Funnel on for it."
  }
}
