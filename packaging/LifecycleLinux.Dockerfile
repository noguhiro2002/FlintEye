# Test the exported package in a fresh desktop session, not the build container.
ARG BASE=ubuntu:24.04
FROM ${BASE}
ARG QA_UID=1000
ARG QA_GID=1000
RUN if command -v apt-get >/dev/null; then \
      apt-get update && apt-get install -y --no-install-recommends sudo curl ca-certificates procps \
        xvfb dbus-x11 libgtk-3-bin x11-utils fonts-dejavu-core; \
    else \
      dnf install -y sudo curl-minimal ca-certificates procps-ng xorg-x11-server-Xvfb \
        dbus-x11 gtk3 xorg-x11-utils dejavu-sans-fonts && dnf clean all; \
    fi \
    && if getent passwd "$QA_UID" >/dev/null; then userdel "$(getent passwd "$QA_UID" | cut -d: -f1)"; fi \
    && if ! getent group "$QA_GID" >/dev/null; then groupadd -g "$QA_GID" qa; fi \
    && useradd -m -u "$QA_UID" -g "$QA_GID" qa \
    && printf 'qa ALL=(ALL) NOPASSWD: ALL\n' > /etc/sudoers.d/flinteye-qa
USER qa
ENV DISPLAY=:99 FLINTEYE_DATA_DIR=/qa/profile
CMD ["sh", "-c", "Xvfb :99 -screen 0 1440x1000x24 -nolisten tcp & exec sleep infinity"]
