/*
Copyright 2025.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package controller

import (
	"fmt"
	"strings"
	"sync"
	"sync/atomic"
)

// refLock is a mutex with a reference counter for cleanup
type refLock struct {
	mu  sync.Mutex
	ref int32
}

// KeyLocker provides per-key locking to allow concurrent reconciliation
// of different resources while preventing concurrent reconciliation of the same resource
type KeyLocker struct {
	locks sync.Map
	sep   string
}

// NewKeyLocker creates a new KeyLocker
func NewKeyLocker() *KeyLocker {
	return &KeyLocker{sep: ":"}
}

// Lock acquires a lock for the given key(s) and returns an unlock function
// Multiple keys are joined with a separator to create a composite key
// Example: Lock("VastCluster", "my-cluster") locks "VastCluster:my-cluster"
func (kl *KeyLocker) Lock(keys ...any) func() {
	var parts []string
	for _, k := range keys {
		parts = append(parts, fmt.Sprintf("%v", k))
	}
	combinedKey := strings.Join(parts, kl.sep)

	// Get or create a lock for this key
	lockIface, _ := kl.locks.LoadOrStore(combinedKey, &refLock{})
	lock := lockIface.(*refLock)

	// Increment reference counter and acquire lock
	atomic.AddInt32(&lock.ref, 1)
	lock.mu.Lock()

	// Return a closure that unlocks and cleans up if no more references
	return func() {
		lock.mu.Unlock()
		// If this was the last reference, remove the lock from the map
		if atomic.AddInt32(&lock.ref, -1) == 0 {
			kl.locks.Delete(combinedKey)
		}
	}
}
