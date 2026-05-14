package errors

import (
	"fmt"
	"strings"
	"time"
)

// Retryable is implemented by errors that want the controller to pause before
// the next reconcile attempt.
//
// RetryAfter returns nil to request the controller's default back-off, or a
// non-nil pointer to schedule a specific delay before the next reconcile.
// The controller detects this via errors.As, so the value may be wrapped
// inside another error (e.g. DeferredError).
type Retryable interface {
	RetryAfter() *time.Duration
}

// RetryAfterError is a concrete Retryable that carries a fixed delay and an
// underlying cause.
type RetryAfterError struct {
	err   error
	delay time.Duration
}

// NewRetryAfterError wraps cause with the given reconcile delay.
func NewRetryAfterError(cause error, delay time.Duration) *RetryAfterError {
	return &RetryAfterError{err: cause, delay: delay}
}

func (e *RetryAfterError) Error() string              { return e.err.Error() }
func (e *RetryAfterError) Unwrap() error              { return e.err }
func (e *RetryAfterError) RetryAfter() *time.Duration { return &e.delay }

// ValidationError indicates that the resource spec is misconfigured and cannot
// be reconciled until the user corrects it.  Unlike transient errors it does
// not benefit from retries; the controller sets SyncStatusInvalid and waits
// for a spec change to re-trigger reconciliation.
type ValidationError struct {
	msg string
}

// NewValidationError creates a ValidationError with a formatted message.
func NewValidationError(format string, args ...any) *ValidationError {
	return &ValidationError{msg: fmt.Sprintf(format, args...)}
}

func (e *ValidationError) Error() string { return e.msg }

// DeferredError accumulates multiple errors so that a loop can continue past
// individual failures and report all of them together at the end.
//
// Typical usage:
//
//	var errs cerrors.DeferredError
//	for _, item := range items {
//	    if err := process(item); err != nil {
//	        errs.Add(err)
//	    }
//	}
//	return errs.Err()
type DeferredError struct {
	errs []error
}

// Add appends err to the collection. nil values are silently ignored.
func (d *DeferredError) Add(err error) {
	if err != nil {
		d.errs = append(d.errs, err)
	}
}

// IsEmpty reports whether no errors have been accumulated.
func (d *DeferredError) IsEmpty() bool {
	return len(d.errs) == 0
}

// Merge absorbs all errors from other into d, flattening the nested
// DeferredError into d's own list rather than wrapping it.
func (d *DeferredError) Merge(other *DeferredError) {
	d.errs = append(d.errs, other.errs...)
}

// Unwrap returns all accumulated errors so that errors.As / errors.Is can
// traverse into a DeferredError and find wrapped types such as RetryAfterError.
func (d *DeferredError) Unwrap() []error {
	return d.errs
}

// Err returns nil when no errors were accumulated, or d itself (as an error)
// otherwise. This lets callers write a single idiomatic "return errs.Err()".
func (d *DeferredError) Err() error {
	if d.IsEmpty() {
		return nil
	}
	return d
}

// Error implements the error interface. Each accumulated error is rendered on
// its own line, prefixed with "- ", for example:
//
//	2 errors occurred:
//	- failed to create volume foo: connection refused
//	- failed to create volume bar: timeout
func (d *DeferredError) Error() string {
	if len(d.errs) == 1 {
		return d.errs[0].Error()
	}
	var sb strings.Builder
	sb.WriteString(itoa(len(d.errs)))
	sb.WriteString(" errors occurred:\n")
	for _, err := range d.errs {
		sb.WriteString("  - ")
		sb.WriteString(err.Error())
		sb.WriteString("\n")
	}
	return strings.TrimRight(sb.String(), "\n")
}

// itoa is a minimal int-to-string helper to avoid importing "strconv".
func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	buf := [20]byte{}
	pos := len(buf)
	for n > 0 {
		pos--
		buf[pos] = byte('0' + n%10)
		n /= 10
	}
	return string(buf[pos:])
}
