# infra

Terraform code, in two separate parts:

- [**foundations**](foundations/): S3 buckets, the scoped AWS credential and the budget alert. Rarely changed, never destroyed.
- **platform**: the kind cluster, Argo CD and its root application. Recreated with one command. Not written yet.

Terraform and the AWS CLI run in the [toolbox](toolbox/) container: `make shell` opens it, `make tf-check` checks format, validity and tests of all the Terraform code.
