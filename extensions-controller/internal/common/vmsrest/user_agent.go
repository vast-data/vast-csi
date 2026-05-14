package vmsrest

import (
	"fmt"
	"runtime"
)

func getUserAgent(version string) string {
	return fmt.Sprintf(
		"csi-extension-controller, os:%s, arch:%s, version:%s",
		runtime.GOOS,
		runtime.GOARCH,
		version,
	)
}
