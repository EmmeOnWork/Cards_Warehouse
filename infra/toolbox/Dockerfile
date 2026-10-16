# syntax=docker/dockerfile:1
# Toolbox: the exact terraform, AWS CLI, kubectl, Helm and Docker CLI versions, so the PC needs nothing but Docker.
FROM hashicorp/terraform:1.16.6 AS terraform

# Helm and its unit test plugin ship as archives: unpacked here, so the final image keeps only the binaries.
FROM alpine:3.24 AS helm
# The Helm that Argo CD 3.5.4 renders charts with (its hack/tool-versions.sh): the checks see what the cluster gets.
ADD --checksum=sha256:479dca836e5b45e8bd222400c5591b0e3a647378f03ff96597180db97c17fdae \
    https://get.helm.sh/helm-v4.2.1-linux-amd64.tar.gz /tmp/helm.tar.gz
ADD --checksum=sha256:48e86ecc1467b009630e5954375e5d8494139f73b466df5fe8c04fa45b634939 \
    https://github.com/helm-unittest/helm-unittest/releases/download/v1.2.1/helm-unittest-linux-amd64-1.2.1.tgz /tmp/unittest.tgz
# A plugin is a folder holding plugin.yaml and its binary: unpacking it is the whole install,
# and no install hook downloads anything at build time.
RUN tar -xzf /tmp/helm.tar.gz -C /usr/local/bin --strip-components=1 linux-amd64/helm \
 && mkdir -p /plugins/unittest \
 && tar -xzf /tmp/unittest.tgz -C /plugins/unittest plugin.yaml untt-linux-amd64

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
COPY --from=helm /usr/local/bin/helm /usr/local/bin/helm
COPY --from=helm /plugins /usr/local/lib/helm/plugins
ENV HELM_PLUGINS=/usr/local/lib/helm/plugins
# Validates what the chart renders against the Kubernetes API schemas.
COPY --from=ghcr.io/yannh/kubeconform:v0.8.0 /kubeconform /usr/local/bin/kubeconform

WORKDIR /work
ENTRYPOINT []
CMD ["bash"]
