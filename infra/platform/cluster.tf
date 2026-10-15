resource "kind_cluster" "this" {
  name = "cards-warehouse"
  # Built for kind 0.31, the kind inside provider 0.11, and pinned by digest as the
  # kind release notes recommend. Kubernetes 1.35+ refuses cgroup v1 hosts, and Docker
  # Desktop on this PC (WSL 2.4, kernel 5.15) still runs cgroup v1: see README.md.
  node_image     = "kindest/node:v1.34.3@sha256:08497ee19eace7b4b5348db5c6a1591d7752b164530a36f855cb0f2bdcbadd48"
  wait_for_ready = true
  # Without a path, the provider exports the kubeconfig into the working directory,
  # inside the repository. In the toolbox, ~/.kube is a Docker volume.
  kubeconfig_path = pathexpand("~/.kube/config")

  kind_config {
    kind        = "Cluster"
    api_version = "kind.x-k8s.io/v1alpha4"

    node {
      role = "control-plane"

      # The PC reaches the cluster only through these ports, on its loopback:
      # nothing is published on the home network.
      extra_port_mappings {
        container_port = local.argocd_node_port
        host_port      = 8090
        listen_address = "127.0.0.1"
      }
    }
  }
}
