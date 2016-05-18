yum -y groupinstall 'Development Tools'
yum -y install epel-release
yum -y install net-tools which
yum -y install clang lldb scons
yum -y install libcmocka libcmocka-devel
yum -y install libunwind libunwind-devel
yum -y install libconfig libconfig-devel
yum -y install doxygen
yum -y install xorg-x11-xauth
yum -y install vim-enhanced
yum -y install zsh

chsh -s /bin/zsh vagrant

# install oh-my-zsh
su vagrant << EOF
git clone git://github.com/robbyrussell/oh-my-zsh.git ~/.oh-my-zsh
cp ~/.oh-my-zsh/templates/zshrc.zsh-template ~/.zshrc
sed -i 's/ZSH_THEME="robbyrussell"/ZSH_THEME="risto"/g' ~/.zshrc
EOF
