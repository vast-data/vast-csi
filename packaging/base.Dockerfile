FROM registry.access.redhat.com/ubi10/ubi-minimal:10.0

WORKDIR /root

# Security-related RPMs (keep in sync with Trivy reports on the built image)
ARG SECURITY_RPMS=\
glib2 glibc glibc-common glibc-minimal-langpack \
krb5-libs \
libcap \
openssl openssl-libs \
p11-kit \
expat sqlite-libs \
curl curl-minimal libcurl-minimal \
gnutls \
libarchive \
libblkid libfdisk libmount libsmartcols libuuid util-linux util-linux-core \
python3 python3-libs \
libnghttp2

# UBI upgrade + build/runtime Python toolchain from UBI10 only.
RUN microdnf upgrade -y \
    && microdnf install -y python3 python3-devel python3-pip gcc gcc-c++ make findutils which \
    && ln -sf /usr/bin/python3.12 /usr/local/bin/python3 \
    && ln -sf /usr/bin/python3.12 /usr/local/bin/python \
    && ln -sf /usr/bin/pip3.12 /usr/local/bin/pip3 \
    && microdnf update -y ${SECURITY_RPMS} \
    && microdnf clean all

# nfs-utils / ktls-utils / e2fsprogs / xfsprogs are not in default UBI10 repos — pull from
# CentOS Stream 10 only for those packages (repos disabled afterward).
RUN echo "[centos-stream]" > /etc/yum.repos.d/centos-stream.repo \
    && echo "name=CentOS Stream 10 - BaseOS" >> /etc/yum.repos.d/centos-stream.repo \
    && echo "baseurl=https://mirror.stream.centos.org/10-stream/BaseOS/\$basearch/os/" >> /etc/yum.repos.d/centos-stream.repo \
    && echo "enabled=1" >> /etc/yum.repos.d/centos-stream.repo \
    && echo "gpgcheck=0" >> /etc/yum.repos.d/centos-stream.repo \
    && echo "[centos-stream-appstream]" > /etc/yum.repos.d/centos-stream-appstream.repo \
    && echo "name=CentOS Stream 10 - AppStream" >> /etc/yum.repos.d/centos-stream-appstream.repo \
    && echo "baseurl=https://mirror.stream.centos.org/10-stream/AppStream/\$basearch/os/" >> /etc/yum.repos.d/centos-stream-appstream.repo \
    && echo "enabled=1" >> /etc/yum.repos.d/centos-stream-appstream.repo \
    && echo "gpgcheck=0" >> /etc/yum.repos.d/centos-stream-appstream.repo \
    && microdnf install -y nfs-utils rpcbind ktls-utils e2fsprogs xfsprogs \
    && sed -i 's/^enabled=1/enabled=0/' /etc/yum.repos.d/centos-stream.repo \
         /etc/yum.repos.d/centos-stream-appstream.repo \
    && microdnf clean all

COPY pyproject.toml poetry.lock* ./
# Required Licenses
COPY LICENSE /licenses/LICENSE

# Install Poetry and python dependencies
# PIP_DEFAULT_TIMEOUT: arm64 QEMU emulation is slow — large wheels (grpcio) need more time to download
ENV PIP_DEFAULT_TIMEOUT=300
RUN curl -sSL https://install.python-poetry.org | python3.12 - --version 1.8.5 \
    && mv /root/.local/bin/poetry /usr/local/bin/poetry \
    && poetry config virtualenvs.create false \
    && poetry config virtualenvs.in-project true \
    && poetry config virtualenvs.options.no-pip true \
    && /usr/bin/python3.12 -m venv /root/.venv \
    && poetry install --only main,dev \
    && rm -f poetry.lock* \
    && /root/.venv/bin/python -m ensurepip --upgrade \
    && /root/.venv/bin/python -m pip install --upgrade setuptools jaraco.context wheel \
    && /root/.venv/bin/python -m pip uninstall pip -y \
    && rm -rf /root/.local /usr/local/bin/poetry /root/.config/poetry \
    && microdnf remove -y gcc gcc-c++ cpp make binutils binutils-gold \
         python3-devel kernel-headers glibc-devel glibc-headers libxcrypt-devel \
    && microdnf clean all


# Dynamically find the GCC directory and remove GCC files
RUN set -ex; \
    gcc_dirs=$(find /usr/libexec/gcc -mindepth 1 -maxdepth 1 -type d 2>/dev/null || true); \
    if [ -n "$gcc_dirs" ]; then \
        for gcc_dir in $gcc_dirs; do \
            echo "Found GCC directory: $gcc_dir"; \
            cd "$gcc_dir" && rm -fv cc1 cc1obj cc1plus lto1 || true; \
        done; \
    else \
        echo "No suitable GCC directories found."; \
    fi
