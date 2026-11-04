# Distroless CSI base (multi-stage):
#   builder: gke-debian  (gke.gcr.io/debian-base — ships /usr/local/bin/clean-install)
#   final:   gke-distroless/libc (no Python — copy interpreter from builder)
#
# Upstream pins (mirror to ECR for CI; pass via DEBIAN_BASE / BASE_IMAGE / CSI_BASE):
#   gke.gcr.io/debian-base:bookworm-v1.0.8-gke.12
#   gke.gcr.io/gke-distroless/libc:gke_distroless_20260928.00_p0
ARG DEBIAN_BASE=gke.gcr.io/debian-base:bookworm-v1.0.8-gke.12
ARG BASE_IMAGE=gke.gcr.io/gke-distroless/libc:gke_distroless_20260928.00_p0

FROM ${DEBIAN_BASE} AS builder

ARG TARGETARCH

WORKDIR /root

ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_DEFAULT_TIMEOUT=300

# Pin matches UBI (ktls-utils-0.11): newer tlshd breaks NFS mTLS vs current VAST.
# Ubuntu .deb Depends on *t64 package names (Noble+); bookworm lacks those names,
# so extract the binary and link against bookworm libgnutls30/libglib2.0-0 (same SONAMEs).
ARG KTLS_UTILS_VERSION=0.11-1

# debian-base provides clean-install (apt-get update/install plus cache cleanup).
# zlib1g/libffi/… : Python DT_NEEDED (distroless/libc does not ship them).
# nfs-kernel-server: rpc.mountd (optional nfs-services sidecar).
# libc-bin provides /usr/bin/ldd (a bash script) — required for shared-lib staging.
# bash is required to execute that script; without both, lib staging is a no-op
# and the distroless image ships a Python that cannot find libz.so.1.
RUN clean-install \
      ca-certificates curl gcc g++ make findutils libc-bin bash coreutils \
      python3 python3-dev python3-pip python3-venv \
      nfs-common nfs-kernel-server rpcbind e2fsprogs xfsprogs util-linux mount keyutils \
      netbase debianutils dash openssl \
      zlib1g libffi8 liblzma5 libbz2-1.0 libncursesw6 libreadline8 \
      libssl3 libgnutls30 libcurl4 libsqlite3-0 libexpat1 \
      libcap2 libblkid1 libuuid1 libmount1 libsmartcols1 \
      libnl-3-200 libnl-genl-3-200 libglib2.0-0 \
      libgcc-s1 libstdc++6 \
    && set -eux; \
      test -x /usr/bin/ldd; \
      test -x /bin/bash; \
      case "${TARGETARCH}" in \
        amd64) \
          KTLS_URL="https://archive.ubuntu.com/ubuntu/pool/universe/k/ktls-utils/ktls-utils_${KTLS_UTILS_VERSION}_amd64.deb" ;; \
        arm64) \
          KTLS_URL="https://ports.ubuntu.com/ubuntu-ports/pool/universe/k/ktls-utils/ktls-utils_${KTLS_UTILS_VERSION}_arm64.deb" ;; \
        *) echo "unsupported TARGETARCH=${TARGETARCH}" >&2; exit 1 ;; \
      esac; \
      curl -fsSL -o /tmp/ktls-utils.deb "${KTLS_URL}"; \
      dpkg-deb -x /tmp/ktls-utils.deb /tmp/ktls; \
      install -m 0755 /tmp/ktls/usr/sbin/tlshd /usr/sbin/tlshd; \
      if [ -f /tmp/ktls/etc/tlshd.conf ]; then \
        install -m 0644 /tmp/ktls/etc/tlshd.conf /etc/tlshd.conf; \
      fi; \
      rm -rf /tmp/ktls /tmp/ktls-utils.deb; \
      test -x /usr/sbin/tlshd

COPY pyproject.toml poetry.lock* ./
COPY LICENSE /licenses/LICENSE

