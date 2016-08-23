curl https://bootstrap.pypa.io/get-pip.py | sudo python2
sudo pip2.7 install setuptools virtualenv

virtualenv venv2
venv2/bin/pip install gprof2dot

# how to use: ./dist/tests/nfs && gprof ./dist/tests/nfs | ./venv2/bin/gprof2dot | dot -Tpng -o output.png
