# infra

Terraform code, in two separate parts:

- [**foundations**](foundations/): S3 buckets, the scoped AWS credential and the budget alert. Rarely changed, never destroyed.
- [**platform**](platform/): the kind cluster, Argo CD and its root application. Recreated with one command.

[**tailscale**](tailscale/) is not Terraform: a container that brings the app to the phone away from home, through a private Tailscale network. It outlives the cluster.

Terraform, the AWS CLI, kubectl and Helm run in the [toolbox](toolbox/) container: `make shell` opens it, `make tf-check` checks format, validity and tests of all the Terraform code.
