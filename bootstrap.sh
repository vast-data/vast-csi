yum -y groupinstall 'Development Tools'
yum -y install epel-release net-tools which clang lldb scons libcmocka libcmocka-devel libunwind libunwind-devel libconfig libconfig-devel install doxygen xorg-x11-xauth vim-enhanced zsh libaio

chsh -s /bin/zsh vagrant

# install oh-my-zsh
su vagrant << EOF
git clone git://github.com/robbyrussell/oh-my-zsh.git ~/.oh-my-zsh
cp ~/.oh-my-zsh/templates/zshrc.zsh-template ~/.zshrc
sed -i 's/ZSH_THEME="robbyrussell"/ZSH_THEME="risto"/g' ~/.zshrc
EOF
