package namespace

import (
	"context"
	"fmt"

	"github.com/spf13/cobra"

	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd/manager"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/config"
)

type state struct {
	ctx        Context
	namespaces []Namespace
}

type stateKey struct{}

// Context carries shared dependencies passed to every namespace.
type Context struct {
	SharedMgr *manager.SharedManager
	Config    *config.Config
}

// Namespace is a manager entrypoint: manager <name> [flags].
type Namespace interface {
	// Name is the cobra namespace command and config.Display component key.
	Name() string
	Short() string
	Long() string

	RegisterFlags(cmd *cobra.Command, cfg *config.Config)
	Configure(ctx Context, cmd *cobra.Command)
}

// Attach registers namespace groups on the manager root and stores execution
// state for ExecuteNamespace.
func Attach(root *cobra.Command, ctx Context, namespaces ...Namespace) {
	for _, ns := range namespaces {
		group := &cobra.Command{
			Use:   ns.Name(),
			Short: ns.Short(),
			Long:  ns.Long(),
		}
		ns.RegisterFlags(group, ctx.Config)
		ns.Configure(ctx, group)
		root.AddCommand(group)
	}

	parentCtx := root.Context()
	if parentCtx == nil {
		parentCtx = context.Background()
	}
	root.SetContext(context.WithValue(parentCtx, stateKey{}, state{
		ctx:        ctx,
		namespaces: namespaces,
	}))
}

// ExecuteNamespace runs the manager with multi-namespace argv parsing.
func ExecuteNamespace(root *cobra.Command, args []string) error {
	st, ok := root.Context().Value(stateKey{}).(state)
	if !ok {
		panic("manager command missing namespace state")
	}
	return execute(root, st.ctx, st.namespaces, args)
}

// execute runs one or more namespace invocations from argv.
//
// Pattern: [global flags] <ns1> [ns flags] <ns2> [ns flags] ...
//
// Examples:
//
//	manager replication
//	manager replication webhook
//	manager --dev-logging replication --pvc-name-format=x webhook --enable-pvc-label-webhook
func execute(root *cobra.Command, ctx Context, namespaces []Namespace, args []string) error {
	if len(args) == 0 || hasHelp(args) {
		return root.Help()
	}

	rootArgs, rest := splitLeadingFlags(args)
	if err := root.ParseFlags(rootArgs); err != nil {
		return err
	}

	if root.PersistentPreRun != nil {
		root.PersistentPreRun(root, rest)
	}

	invocations, err := parseInvocations(rest, namespaces)
	if err != nil {
		return err
	}

	for _, inv := range invocations {
		cmd, _, err := root.Find([]string{inv.Namespace})
		if err != nil {
			return fmt.Errorf("%s: %w", inv.Namespace, err)
		}
		if len(inv.Flags) > 0 {
			if err := cmd.ParseFlags(inv.Flags); err != nil {
				return fmt.Errorf("%s: %w", inv.Namespace, err)
			}
		}
		if err := invoke(cmd); err != nil {
			return err
		}
		fmt.Println(ctx.Config.Display(inv.Namespace))
	}

	return ctx.SharedMgr.Start()
}

func hasHelp(args []string) bool {
	for _, a := range args {
		if a == "-h" || a == "--help" {
			return true
		}
	}
	return false
}

func invoke(cmd *cobra.Command) error {
	if err := cmd.ValidateRequiredFlags(); err != nil {
		return err
	}
	if cmd.PreRunE != nil {
		if err := cmd.PreRunE(cmd, []string{}); err != nil {
			return err
		}
	} else if cmd.PreRun != nil {
		cmd.PreRun(cmd, []string{})
	}
	if cmd.RunE != nil {
		return cmd.RunE(cmd, []string{})
	}
	if cmd.Run != nil {
		cmd.Run(cmd, []string{})
	}
	return nil
}
