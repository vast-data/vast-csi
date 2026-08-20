package main

import (
	"context"
	"errors"
	"os"
	"path/filepath"

	"github.com/fatih/color"
	"k8s.io/klog/v2"

	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd"
	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd/namespace"
)

var errorColor = color.New(color.FgRed).FprintfFunc()

func main() {
	defer klog.Flush()

	baseName := filepath.Base(os.Args[0])
	root := cmd.NewCommand(baseName)

	var err error
	if cmd.IsOperator(root) {
		err = namespace.ExecuteNamespace(root, os.Args[1:])
	} else {
		err = root.Execute()
	}

	if err != nil {
		if !errors.Is(err, context.Canceled) {
			errorColor(os.Stderr, "%s\n", err.Error())
		}
		os.Exit(1)
	}
}
