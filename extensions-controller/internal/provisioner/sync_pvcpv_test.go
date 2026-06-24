// Package provisioner tests verify the SyncPVCPV guard behaviour:
//
//   - When SyncPVCPV=true and CleanVolumeCb is called, no VAST REST calls are
//     made (early return).  A nil sibRest / sibSc is passed on purpose to
//     prove that the function never dereferences them.
//
//   - When syncFileObjects / syncBlockObjects is called with syncPVCPV=true
//     and a non-empty toDelete list, the delete loop is skipped.  Again a nil
//     sibRest is intentionally passed to confirm no REST calls occur.
//
//   - When SyncPVCPV=false and CleanVolumeCb is called, the function proceeds
//     past the guard and eventually attempts VAST REST calls.  We verify this
//     by checking the error that comes back from the first REST call against a
//     nil client (nil-pointer panic would mean we called before the guard).
package provisioner

import (
	"context"
	"testing"

	vastv1alpha1 "github.com/vast-data/vast-csi/extensions-controller/api/v1alpha1"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/k8s_client"
	"go.uber.org/zap"
	storagev1 "k8s.io/api/storage/v1"
)

// minimalFileProvisioner builds a FileProvisioner with only the fields that
// the SyncPVCPV-guard code paths read.
func minimalFileProvisioner(vrc *vastv1alpha1.VastReplicationContent) *FileProvisioner {
	base := &baseProvisioner{
		rp:        vrc,
		logger:    zap.NewNop(),
		k8sClient: k8s_client.NewK8sClient(nil, zap.NewNop()),
	}
	fp := &FileProvisioner{baseProvisioner: base}
	base.setProvisioner(fp)
	return fp
}

// minimalBlockProvisioner builds a BlockProvisioner with only the fields that
// the SyncPVCPV-guard code paths read.
func minimalBlockProvisioner(vrc *vastv1alpha1.VastReplicationContent) *BlockProvisioner {
	base := &baseProvisioner{
		rp:        vrc,
		logger:    zap.NewNop(),
		k8sClient: k8s_client.NewK8sClient(nil, zap.NewNop()),
	}
	bp := &BlockProvisioner{baseProvisioner: base}
	base.setProvisioner(bp)
	return bp
}

// emptyStorageClass returns a StorageClass with an initialised (empty) Parameters
// map so that ExtractNonPrefixedParams does not panic.
func emptyStorageClass() *storagev1.StorageClass {
	return &storagev1.StorageClass{Parameters: map[string]string{}}
}

// ---------------------------------------------------------------------------
// FileProvisioner tests
// ---------------------------------------------------------------------------

// TestFileCleanVolumeCb_SyncPVCPV_True_IsNoop asserts that CleanVolumeCb
// returns nil without touching sibRest or sibSc when SyncPVCPV=true.
// The nil sibRest is intentional: any inadvertent dereference would panic.
func TestFileCleanVolumeCb_SyncPVCPV_True_IsNoop(t *testing.T) {
	vrc := &vastv1alpha1.VastReplicationContent{}
	vrc.Spec.SyncPVCPV = true

	fp := minimalFileProvisioner(vrc)
	err := fp.CleanVolumeCb(context.Background(), vrc, nil /*sibRest*/, nil /*sibSc*/)
	if err != nil {
		t.Fatalf("CleanVolumeCb(SyncPVCPV=true) returned unexpected error: %v", err)
	}
}

// TestFileSyncFileObjects_SyncPVCPV_True_SkipsToDelete asserts that
// syncFileObjects does not attempt any VAST delete calls when syncPVCPV=true,
// even when toDelete is non-empty.
// sibRest is nil on purpose: a panic here means the guard is missing.
func TestFileSyncFileObjects_SyncPVCPV_True_SkipsToDelete(t *testing.T) {
	vrc := &vastv1alpha1.VastReplicationContent{}
	vrc.Spec.SyncPVCPV = true

	fp := minimalFileProvisioner(vrc)
	toDelete := vastv1alpha1.PVCList{"pvc-1", "pvc-2"}
	err := fp.syncFileObjects(context.Background(), nil /*sibRest*/, emptyStorageClass(), true /*syncPVCPV*/, nil /*toEnsure*/, toDelete)
	if err != nil {
		t.Fatalf("syncFileObjects(syncPVCPV=true) returned unexpected error: %v", err)
	}
}

