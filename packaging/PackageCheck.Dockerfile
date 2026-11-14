# The build context is the exported Linux release artifacts, not the checkout.
FROM ubuntu:24.04
ARG ARCH=amd64
ARG VERSION
COPY FlintEye-${VERSION}-linux-${ARCH}.deb /tmp/flinteye.deb
RUN apt-get update && apt-get install -y --no-install-recommends /tmp/flinteye.deb curl \
    && rm -rf /var/lib/apt/lists/* /tmp/flinteye.deb \
    && ! command -v python3 && ! command -v node && ! command -v git
USER 65532:65532
ENTRYPOINT ["bash"]
