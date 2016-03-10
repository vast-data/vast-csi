FROM centos

RUN yum -y groupinstall 'Development Tools'
RUN yum -y install epel-release
RUN yum -y install clang
RUN yum -y install scons
RUN yum -y install libcmocka libcmocka-devel
RUN yum -y install doxygen

WORKDIR /source

CMD bash
