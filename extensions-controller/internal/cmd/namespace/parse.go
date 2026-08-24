package namespace

import (
	"fmt"
	"strings"
)

type invocation struct {
	Namespace string
	Flags     []string
}

func parseInvocations(args []string, namespaces []Namespace) ([]invocation, error) {
	byName := make(map[string]Namespace, len(namespaces))
	for _, ns := range namespaces {
		byName[ns.Name()] = ns
	}

	var invocations []invocation
	var current *invocation

	flush := func() error {
		if current == nil {
			return nil
		}
		if _, ok := byName[current.Namespace]; !ok {
			return fmt.Errorf("unknown namespace %q", current.Namespace)
		}
		invocations = append(invocations, *current)
		current = nil
		return nil
	}

	for i := 0; i < len(args); i++ {
		arg := args[i]

		if ns, ok := byName[arg]; ok {
			if err := flush(); err != nil {
				return nil, err
			}
			current = &invocation{Namespace: ns.Name()}
			continue
		}

		if current == nil {
			return nil, fmt.Errorf("expected namespace name, got %q", arg)
		}

		if strings.HasPrefix(arg, "-") {
			current.Flags = append(current.Flags, arg)
			if !strings.Contains(arg, "=") && i+1 < len(args) && !strings.HasPrefix(args[i+1], "-") {
				if _, ok := byName[args[i+1]]; !ok {
					i++
					current.Flags = append(current.Flags, args[i])
				}
			}
			continue
		}

		return nil, fmt.Errorf("namespace %q does not take positional arguments, got %q", current.Namespace, arg)
	}

	if err := flush(); err != nil {
		return nil, err
	}
	if len(invocations) == 0 {
		return nil, fmt.Errorf("at least one namespace invocation is required")
	}
	return invocations, nil
}

func splitLeadingFlags(args []string) (rootFlags, rest []string) {
	i := 0
	for i < len(args) {
		if !strings.HasPrefix(args[i], "-") {
			break
		}
		rootFlags = append(rootFlags, args[i])
		if !strings.Contains(args[i], "=") && i+1 < len(args) && !strings.HasPrefix(args[i+1], "-") {
			i++
			rootFlags = append(rootFlags, args[i])
		}
		i++
	}
	return rootFlags, args[i:]
}
