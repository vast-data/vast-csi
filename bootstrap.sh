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

sh -c "$(curl -fsSL https://raw.githubusercontent.com/robbyrussell/oh-my-zsh/master/tools/install.sh)"
sed -i 's/ZSH_THEME="robbyrussell"/ZSH_THEME="risto"/g' /home/vagrant/.zshrc
sudo chsh -s /bin/zsh vagrant
zsh
