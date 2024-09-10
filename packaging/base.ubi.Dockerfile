FROM registry.access.redhat.com/ubi9/ubi-minimal

WORKDIR /root

# Install basic tools for both architectures
RUN microdnf install -y python3 python3-devel python3-pip gcc g++ make yum findutils && microdnf clean all

# Add CentOS Stream 9 repository for nfs-utils installation
RUN echo "[centos-stream]" > /etc/yum.repos.d/centos-stream.repo \
    && echo "name=CentOS Stream 9 - BaseOS" >> /etc/yum.repos.d/centos-stream.repo \
    && echo "baseurl=https://mirror.stream.centos.org/9-stream/BaseOS/\$basearch/os/" >> /etc/yum.repos.d/centos-stream.repo \
    && echo "enabled=1" >> /etc/yum.repos.d/centos-stream.repo \
    && echo "gpgcheck=0" >> /etc/yum.repos.d/centos-stream.repo \
    && microdnf install -y nfs-utils \
    && microdnf clean all

RUN pip install --no-cache-dir grpcio==1.25.0
