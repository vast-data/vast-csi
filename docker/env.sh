docker run -v /var/run/docker.sock:/var/run/docker.sock -v "$(which docker)":/bin/docker -v "$(pwd)":/source --rm -ti --name orion orion $*