# Install Poetry + deps into /root/.venv; keep interpreter as system python3
# (bookworm → 3.11). Distroless final has no python — we COPY it below.
RUN curl -sSL https://install.python-poetry.org | python3 - --version 1.8.5 \
    && mv /root/.local/bin/poetry /usr/local/bin/poetry \
    && poetry config virtualenvs.create false \
    && poetry config virtualenvs.in-project true \
    && poetry config virtualenvs.options.no-pip true \
    && /usr/bin/python3 -m venv /root/.venv \
    && poetry install --only main,dev \
    && rm -f poetry.lock* \
    && /root/.venv/bin/python -m ensurepip --upgrade \
    && /root/.venv/bin/python -m pip install --upgrade setuptools jaraco.context wheel \
    && /root/.venv/bin/python -m pip uninstall pip -y \
    && rm -rf /root/.local /usr/local/bin/poetry /root/.config/poetry \
    && apt-get purge -y --auto-remove gcc g++ make python3-dev \
    && apt-get update \
    && apt-get install -y --no-install-recommends binutils libgcc-s1 libstdc++6 \
    && /root/.venv/bin/python -c "from cryptography import x509; print('cryptography ok')" \
    && rm -rf /var/lib/apt/lists/*

# Stage CSI/nfs/block binaries + shared libs for Distroless.
# Use readelf (not ldd): under qemu, ldd reports foreign-arch ELFs as
# "not a dynamic executable" and would stage zero libraries.
RUN set -eux; \
    stage() { \
      src="$1"; \
      [ -e "$src" ] || return 0; \
      mkdir -p "/opt/csi-runtime$(dirname "$src")"; \
      cp -aL "$src" "/opt/csi-runtime$src"; \
    }; \
    resolve_soname() { \
      s="$1"; \
      p=$(ldconfig -p 2>/dev/null | awk -v n="$s" '$1 == n { print $NF; exit }'); \
      if [ -n "$p" ] && [ -e "$p" ]; then echo "$p"; return 0; fi; \
      for d in /lib /usr/lib /lib64 /lib/*-linux-gnu /usr/lib/*-linux-gnu; do \
        if [ -e "$d/$s" ]; then echo "$d/$s"; return 0; fi; \
      done; \
      return 1; \
    }; \
    list_needed() { \
      # Prefer readelf (works cross-arch under qemu); ldd only on native.
      needed=$(readelf -d "$1" 2>/dev/null | sed -n 's/.*Shared library: \[\(.*\)\]/\1/p' || true); \
      if [ -n "$needed" ]; then \
        printf '%s\n' $needed; \
        return 0; \
      fi; \
      /usr/bin/ldd "$1" 2>/dev/null | awk '/=> \// {print $1}' || true; \
    }; \
    stage_deps() { \
      bin="$1"; \
      [ -e "$bin" ] || return 0; \
      stage "$bin"; \
      case "$bin" in \
        /bin/*)  stage_as="/usr/bin/${bin#/bin/}"; \
                 mkdir -p "/opt/csi-runtime$(dirname "$stage_as")"; \
                 cp -aL "$bin" "/opt/csi-runtime$stage_as" ;; \
        /sbin/*) stage_as="/usr/sbin/${bin#/sbin/}"; \
                 mkdir -p "/opt/csi-runtime$(dirname "$stage_as")"; \
                 cp -aL "$bin" "/opt/csi-runtime$stage_as" ;; \
      esac; \
      # BFS over DT_NEEDED so transitive deps (libz via libpython, etc.) are copied.
      queue="$bin"; \
      seen=""; \
      while [ -n "$queue" ]; do \
        set -- $queue; \
        cur="$1"; shift; \
        queue="$*"; \
        case " $seen " in *" $cur "*) continue ;; esac; \
        seen="$seen $cur"; \
        for soname in $(list_needed "$cur"); do \
          [ -n "$soname" ] || continue; \
          # Distroless/libc already ships the loader + glibc family. Copying
          # bookworm's libc into it causes loader crashes (stack smashing).
          case "$soname" in \
            linux-vdso*|ld-linux*|ld-musl*| \
            libc.so.*|libm.so.*|libdl.so.*|libpthread.so.*|librt.so.*| \
            libresolv.so.*|libnss_*|libanl.so.*|libBrokenLocale.so.*| \
            libc_malloc_debug.so.*) continue ;; \
          esac; \
          lib=$(resolve_soname "$soname" || true); \
          [ -n "$lib" ] || continue; \
          stage "$lib"; \
          queue="$queue $lib"; \
        done; \
      done; \
    }; \
    test -x /usr/bin/readelf || { echo "readelf required for staging" >&2; exit 1; }; \
    mkdir -p /opt/csi-runtime/bin /opt/csi-runtime/sbin \
             /opt/csi-runtime/lib /opt/csi-runtime/usr; \
    bins=" \
      /bin/sh /bin/cat /bin/rm /bin/echo /bin/mount /bin/umount \
      /usr/bin/findmnt /usr/bin/nsenter /usr/bin/which /usr/bin/keyctl \
      /usr/sbin/chroot /usr/bin/chroot /sbin/chroot \
      /usr/bin/mountpoint /bin/mountpoint \
      /usr/bin/blockdev /sbin/blockdev /usr/sbin/blockdev \
      /usr/bin/python3 /usr/bin/python3.11 \
      /sbin/mount.nfs /sbin/mount.nfs4 /sbin/umount.nfs /sbin/umount.nfs4 \
      /usr/sbin/mount.nfs /usr/sbin/mount.nfs4 /usr/sbin/umount.nfs /usr/sbin/umount.nfs4 \
      /usr/sbin/rpcbind /sbin/rpcbind \
      /usr/sbin/rpc.statd /sbin/rpc.statd /usr/sbin/sm-notify \
      /usr/sbin/rpc.idmapd /usr/sbin/rpc.mountd \
      /usr/sbin/rpcinfo /usr/bin/rpcinfo \
      /usr/sbin/tlshd /usr/bin/tlshd \
      /usr/sbin/mkfs.ext4 /usr/sbin/mkfs.ext3 /usr/sbin/mkfs.xfs \
      /usr/sbin/fsck.ext4 /usr/sbin/fsck.xfs \
      /usr/sbin/blkid /sbin/blkid \
      /usr/sbin/e2fsck /usr/sbin/tune2fs \
      /usr/sbin/resize2fs /usr/sbin/dumpe2fs \
      /usr/sbin/xfs_db /usr/sbin/xfs_growfs /usr/sbin/xfs_io \
    "; \
    for b in $bins; do \
      stage_deps "$b"; \
    done; \
    # Explicit sonames the loader resolves by absolute /lib path.
    for pattern in \
        '/lib/*/libz.so.1' '/usr/lib/*/libz.so.1' \
        '/lib/*/libffi.so.8' '/usr/lib/*/libffi.so.8' \
        '/lib/*/liblzma.so.5' '/usr/lib/*/liblzma.so.5' \
        '/lib/*/libbz2.so.1*' '/usr/lib/*/libbz2.so.1*' \
        '/lib/*/libreadline.so.8' '/usr/lib/*/libreadline.so.8' \
        '/lib/*/libncursesw.so.6' '/usr/lib/*/libncursesw.so.6' \
        '/lib/*/libtinfo.so.6' '/usr/lib/*/libtinfo.so.6' \
        '/lib/*/libpython3.11.so.1.0' '/usr/lib/*/libpython3.11.so.1.0' \
        '/lib/*/libkeyutils.so.1' '/usr/lib/*/libkeyutils.so.1' \
        '/lib/*/libnl-3.so.200' '/usr/lib/*/libnl-3.so.200' \
        '/lib/*/libnl-genl-3.so.200' '/usr/lib/*/libnl-genl-3.so.200' \
        '/lib/*/libglib-2.0.so.0' '/usr/lib/*/libglib-2.0.so.0' \
        '/lib/*/libgcc_s.so.1' '/usr/lib/*/libgcc_s.so.1' \
        '/lib/*/libstdc++.so.6' '/usr/lib/*/libstdc++.so.6' \
      ; do \
      for f in $pattern; do \
        [ -e "$f" ] || continue; \
        stage_deps "$f"; \
      done; \
    done; \
    # Python stdlib + dynamic modules (venv needs these next to the interpreter)
    for d in /usr/lib/python3.11 /usr/lib/python3; do \
      if [ -d "$d" ]; then \
        mkdir -p "/opt/csi-runtime$(dirname "$d")"; \
        cp -a "$d" "/opt/csi-runtime$d"; \
        find "$d" -type f -name '*.so' | while read -r so; do \
          stage_deps "$so"; \
        done; \
      fi; \
    done; \
    # Drop Debian pip/setuptools from dist-packages (venv has its own; Trivy flags these).
    find /opt/csi-runtime -type d -path '*/dist-packages' | while read -r dp; do \
      rm -rf \
        "$dp"/pip "$dp"/pip-[0-9]* \
        "$dp"/setuptools "$dp"/setuptools-[0-9]* \
        "$dp"/_distutils_hack "$dp"/pkg_resources \
        "$dp"/distutils-precedence.pth; \
    done; \
    # Native wheels in the venv (cryptography, grpcio, …) pull libgcc_s / libstdc++.
    find /root/.venv -type f \( -name '*.so' -o -name '*.so.*' \) | while read -r so; do \
      stage_deps "$so"; \
    done; \
    # TI-RPC / rpcbind need these (distroless has none). Without them rpcbind
    # exits and rpcinfo cannot resolve "portmapper" → nfs-services never ready.
    mkdir -p /opt/csi-runtime/etc; \
    for f in /etc/rpc /etc/netconfig /etc/services /etc/protocols; do \
      if [ -f "$f" ]; then cp -a "$f" "/opt/csi-runtime$f"; fi; \
    done; \
    # Optional tlshd defaults if present on the builder.
    if [ -f /etc/tlshd.conf ]; then cp -a /etc/tlshd.conf /opt/csi-runtime/etc/tlshd.conf; fi; \
    # Fail the build if critical tools/libs did not stage.
    require_any() { \
      label="$1"; shift; \
      for f in "$@"; do \
        for g in $f; do \
          if [ -e "$g" ]; then return 0; fi; \
        done; \
      done; \
      echo "staging missing required path: $label" >&2; \
      find /opt/csi-runtime -type f | sort | head -200 >&2; \
      return 1; \
    }; \
    require_any python3.11 /opt/csi-runtime/usr/bin/python3.11; \
    require_any libz.so.1 \
      '/opt/csi-runtime/lib/*/libz.so.1' \
      '/opt/csi-runtime/usr/lib/*/libz.so.1'; \
    require_any libgcc_s.so.1 \
      '/opt/csi-runtime/lib/*/libgcc_s.so.1' \
      '/opt/csi-runtime/usr/lib/*/libgcc_s.so.1'; \
    require_any 'libstdc++.so.6' \
      '/opt/csi-runtime/lib/*/libstdc++.so.6' \
      '/opt/csi-runtime/usr/lib/*/libstdc++.so.6'; \
    require_any rpcbind \
      /opt/csi-runtime/usr/sbin/rpcbind /opt/csi-runtime/sbin/rpcbind; \
    require_any rpc.statd \
      /opt/csi-runtime/usr/sbin/rpc.statd /opt/csi-runtime/sbin/rpc.statd; \
    require_any rpcinfo \
      /opt/csi-runtime/usr/sbin/rpcinfo /opt/csi-runtime/usr/bin/rpcinfo; \
    require_any tlshd \
      /opt/csi-runtime/usr/sbin/tlshd /opt/csi-runtime/usr/bin/tlshd; \
    require_any blkid \
      /opt/csi-runtime/usr/sbin/blkid /opt/csi-runtime/sbin/blkid; \
    require_any chroot \
      /opt/csi-runtime/usr/sbin/chroot \
      /opt/csi-runtime/usr/bin/chroot \
      /opt/csi-runtime/sbin/chroot; \
    require_any blockdev \
      /opt/csi-runtime/usr/bin/blockdev \
      /opt/csi-runtime/usr/sbin/blockdev \
      /opt/csi-runtime/sbin/blockdev; \
    require_any xfs_db /opt/csi-runtime/usr/sbin/xfs_db; \
    require_any resize2fs /opt/csi-runtime/usr/sbin/resize2fs; \
    require_any mount \
      /opt/csi-runtime/bin/mount \
      /opt/csi-runtime/usr/bin/mount; \
    require_any mount.nfs \
      /opt/csi-runtime/sbin/mount.nfs \
      /opt/csi-runtime/usr/sbin/mount.nfs; \
    require_any /etc/rpc /opt/csi-runtime/etc/rpc; \
    require_any /etc/netconfig /opt/csi-runtime/etc/netconfig; \
    # Belt-and-suspenders: strip glibc/loader artifacts if any slipped in.
    find /opt/csi-runtime \( \
        -name 'libc.so*' -o -name 'libm.so*' -o -name 'libdl.so*' \
        -o -name 'libpthread.so*' -o -name 'librt.so*' -o -name 'libresolv.so*' \
        -o -name 'ld-linux*' -o -name 'ld-musl*' -o -name 'libanl.so*' \
        -o -name 'libBrokenLocale.so*' -o -name 'libc_malloc_debug.so*' \
        -o -name 'libnss_*.so*' \
      \) -type f -delete

FROM ${BASE_IMAGE}

WORKDIR /root

COPY --from=builder /opt/csi-runtime/lib/ /lib/
COPY --from=builder /opt/csi-runtime/usr/ /usr/
COPY --from=builder /opt/csi-runtime/etc/ /etc/
COPY --from=builder /root/.venv /root/.venv
COPY --from=builder /licenses /licenses
