package provisioner

import (
	"sort"
	"strings"
	"sync"
)

// lazyCache is a generic, concurrency-safe, error-aware cache for a single
// value.  Unlike sync.Once, it retries on error so that a transient failure
// does not permanently poison the cache.
type lazyCache[V any] struct {
	mu     sync.Mutex
	val    V
	loaded bool
}

// get returns the cached value, computing it with fetch on the first
// successful call.  Concurrent callers block until the fetch completes.
func (c *lazyCache[V]) get(fetch func() (V, error)) (V, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if !c.loaded {
		v, err := fetch()
		if err != nil {
			return v, err
		}
		c.val = v
		c.loaded = true
	}
	return c.val, nil
}

// lazyCacheMap is a collection of lazyCaches keyed by an arbitrary string (e.g.
// StorageClass name).  Each key gets its own independent cache bucket so that
// different SCs are fetched and cached separately.
type lazyCacheMap[V any] struct {
	mu     sync.Mutex
	caches map[string]*lazyCache[V]
}

// get returns the cached value for key, computing it with fetch on the first
// successful call for that key.
func (m *lazyCacheMap[V]) get(key string, fetch func() (V, error)) (V, error) {
	m.mu.Lock()
	if m.caches == nil {
		m.caches = make(map[string]*lazyCache[V])
	}
	c, ok := m.caches[key]
	if !ok {
		c = &lazyCache[V]{}
		m.caches[key] = c
	}
	m.mu.Unlock()
	return c.get(fetch)
}

// add inserts val under strings.TrimRight(entryKey, "/") into the loaded
// cache bucket for cacheKey.  Intended for map[string]any caches so that a
// newly-created object is visible to subsequent lookups without a fresh REST
// fetch.  A no-op if the cache bucket has not yet been populated or V is not
// map[string]any.
func (m *lazyCacheMap[V]) add(cacheKey, entryKey string, val any) {
	m.mu.Lock()
	c, ok := m.caches[cacheKey]
	m.mu.Unlock()
	if !ok {
		return
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.loaded {
		if mv, ok := any(c.val).(map[string]any); ok {
			mv[strings.TrimRight(entryKey, "/")] = val
		}
	}
}

// sortedKeys returns the keys of m in sorted order.
func sortedKeys[V any](m map[string]V) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}
