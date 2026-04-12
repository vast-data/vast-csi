package vmsrest

import (
	"fmt"
	"strings"

	vast_client "github.com/vast-data/go-vast-client"
	"github.com/vast-data/go-vast-client/core"
	"github.com/vast-data/go-vast-client/resources/typed"
	storagev1 "k8s.io/api/storage/v1"
)

// ResolveTenantFromVipPool looks up the VIP pool referenced by sc
// (via "vip_pool_name" or "vip_pool_fqdn" parameters), reads its TenantId,
// and returns the matching tenant's GUID.
//
// When TenantId is 0 (unset) the GUID of the tenant named "default" is
// returned.
func ResolveTenantFromVipPool(
	rest *vast_client.TypedVMSRest,
	sc *storagev1.StorageClass,
) (*typed.TenantDetailsModel, error) {
	vipPoolName := sc.Parameters["vip_pool_name"]
	vipPoolFqdn := sc.Parameters["vip_pool_fqdn"]

	var vipPool *typed.VipPoolDetailsModel
	var err error

	switch {
	case vipPoolName != "":
		vipPool, err = rest.VipPools.Get(&typed.VipPoolSearchParams{Name: vipPoolName})
		if err != nil {
			return nil, fmt.Errorf("failed to get VIP pool by name %q: %w", vipPoolName, err)
		}

	case vipPoolFqdn != "":
		// FQDN may be of the form "vippool-1.cluster.domain.lab" — only the
		// first label before the first dot is the pool's domain_name.
		domainName := strings.SplitN(vipPoolFqdn, ".", 2)[0]
		vipPool, err = rest.VipPools.Get(&typed.VipPoolSearchParams{
			RawData: core.Params{"domain_name": domainName},
		})
		if err != nil {
			return nil, fmt.Errorf("failed to get VIP pool by FQDN domain %q (fqdn=%s): %w",
				domainName, vipPoolFqdn, err)
		}

	default:
		return nil, fmt.Errorf("StorageClass %s has neither vip_pool_name nor vip_pool_fqdn parameter", sc.Name)
	}

	if vipPool.TenantId == 0 {
		tenant, err := rest.Tenants.Get(&typed.TenantSearchParams{Name: "default"})
		if err != nil {
			return nil, fmt.Errorf("failed to get default tenant: %w", err)
		}
		return tenant, nil
	}

	tenant, err := rest.Tenants.GetById(vipPool.TenantId)
	if err != nil {
		return nil, fmt.Errorf("failed to get tenant id=%d: %w", vipPool.TenantId, err)
	}
	return tenant, nil
}
