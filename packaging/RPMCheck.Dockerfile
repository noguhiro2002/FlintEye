# Start with the pinned older Rocky image so missing runtime upgrades are caught.
FROM rockylinux:9@sha256:d7be1c094cc5845ee815d4632fe377514ee6ebcf8efaed6892889657e5ddaaa6
ARG ARCH=amd64
ARG VERSION
COPY FlintEye-${VERSION}-linux-${ARCH}.rpm /tmp/flinteye.rpm
RUN dnf install -y /tmp/flinteye.rpm curl-minimal \
    && dnf clean all && rm /tmp/flinteye.rpm
USER 65532:65532
ENTRYPOINT ["bash"]
