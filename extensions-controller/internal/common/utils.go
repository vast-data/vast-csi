package common

import metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

// OwnerByKind returns the first OwnerReference whose Kind matches the given
// string, or nil if none is found.
func OwnerByKind(refs []metav1.OwnerReference, kind string) *metav1.OwnerReference {
	for i := range refs {
		if refs[i].Kind == kind {
			return &refs[i]
		}
	}
	return nil
}
