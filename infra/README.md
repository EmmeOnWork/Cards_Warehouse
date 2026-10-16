# infra

Terraform code, in two separate parts:

- [**foundations**](foundations/): S3 buckets, the scoped AWS credential and the budget alert. Rarely changed, never destroyed.
- [**platform**](platform/): the kind cluster, Argo CD and its root application. Recreated with one command.

Terraform, the AWS CLI, kubectl and Helm run in the [toolbox](toolbox/) container: `make shell` opens it, `make tf-check` checks format, validity and tests of all the Terraform code.
