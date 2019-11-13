docker build . \
	-t vast-csi \
	--build-arg=GIT_COMMIT=`git rev-parse HEAD` \
	--build-arg=VERSION=0.1.0 \