package backoff

import (
	"time"

	"k8s.io/apimachinery/pkg/types"
	"k8s.io/client-go/util/workqueue"
)

// Tracker provides per-object exponential backoff for requeue delays.
//
// Backed by the standard k8s workqueue typed exponential failure rate limiter:
//   - each consecutive failure for the same key doubles the delay (base × 2^N)
//   - capped at MaxDelay
//   - Reset(key) clears all failure history for that key
//
// Safe for concurrent use.
type Tracker struct {
	limiter workqueue.TypedRateLimiter[types.NamespacedName]
}

// New returns a Tracker with the given base and max delays.
func New(baseDelay, maxDelay time.Duration) *Tracker {
	return &Tracker{
		limiter: workqueue.NewTypedItemExponentialFailureRateLimiter[types.NamespacedName](baseDelay, maxDelay),
	}
}

// Next returns the delay to use for the next requeue of the given object,
// increasing it exponentially on every consecutive call.
func (t *Tracker) Next(key types.NamespacedName) time.Duration {
	return t.limiter.When(key)
}

// Reset clears the backoff state for the given object.
// Call when a reconcile succeeds so the counter starts fresh on the next failure.
func (t *Tracker) Reset(key types.NamespacedName) {
	t.limiter.Forget(key)
}

// Failures returns how many consecutive failures have been recorded for key.
func (t *Tracker) Failures(key types.NamespacedName) int {
	return t.limiter.NumRequeues(key)
}

// For returns a BoundBackoff with the given key pre-bound so callers never
// have to pass the key on every Next/Reset/Failures call.
func (t *Tracker) For(key types.NamespacedName) *BoundBackoff {
	return &BoundBackoff{tracker: t, key: key}
}

// BoundBackoff is a Tracker with a specific key pre-bound for convenience,
// analogous to events.BoundReporter.
type BoundBackoff struct {
	tracker *Tracker
	key     types.NamespacedName
}

// Next returns the next requeue delay for the bound key, increasing
// exponentially on every consecutive call.
func (b *BoundBackoff) Next() time.Duration { return b.tracker.Next(b.key) }

// Reset clears the backoff state for the bound key.
func (b *BoundBackoff) Reset() { b.tracker.Reset(b.key) }

// Failures returns how many consecutive failures have been recorded for the
// bound key.
func (b *BoundBackoff) Failures() int { return b.tracker.Failures(b.key) }
