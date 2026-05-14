package vmsrest

import (
	"fmt"
	"time"

	"github.com/vast-data/go-vast-client/core"
)

// WaitCondition describes what to wait for.
type WaitCondition int

const (
	// WaitConditionPresent waits until the resource exists.
	WaitConditionPresent WaitCondition = iota
	// WaitConditionAbsent waits until the resource no longer exists.
	WaitConditionAbsent
)

func (c WaitCondition) String() string {
	switch c {
	case WaitConditionPresent:
		return "present"
	case WaitConditionAbsent:
		return "absent"
	default:
		return "unknown"
	}
}

// resourceExistsChecker is the minimal interface used by WaitForResource.
// It is satisfied by *core.VastResource and every untyped resource that embeds it.
type resourceExistsChecker interface {
	Exists(params core.Params) (bool, error)
}

// WaitResource is the low-level polling primitive. It calls checkFn every sleep
// until checkFn returns (true, nil) or timeout elapses.
//
// A non-nil error from checkFn aborts immediately and is returned to the caller.
// description is used only in the timeout error message.
func WaitResource(
	timeout, sleep time.Duration,
	description string,
	checkFn func() (bool, error),
) error {
	deadline := time.Now().Add(timeout)
	for {
		done, err := checkFn()
		if err != nil {
			return err
		}
		if done {
			return nil
		}
		if time.Now().After(deadline) {
			return fmt.Errorf("timed out after %s waiting for %s to be %s",
				timeout, description, "ready")
		}
		time.Sleep(sleep)
	}
}

// WaitForResource polls a VAST resource until it satisfies condition.
//
// For WaitConditionPresent it returns nil as soon as Exists() is true.
// For WaitConditionAbsent  it returns nil as soon as Exists() is false.
func WaitForResource(
	resource resourceExistsChecker,
	params core.Params,
	condition WaitCondition,
	timeout, sleep time.Duration,
	description string,
) error {
	return WaitResource(timeout, sleep, description, func() (bool, error) {
		exists, err := resource.Exists(params)
		if err != nil {
			return false, fmt.Errorf("checking %s: %w", description, err)
		}
		switch condition {
		case WaitConditionPresent:
			return exists, nil
		case WaitConditionAbsent:
			return !exists, nil
		default:
			return false, fmt.Errorf("unknown WaitCondition %d", condition)
		}
	})
}
