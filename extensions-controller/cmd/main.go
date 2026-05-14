package main

import (
	"context"
	"errors"
	"os"
	"path/filepath"

	"github.com/fatih/color"
	"k8s.io/klog/v2"

	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd"
)

var errorColor = color.New(color.FgRed).FprintfFunc()

func main() {
	defer klog.Flush()

	baseName := filepath.Base(os.Args[0])

	if err := cmd.NewCommand(baseName).Execute(); err != nil {
		if !errors.Is(err, context.Canceled) {
			errorColor(os.Stderr, "%s\n", err.Error())
		}
		os.Exit(1)
	}
}
