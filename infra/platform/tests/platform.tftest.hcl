# Unit tests of the platform. They check the plan against mock providers,
# so they need no Docker, no cluster and no AWS, and run in a few seconds.
mock_provider "kind" {}
mock_provider "helm" {}

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

run "root_application_follows_main_and_undoes_manual_changes" {
  command = plan

  assert {
    condition = yamldecode(helm_release.root_app.values[0]).applications.root.source == {
      repoURL        = "https://github.com/EmmeOnWork/Cards_Warehouse.git"
      targetRevision = "main"
      path           = "gitops/apps"
    }
    error_message = "The root application must read gitops/apps from the main branch of the public repository."
  }

  assert {
    condition = yamldecode(helm_release.root_app.values[0]).applications.root.syncPolicy.automated == {
      prune    = true
      selfHeal = true
    }
    error_message = "The root application must sync on its own, undo manual changes and delete what leaves Git."
  }
}
