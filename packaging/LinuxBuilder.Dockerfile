# Build on updated Rocky 9 so the same bundle supports Rocky 9, Ubuntu 24.04,
# and 64-bit Raspberry Pi OS Bookworm. Build natively for each target CPU.
# nfpm declares the GLIBC_2.35 symbols backported by updated Rocky 9.
FROM node:22-bookworm-slim@sha256:e9f565d32859f0cbfb52125eafe8be39390f24dac302dc3cdf566e8ba3ab21ee AS node
FROM golang:1.27.4-bookworm@sha256:4fa7c968ba93f1635670522dbb01a2c78150443e1385746924566079f36570ea AS go
FROM scratch AS vendor-downloads
COPY packaging/empty-cache/ /
FROM rockylinux:9@sha256:d7be1c094cc5845ee815d4632fe377514ee6ebcf8efaed6892889657e5ddaaa6 AS builder
# Refresh installed libraries before packaging so their exact source RPMs are available.
RUN dnf upgrade -y --refresh \
    && dnf install -y dnf-plugins-core && dnf config-manager --set-enabled crb \
    && dnf install -y gcc gcc-c++ make cmake ninja-build pkgconf-pkg-config nasm \
       python3.12 python3.12-pip openssl-devel bzip2-devel libffi-devel zlib-devel \
       xz-devel readline-devel sqlite-devel tk-devel libuuid-devel libX11-devel \
       libXft-devel libXext-devel libXScrnSaver-devel git tar gzip patch which \
       dejavu-sans-fonts \
    && dnf clean all
COPY --from=node /usr/local/ /opt/node/
COPY --from=go /usr/local/go /usr/local/go
ENV PATH="/opt/python/bin:/opt/node/bin:/usr/local/go/bin:/root/go/bin:${PATH}" \
    LD_LIBRARY_PATH="/opt/python/lib" \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
COPY --from=vendor-downloads / ./vendor/downloads/
COPY packaging/vendor.py packaging/vendor-lock.json packaging/release_lib.py ./packaging/
COPY flinteye_app/_version.py ./flinteye_app/
RUN python3.12 packaging/vendor.py fetch python \
    && cd vendor/src/python && ./configure --prefix=/opt/python --enable-shared --with-ensurepip=install \
    && make -j4 && make install \
    && ln -s python3.13 /opt/python/bin/python
COPY requirements.txt ./
COPY packaging/requirements-build.txt packaging/constraints.txt ./packaging/
RUN python -m pip install -c packaging/constraints.txt -r requirements.txt -r packaging/requirements-build.txt meson==1.9.1 ninja==1.13.0 \
    && go install github.com/goreleaser/nfpm/v2/cmd/nfpm@v2.49.0
COPY packaging/build_vendor.sh packaging/LinuxBuilder.Dockerfile ./packaging/
RUN bash packaging/build_vendor.sh
COPY . .
ARG FLINTEYE_REVISION
RUN python packaging/build_bundle.py --vendor vendor \
    && VERSION=$(python -c 'import sys; sys.path.insert(0,"packaging"); from release_lib import version; print(version())') \
    && ARCH=$(uname -m) && if [ "$ARCH" = x86_64 ]; then ARCH=amd64; else ARCH=arm64; fi \
    && export VERSION ARCH \
    && nfpm package --config packaging/nfpm.yaml --packager deb --target "dist/FlintEye-$VERSION-linux-$ARCH.deb" \
    && nfpm package --config packaging/nfpm.yaml --packager rpm --target "dist/FlintEye-$VERSION-linux-$ARCH.rpm" \
    && ./dist/FlintEye/FlintEye --version \
    && mkdir /artifacts && cp dist/FlintEye-* /artifacts/
FROM scratch AS artifacts
COPY --from=builder /artifacts/ /
