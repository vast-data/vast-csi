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

package controller

import (
	"testing"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	vastv1alpha1 "github.com/vast-data/vast-csi/extensions-controller/api/v1alpha1"
)

func TestClearParentBlockOwnerDeletion(t *testing.T) {
	blockTrue := true
	blockFalse := false
	refs := []metav1.OwnerReference{
		{Kind: "VastStorageClassReplication", Name: "app", BlockOwnerDeletion: &blockTrue},
		{Kind: vastv1alpha1.DestinationKindVolumeGroupReplication, Name: "vgr-sc2", BlockOwnerDeletion: &blockTrue},
	}

	out, changed := clearParentBlockOwnerDeletion(refs, vastv1alpha1.DestinationKindVolumeGroupReplication, "vgr-sc2")
	if !changed {
		t.Fatal("expected change")
	}
	if out[0].BlockOwnerDeletion == nil || !*out[0].BlockOwnerDeletion {
		t.Fatal("unrelated owner ref must be unchanged")
	}
	if out[1].BlockOwnerDeletion == nil || *out[1].BlockOwnerDeletion {
		t.Fatal("parent owner ref must have blockOwnerDeletion=false")
	}

	_, changed = clearParentBlockOwnerDeletion(out, vastv1alpha1.DestinationKindVolumeGroupReplication, "vgr-sc2")
	if changed {
		t.Fatal("expected no-op when already unblocked")
	}

	_, changed = clearParentBlockOwnerDeletion(out, vastv1alpha1.DestinationKindVolumeGroupReplication, "missing")
	if changed {
		t.Fatal("expected no-op for non-matching owner name")
	}

	refs = []metav1.OwnerReference{
		{Kind: vastv1alpha1.DestinationKindVolumeGroupReplication, Name: "vgr", BlockOwnerDeletion: &blockFalse},
	}
	_, changed = clearParentBlockOwnerDeletion(refs, vastv1alpha1.DestinationKindVolumeGroupReplication, "vgr")
	if changed {
		t.Fatal("expected no-op when blockOwnerDeletion already false")
	}
}