// TestFileCleanVolumeCb_SyncPVCPV_False_ProceedsToVAST asserts that
// CleanVolumeCb proceeds past the SyncPVCPV guard when SyncPVCPV=false
// and attempts to make VAST REST / K8s calls.  With a nil K8s client it will
// return a non-nil error originating from shouldRetainDestVolumes; this
// confirms the guard was NOT triggered and the function reached live code.
func TestFileCleanVolumeCb_SyncPVCPV_False_ProceedsToVAST(t *testing.T) {
	vrc := &vastv1alpha1.VastReplicationContent{}
	vrc.Spec.SyncPVCPV = false

	fp := minimalFileProvisioner(vrc)
	err := fp.CleanVolumeCb(context.Background(), vrc, nil /*sibRest*/, nil /*sibSc*/)
	// A nil error here would mean the function returned early via the
	// SyncPVCPV guard or via shouldRetainDestVolumes's retain path — both
	// of which require a working K8s client.  With no client we expect a
	// non-nil error confirming the function attempted to proceed.
	if err == nil {
		t.Fatal("CleanVolumeCb(SyncPVCPV=false) should have proceeded past the guard and returned an error from the nil K8s client, but returned nil")
	}
	t.Logf("got expected error (confirms guard bypassed): %v", err)
}

// ---------------------------------------------------------------------------
// BlockProvisioner tests
// ---------------------------------------------------------------------------

// TestBlockCleanVolumeCb_SyncPVCPV_True_IsNoop asserts the same early-return
// behaviour for the block provisioner.
func TestBlockCleanVolumeCb_SyncPVCPV_True_IsNoop(t *testing.T) {
	vrc := &vastv1alpha1.VastReplicationContent{}
	vrc.Spec.SyncPVCPV = true

	bp := minimalBlockProvisioner(vrc)
	err := bp.CleanVolumeCb(context.Background(), vrc, nil /*sibRest*/, nil /*sibSc*/)
	if err != nil {
		t.Fatalf("BlockProvisioner.CleanVolumeCb(SyncPVCPV=true) returned unexpected error: %v", err)
	}
}

// TestBlockSyncBlockObjects_SyncPVCPV_True_SkipsToDelete asserts that
// syncBlockObjects does not attempt any VAST delete calls when
// sibVRC.Spec.SyncPVCPV=true and toEnsure is empty.
func TestBlockSyncBlockObjects_SyncPVCPV_True_SkipsToDelete(t *testing.T) {
	vrc := &vastv1alpha1.VastReplicationContent{}
	vrc.Spec.SyncPVCPV = true

	bp := minimalBlockProvisioner(vrc)
	toDelete := vastv1alpha1.PVCList{"pvc-1", "pvc-2"}
	err := bp.syncBlockObjects(
		context.Background(),
		nil, /*sibRest – intentionally nil: must not be dereferenced*/
		emptyStorageClass(),
		vrc, /*sibVRC with SyncPVCPV=true*/
		nil, /*ppath – not needed when toEnsure is empty*/
		nil, /*toEnsure – empty*/
		toDelete,
	)
	if err != nil {
		t.Fatalf("syncBlockObjects(syncPVCPV=true) returned unexpected error: %v", err)
	}
}

// TestBlockCleanVolumeCb_SyncPVCPV_False_ProceedsToVAST is the block-side
// equivalent of the file test: confirms the function proceeds past the guard.
func TestBlockCleanVolumeCb_SyncPVCPV_False_ProceedsToVAST(t *testing.T) {
	vrc := &vastv1alpha1.VastReplicationContent{}
	vrc.Spec.SyncPVCPV = false

	bp := minimalBlockProvisioner(vrc)
	err := bp.CleanVolumeCb(context.Background(), vrc, nil /*sibRest*/, nil /*sibSc*/)
	if err == nil {
		t.Fatal("BlockProvisioner.CleanVolumeCb(SyncPVCPV=false) should have proceeded past the guard and returned an error from the nil K8s client, but returned nil")
	}
	t.Logf("got expected error (confirms guard bypassed): %v", err)
}
