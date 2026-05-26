package vmsrest

import (
	"fmt"

	vast_client "github.com/vast-data/go-vast-client"
	"github.com/vast-data/go-vast-client/resources/typed"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/k8s_client"
	storagev1 "k8s.io/api/storage/v1"
)

// ResolveTenant determines the VAST tenant associated with a StorageClass.
//
// For block StorageClasses the "subsystem" parameter names the View to look up.
// If "tenant_name" is also present the tenant is returned directly by name,
// saving a round-trip.  Otherwise the tenant is resolved from the View's TenantId.
//
// For file StorageClasses the "view_policy" parameter names the ViewPolicy to
// look up.  The tenant is resolved from that policy's TenantId.
func ResolveTenant(
	rest *vast_client.TypedVMSRest,
	sc *storagev1.StorageClass,
) (*typed.TenantDetailsModel, error) {
	if k8s_client.IsBlockStorageClass(sc) {
		return resolveBlockTenant(rest, sc)
	}
	return resolveFileTenant(rest, sc)
}

func resolveBlockTenant(
	rest *vast_client.TypedVMSRest,
	sc *storagev1.StorageClass,
) (*typed.TenantDetailsModel, error) {
	subsystem := sc.Parameters[common.StorageClassParameterSubsystem]
	if subsystem == "" {
		return nil, fmt.Errorf("StorageClass %s is missing required parameter %q", sc.Name, common.StorageClassParameterSubsystem)
	}

	if tenantName := sc.Parameters["tenant_name"]; tenantName != "" {
		tenant, err := rest.Tenants.Get(&typed.TenantSearchParams{Name: tenantName})
		if err != nil {
			return nil, fmt.Errorf("failed to get tenant %q: %w", tenantName, err)
		}
		return tenant, nil
	}

	view, err := rest.Views.Get(&typed.ViewSearchParams{Name: subsystem})
	if err != nil {
		return nil, fmt.Errorf("failed to get view (subsystem) %q: %w", subsystem, err)
	}

	return resolveTenantById(rest, view.TenantId)
}

func resolveFileTenant(
	rest *vast_client.TypedVMSRest,
	sc *storagev1.StorageClass,
) (*typed.TenantDetailsModel, error) {
	viewPolicy := sc.Parameters["view_policy"]
	if viewPolicy == "" {
		return nil, fmt.Errorf("StorageClass %s is missing required parameter %q", sc.Name, "view_policy")
	}

	policy, err := GetViewPolicy(rest, viewPolicy)
	if err != nil {
		return nil, err
	}

	return resolveTenantById(rest, policy.TenantId)
}

// resolveTenantById returns the tenant for the given ID.
func resolveTenantById(rest *vast_client.TypedVMSRest, id int64) (*typed.TenantDetailsModel, error) {
	tenant, err := rest.Tenants.GetById(id)
	if err != nil {
		return nil, fmt.Errorf("failed to get tenant id=%d: %w", id, err)
	}
	return tenant, nil
}
