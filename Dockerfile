FROM node:22-bookworm-slim@sha256:e9f565d32859f0cbfb52125eafe8be39390f24dac302dc3cdf566e8ba3ab21ee AS ui
WORKDIR /src/frontend
COPY frontend/package*.json ./
COPY frontend/scripts/ ./scripts/
RUN npm ci
COPY frontend/ ./
RUN npm run build
WORKDIR /src
COPY packaging/collect_frontend_licenses.mjs ./packaging/
RUN node packaging/collect_frontend_licenses.mjs /licenses/frontend

FROM golang:1.27.4-bookworm@sha256:4fa7c968ba93f1635670522dbb01a2c78150443e1385746924566079f36570ea AS gotoolchain
FROM scratch AS vendor-downloads
COPY packaging/empty-cache/ /
FROM python:3.13-slim-trixie@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90 AS media
COPY --from=gotoolchain /usr/local/go /usr/local/go
ENV PATH="/usr/local/go/bin:${PATH}"
WORKDIR /opt/flinteye
COPY --from=vendor-downloads / ./vendor/downloads/
COPY packaging/vendor.py packaging/vendor-lock.json packaging/release_lib.py ./packaging/
COPY flinteye_app/_version.py ./flinteye_app/
RUN --mount=type=cache,target=/root/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    python packaging/vendor.py mediamtx && python packaging/vendor.py notices \
    && tar -czf /media-source.tar.gz vendor/src vendor/downloads packaging flinteye_app/_version.py

FROM scratch AS media-sources
COPY --from=media /media-source.tar.gz /

FROM python:3.13-slim-trixie@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core alsa-utils zlib1g \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/flinteye
COPY requirements.txt ./
COPY packaging/constraints.txt ./packaging/
# Keep the runtime free of pip's bundled build-time libraries, including the
# copy inside the ensurepip bootstrap wheel. Install dependencies at build time.
RUN python -m pip install --no-cache-dir -c packaging/constraints.txt -r requirements.txt \
    && python -c "import ensurepip, pathlib, shutil; shutil.rmtree(pathlib.Path(ensurepip.__file__).parent)" \
    && python -m pip uninstall --yes pip
COPY flinteye.py ./
COPY flinteye_app/ ./flinteye_app/
COPY LICENSE THIRD_PARTY_NOTICES.md ./
COPY packaging/collect_licenses.py packaging/container_sources.py ./packaging/
COPY packaging/container_health.py ./packaging/
COPY docs/LAN_ACCESS.md docs/LAN_ACCESS.ja.md ./docs/
RUN python packaging/collect_licenses.py /opt/flinteye/licenses
COPY --from=ui /src/frontend/dist ./frontend/dist
COPY --from=ui /licenses/frontend ./licenses/frontend
COPY --from=media /opt/flinteye/vendor/bin/mediamtx ./bin/mediamtx
COPY --from=media /opt/flinteye/vendor/licenses/ ./licenses/media/
ARG FLINTEYE_VERSION=development
ARG FLINTEYE_REVISION=unknown
ARG FLINTEYE_BUILD_DIRTY=false
RUN python -c "import json,os; json.dump({'commit': os.environ.get('FLINTEYE_REVISION'), 'dirty': os.environ.get('FLINTEYE_BUILD_DIRTY') == 'true'}, open('build-info.json', 'w'))"
LABEL org.opencontainers.image.title="FlintEye" \
      org.opencontainers.image.description="Private camera monitoring and recording on your own infrastructure" \
      org.opencontainers.image.documentation="https://github.com/noguhiro2002/FlintEye/blob/main/docs/DOCKER.md" \
      org.opencontainers.image.source="https://github.com/noguhiro2002/FlintEye" \
      org.opencontainers.image.version=$FLINTEYE_VERSION \
      org.opencontainers.image.revision=$FLINTEYE_REVISION \
      org.opencontainers.image.licenses="LicenseRef-FlintEye-SUL-Additional-Permission"
RUN useradd --uid 10001 --create-home flinteye && mkdir /data && chown flinteye:flinteye /data
USER 10001:10001
ENV FLINTEYE_DATA_DIR=/data
VOLUME ["/data"]
EXPOSE 18080/tcp 8189/udp 8322/tcp
HEALTHCHECK --interval=30s --start-period=30s CMD python /opt/flinteye/packaging/container_health.py
ENTRYPOINT ["python", "/opt/flinteye/flinteye.py", "--headless"]
