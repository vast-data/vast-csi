yum -y groupinstall 'Development Tools'
yum -y install epel-release
yum -y install net-tools which clang lldb scons libcmocka-devel libunwind-devel libconfig-devel install doxygen xorg-x11-xauth vim-enhanced zsh centos-release-scl libaio-devel
yum -y install devtoolset-3-gcc

pip install --upgrade pip
pip install virtualenv

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
rm -rf softiwarp
