FROM registry.access.redhat.com/ubi9/ubi-minimal

WORKDIR /root

# Install basic tools and dependencies
RUN microdnf upgrade -y \
    && microdnf install -y python3 python3-devel python3-pip gcc g++ make findutils which \
    && microdnf clean all

# Add CentOS Stream 9 repository for nfs-utils installation
RUN echo "[centos-stream]" > /etc/yum.repos.d/centos-stream.repo \
    && echo "name=CentOS Stream 9 - BaseOS" >> /etc/yum.repos.d/centos-stream.repo \
    && echo "baseurl=https://mirror.stream.centos.org/9-stream/BaseOS/\$basearch/os/" >> /etc/yum.repos.d/centos-stream.repo \
    && echo "enabled=1" >> /etc/yum.repos.d/centos-stream.repo \
    && echo "gpgcheck=0" >> /etc/yum.repos.d/centos-stream.repo \
    && microdnf install -y nfs-utils \
    && microdnf clean all

COPY pyproject.toml poetry.lock* ./
# Required Licenses
COPY LICENSE /licenses/LICENSE

# Install Poetry and python dependencies
RUN curl -sSL https://install.python-poetry.org | python3 - --version 1.8.3 \
    && mv /root/.local/bin/poetry /usr/local/bin/poetry \
    && poetry config virtualenvs.create false \
    && poetry config virtualenvs.in-project true \
    && poetry config virtualenvs.options.no-pip true \
    && mkdir .venv \
    && poetry install --no-dev \
    && rm -f poetry.lock*

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
