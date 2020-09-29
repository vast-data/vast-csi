FROM registry.access.redhat.com/ubi7/ubi:latest

ARG MAINTAINER=ofer.koren@vastdata.com
MAINTAINER "VAST Data" <$MAINTAINER>


### add licenses to this directory
COPY LICENSE /licenses/vast-csi
COPY NOTICE.txt /licenses/vast-csi-notice.txt

ENV PYTHON_VERSION=3.6 \
    PATH=$HOME/.local/bin/:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=UTF-8 \
    LC_ALL=en_US.UTF-8 \
    LANG=en_US.UTF-8 \
    PIP_NO_CACHE_DIR=off

#  nss_wrapper atlas-devel gcc-gfortran libffi-devel libtool-ltdl enchant
#  prepare-yum-repositories rhel-server-rhscl-7-rpms && \


ARG APP_ROOT=/csi

WORKDIR $APP_ROOT

COPY packaging/files .
RUN INSTALL_PKGS="rh-python36 rh-python36-python-devel rh-python36-python-setuptools rh-python36-python-pip gcc" && \
    yum install -y yum-utils && \
    yum -y --setopt=tsflags=nodocs install $INSTALL_PKGS && \
    rpm -V $INSTALL_PKGS && \
    yum -y clean all --enablerepo='*' && \
    source scl_source enable rh-python36 && \
    virtualenv $APP_ROOT && \
    chown -R 1001:0 $APP_ROOT && \
    ./fix-permissions $APP_ROOT -P && \
    ./rpm-file-permissions && \
    $APP_ROOT/bin/pip install --no-cache-dir -r requirements.txt && \
    yum remove -y gcc && yum -y clean all 

COPY vast_csi $APP_ROOT/lib/python3.6/site-packages/vast_csi
COPY deployment .

RUN \
  setcap cap_sys_admin=ep $APP_ROOT/bin/python3 && \
  ln -sf $APP_ROOT/bin/python /usr/bin/python3

USER 1001

ARG NAME=csi.vastdata.com
ARG RELEASE=101
ARG VERSION
ARG GIT_COMMIT=0
ARG CI_PIPELINE_ID=0

RUN echo "$NAME $VERSION $GIT_COMMIT" > $APP_ROOT/version.info 

### Required OpenShift Labels 
LABEL name="$NAME" \
      maintainer="$MAINTAINER" \
      vendor="vastdata" \
      version="$VERSION.$GIT_COMMIT.$CI_PIPELINE_ID" \
      release="$RELEASE" \
      summary="VAST Data CSI Driver" \
      description="A CSI driver for integrating Kubernetes with the VAST Data storage system"


ENTRYPOINT ["/usr/bin/python3", "-m", "vast_csi"]
