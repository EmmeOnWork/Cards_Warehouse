# Toolbox: the exact terraform and AWS CLI versions, so the PC needs nothing but Docker.
FROM hashicorp/terraform:1.16.6 AS terraform

FROM amazon/aws-cli:2.38.0

# terraform is a static Go binary: copying it is enough to run it on any Linux base.
COPY --from=terraform /bin/terraform /usr/local/bin/terraform

WORKDIR /work
ENTRYPOINT []
CMD ["bash"]
