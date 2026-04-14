package k8s_client

import (
	"context"
	"fmt"
	"strings"

	"github.com/vast-data/vast-csi/extensions-controller/internal/common"
	"go.uber.org/zap"
	corev1 "k8s.io/api/core/v1"
	storagev1 "k8s.io/api/storage/v1"
)

func (k *K8sClient) GetPVCClass(claim *corev1.PersistentVolumeClaim) (string, error) {
	if class, found := claim.Annotations[corev1.BetaStorageClassAnnotation]; found {
		return class, nil
	}

	if claim.Spec.StorageClassName != nil {
		return *claim.Spec.StorageClassName, nil
	}

	err := fmt.Errorf("Failed to get storageClass name from persistentVolumeClaim %s", claim.Name)
	return "", err
}

func (k *K8sClient) getStorageClassProvisioner(ctx context.Context, scName string) (string, error) {
	sc, err := k.GetStorageClass(ctx, scName)
	if err != nil {
		return "", err
	}
	return sc.Provisioner, nil
}

func (k *K8sClient) isSCHasParam(sc *storagev1.StorageClass, param string) bool {
	scParams := sc.Parameters
	_, ok := scParams[param]
	return ok
}

// GetStorageClass fetches a StorageClass by name.
// StorageClass is cluster-scoped, so namespace is not required.
func (k *K8sClient) GetStorageClass(ctx context.Context, scName string) (*storagev1.StorageClass, error) {
	sc := &storagev1.StorageClass{}
	// StorageClass is cluster-scoped, so namespace is empty
	if err := k.GetObject(ctx, scName, "", sc); err != nil {
		k.logger.Error("Failed to get storageClass", zap.Error(err), zap.String("storageClass", scName))
		return nil, err
	}
	return sc, nil
}

// GetStorageClasses fetches multiple StorageClasses by name in a single operation.
// Returns a map of StorageClass name to StorageClass object.
// If any StorageClass cannot be fetched, the error is returned and the map may be partially populated.
// StorageClasses are cluster-scoped, so namespace is not required.
func (k *K8sClient) GetStorageClasses(ctx context.Context, scNames []string) (map[string]*storagev1.StorageClass, error) {
	result := make(map[string]*storagev1.StorageClass, len(scNames))

	for _, scName := range scNames {
		scName = strings.TrimSpace(scName)
		if scName == "" {
			continue
		}

		sc, err := k.GetStorageClass(ctx, scName)
		if err != nil {
			return result, fmt.Errorf("failed to get StorageClass %q: %w", scName, err)
		}
		result[scName] = sc
	}

	return result, nil
}

// ExtractNonPrefixedParams returns only the parameters whose key does NOT
// start with prefix — i.e. the VAST-specific parameters such as subsystem,
// volume_group, vip_pool_name, etc. that have no CSI key prefix.
func (k *K8sClient) ExtractNonPrefixedParams(prefix string, params map[string]string) map[string]string {
	result := make(map[string]string)
	for key, val := range params {
		if !strings.HasPrefix(key, prefix) {
			result[key] = val
		}
	}
	return result
}

// ExtractPrefixedParams returns only the parameters whose key starts with
// prefix, with the prefix stripped from each key in the result.
// Use this to extract CSI-standard parameters from a StorageClass:
//
//	params := k.ExtractPrefixedParams("csi.storage.k8s.io/", sc.Parameters)
//	// "csi.storage.k8s.io/provisioner-secret-name" → "provisioner-secret-name"
//
// Non-prefixed parameters (e.g. vip_pool_name, subsystem) are excluded;
// read those directly from sc.Parameters.
func (k *K8sClient) ExtractPrefixedParams(prefix string, params map[string]string) map[string]string {
	result := make(map[string]string)
	for key, val := range params {
		if strings.HasPrefix(key, prefix) {
			result[strings.TrimPrefix(key, prefix)] = val
		}
	}
	return result
}

// ScsFromStorageClasses fetches the StorageClass object for each name and
// returns them keyed by StorageClass name.  It is the companion of
// RestFromStorageClasses and is used when callers need the StorageClass
func ScsFromStorageClasses(
	ctx context.Context,
	k8sClient *K8sClient,
	scNames []string,
) (map[string]*storagev1.StorageClass, error) {
	scByName := make(map[string]*storagev1.StorageClass, len(scNames))
	for _, scName := range scNames {
		sc, err := k8sClient.GetStorageClass(ctx, scName)
		if err != nil {
			return nil, fmt.Errorf("failed to get StorageClass %s: %w", scName, err)
		}
		scByName[scName] = sc
	}
	return scByName, nil
}

// IsBlockStorageClass reports whether sc is a VAST block StorageClass.
//
// A StorageClass is considered block when:
//   - it has a "subsystem" parameter, OR
//   - it has both "subsystem" and "root_export" AND its provisioner name starts
//     with "block".
func IsBlockStorageClass(sc *storagev1.StorageClass) bool {
	_, hasSubsystem := sc.Parameters[common.StorageClassParameterSubsystem]
	_, hasRootExport := sc.Parameters[common.StorageClassParameterRootExport]
	if hasSubsystem && hasRootExport {
		if strings.HasPrefix(sc.Provisioner, "block") {
			return true
		}
		return false
	}
	return hasSubsystem
}
