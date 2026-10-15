# syntax=docker/dockerfile:1
# Toolbox: the exact terraform, AWS CLI, kubectl and Docker CLI versions, so the PC needs nothing but Docker.
FROM hashicorp/terraform:1.16.6 AS terraform

FROM amazon/aws-cli:2.38.0

# git lets the platform acceptance test see which files Git would pick up.
RUN dnf install -y git-core && dnf clean all

# terraform is a static Go binary: copying it is enough to run it on any Linux base.
COPY --from=terraform /bin/terraform /usr/local/bin/terraform
# The kind provider drives the PC's Docker through the docker CLI and the mounted socket.
COPY --from=docker:29.5.2-cli /usr/local/bin/docker /usr/local/bin/docker
# kubectl within one minor version of the cluster, verified against its published checksum.
ADD --chmod=755 --checksum=sha256:3cfeaf80be482b435b0aa214aff6e0b2c312ee23c0ff20810c75517b6004c6eb \
    https://dl.k8s.io/release/v1.35.9/bin/linux/amd64/kubectl /usr/local/bin/kubectl

WORKDIR /work
ENTRYPOINT []
CMD ["bash"]
