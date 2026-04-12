package common

import (
	"context"
	"errors"
	"net"
	"strings"
)

// networkErrSubstrings are substrings present in network-level error messages.
// The go-vast-client wraps the underlying *url.Error / *net.OpError with %v
// (not %w), so errors.As / errors.Is cannot traverse the chain; we fall back
// to message inspection as the primary detection mechanism.
var networkErrSubstrings = []string{
	"dial tcp",
	"i/o timeout",
	"connection refused",
	"connection reset",
	"no route to host",
	"network is unreachable",
	"connection timed out",
	"context deadline exceeded",
	// WaitResource exhausted its polling window because the cluster was
	// unreachable on every poll attempt.
	"timed out after",
	"EOF",
}

// IsNetworkError reports whether err represents a connectivity failure.
//
// Detection order:
//  1. errors.Is(context.DeadlineExceeded) — catches properly-wrapped K8s
//     client context timeouts.
//  2. errors.As(*net.OpError) — catches properly-wrapped net-layer errors.
//  3. Message substring scan — the VAST client formats the underlying
//     *url.Error / *net.OpError with %v (not %w), breaking the error chain;
//     we must inspect the rendered message to detect those cases.
func IsNetworkError(err error) bool {
	if err == nil {
		return false
	}
	if errors.Is(err, context.DeadlineExceeded) {
		return true
	}
	var netErr *net.OpError
	if errors.As(err, &netErr) {
		return true
	}
	msg := err.Error()
	for _, sub := range networkErrSubstrings {
		if strings.Contains(msg, sub) {
			return true
		}
	}
	return false
}
