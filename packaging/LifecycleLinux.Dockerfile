# Test the exported package in a fresh desktop session, not the build container.
ARG BASE=ubuntu:24.04
FROM ${BASE}
ARG QA_UID=1000
ARG QA_GID=1000
ARG USER_INSTALL=0
RUN if command -v apt-get >/dev/null; then \
      if [ "$USER_INSTALL" = 1 ]; then \
        set -- libx11-6 libxext6 libxrender1 libxft2 libxss1 alsa-utils; \
      else set -- sudo; fi; \
      apt-get update && apt-get install -y --no-install-recommends curl ca-certificates procps \
        xvfb dbus-x11 libgtk-3-bin x11-utils fonts-dejavu-core "$@"; \
    else \
      if [ "$USER_INSTALL" = 1 ]; then \
        set -- rpm cpio 'libc.so.6(GLIBC_2.35)(64bit)' libX11 libXext libXrender libXft libXScrnSaver alsa-utils; \
      else set -- sudo; fi; \
      dnf install -y curl-minimal ca-certificates procps-ng xorg-x11-server-Xvfb \
        dbus-x11 gtk3 xorg-x11-utils dejavu-sans-fonts "$@" && dnf clean all; \
    fi \
    && if getent passwd "$QA_UID" >/dev/null; then userdel "$(getent passwd "$QA_UID" | cut -d: -f1)"; fi \
    && if ! getent group "$QA_GID" >/dev/null; then groupadd -g "$QA_GID" qa; fi \
    && useradd -m -u "$QA_UID" -g "$QA_GID" qa \
    && if [ "$USER_INSTALL" = 0 ]; then printf 'qa ALL=(ALL) NOPASSWD: ALL\n' > /etc/sudoers.d/flinteye-qa; fi
USER qa
ENV DISPLAY=:99 FLINTEYE_DATA_DIR=/qa/profile
CMD ["sh", "-c", "Xvfb :99 -screen 0 1440x1000x24 -nolisten tcp & exec sleep infinity"]
