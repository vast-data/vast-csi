/*
Copyright 2026.

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

package v1alpha1

import (
	"fmt"
	"strings"
)

// previewMax is the number of entries shown before the "+N more" suffix.
const previewMax = 2

// DisplayableList is a named []string slice with human-friendly formatting.
type DisplayableList []string

// First returns the first element of the list.
// Returns an error when the list is empty so callers can detect empty
// membership before attempting to use the result.
func (d DisplayableList) First() (string, error) {
	if len(d) == 0 {
		return "", fmt.Errorf("list is empty")
	}
	return d[0], nil
}

// Equal reports whether d and other contain the same elements in the same order.
func (d DisplayableList) Equal(other DisplayableList) bool {
	if len(d) != len(other) {
		return false
	}
	for i := range d {
		if d[i] != other[i] {
			return false
		}
	}
	return true
}

// String returns the list in ["a", "b", "c"] notation.
// When the list exceeds previewMax entries only the first previewMax items are
// shown followed by a "+N more" count:
//
//	["a", "b", "c" ... +7 more]
//
// Implements fmt.Stringer.
func (d DisplayableList) String() string {
	if len(d) == 0 {
		return "[]"
	}
	n := len(d)
	if n > previewMax {
		n = previewMax
	}
	quoted := make([]string, n)
	for i := 0; i < n; i++ {
		quoted[i] = `"` + d[i] + `"`
	}
	if len(d) > previewMax {
		return fmt.Sprintf("[%s ... +%d more]", strings.Join(quoted, ", "), len(d)-previewMax)
	}
	return "[" + strings.Join(quoted, ", ") + "]"
}
