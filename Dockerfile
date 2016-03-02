FROM centos

RUN yum -y groupinstall 'Development Tools'
RUN yum -y install epel-release
RUN yum -y install clang
RUN yum -y install scons

WORKDIR /source

CMD bash
