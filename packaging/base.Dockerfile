FROM registry.access.redhat.com/ubi9/ubi-minimal:9.8

WORKDIR /root

# Security-related RPMs (keep in sync with Trivy reports on the built image)
ARG SECURITY_RPMS=\
glib2 glibc glibc-common glibc-minimal-langpack glibc-devel glibc-headers \
krb5-libs \
libcap \
openssl openssl-libs \
p11-kit \
expat sqlite-libs \
curl curl-minimal libcurl-minimal \
gnutls \
libarchive \
libblkid libfdisk libmount libsmartcols libuuid util-linux util-linux-core \
python3 python3-libs python3.12 python3.12-devel python3.12-libs \
libnghttp2

RUN microdnf upgrade -y \
    && microdnf install -y python3.12 python3.12-devel python3.12-pip gcc g++ make findutils which \
    && ln -sf /usr/bin/python3.12 /usr/bin/python3 \
    && ln -sf /usr/bin/python3.12 /usr/bin/python \
    && ln -sf /usr/bin/pip3.12 /usr/bin/pip3 \
    && echo "[centos-stream]" > /etc/yum.repos.d/centos-stream.repo \
    && echo "name=CentOS Stream 9 - BaseOS" >> /etc/yum.repos.d/centos-stream.repo \
    && echo "baseurl=https://mirror.stream.centos.org/9-stream/BaseOS/\$basearch/os/" >> /etc/yum.repos.d/centos-stream.repo \
    && echo "enabled=1" >> /etc/yum.repos.d/centos-stream.repo \
    && echo "gpgcheck=0" >> /etc/yum.repos.d/centos-stream.repo \
    && microdnf install -y nfs-utils rpcbind ktls-utils e2fsprogs xfsprogs \
    && microdnf update -y ${SECURITY_RPMS} \
    && microdnf clean all

COPY pyproject.toml poetry.lock* ./
# Required Licenses
COPY LICENSE /licenses/LICENSE

# Install Poetry and python dependencies
# PIP_DEFAULT_TIMEOUT: arm64 QEMU emulation is slow — large wheels (grpcio) need more time to download
ENV PIP_DEFAULT_TIMEOUT=300
RUN curl -sSL https://install.python-poetry.org | python3 - --version 1.8.5 \
    && mv /root/.local/bin/poetry /usr/local/bin/poetry \
    && poetry config virtualenvs.create false \
    && poetry config virtualenvs.in-project true \
    && poetry config virtualenvs.options.no-pip true \
    && mkdir .venv \
    && poetry install --only main,dev \
    && rm -f poetry.lock* \
    && /root/.venv/bin/python -m ensurepip --upgrade \
    && /root/.venv/bin/python -m pip install --upgrade setuptools jaraco.context wheel \
    && /root/.venv/bin/python -m pip uninstall pip -y \
    && rm -rf /root/.local /usr/local/bin/poetry /root/.config/poetry \
    && ln -sf /usr/bin/python3.12 /usr/bin/python3


# Dynamically find the GCC directory and remove GCC files
RUN set -ex; \
    gcc_dirs=$(find /usr/libexec/gcc -mindepth 1 -maxdepth 1 -type d); \
    if [ -n "$gcc_dirs" ]; then \
        for gcc_dir in $gcc_dirs; do \
            echo "Found GCC directory: $gcc_dir"; \
            cd "$gcc_dir" && rm -fv cc1 cc1obj cc1plus lto1 || true; \
        done; \
    else \
        echo "No suitable GCC directories found."; \
    fi
