#!/usr/bin/env bash
set -o errexit
set -o nounset
set -o xtrace

yum -y groupinstall 'Development Tools'
yum -y install epel-release
yum -y install net-tools time nfstest which strace clang lldb scons libunwind-devel libconfig-devel install doxygen xorg-x11-xauth vim-enhanced zsh dstat centos-release-scl libaio-devel python34 gtest-devel libuuid-devel zlib-devel nc
yum -y install devtoolset-3-gcc

curl https://bootstrap.pypa.io/get-pip.py | python3.4
pip3.4 install setuptools virtualenv

# install oh-my-zsh for the vagrant user
chsh -s /bin/zsh vagrant

su vagrant << EOF
if [ ! -d ~/.oh-my-zsh ]; then
    git clone git://github.com/robbyrussell/oh-my-zsh.git ~/.oh-my-zsh
    cp ~/.oh-my-zsh/templates/zshrc.zsh-template ~/.zshrc
    sed -i 's/ZSH_THEME="robbyrussell"/ZSH_THEME="risto"/g' ~/.zshrc
fi
EOF

# install soft iwarp
git clone https://github.com/asaf-levy/softiwarp.git
cd softiwarp
./install_me.sh
cd ..
rm -rf ./softiwarp

# make nfs test to run on local host
sudo sed -i "s/ not in ('127.0.0.1', '::1'):/:/g" /usr/lib/python2.7/site-packages/nfstest/host.py
# disable lock testing in nfs test until NLM is ready
sudo sed -i "s/ 'fcntl'/#'fcntl'/g" /usr/bin/nfstest_posix

if [[ ! -a ~/.gdbinit ]]; then
    echo "set history save on" > ~/.gdbinit
fi

echo "Bootstrap script has finished successfully!"
