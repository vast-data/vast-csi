package vmsrest

import (
	"fmt"

	vast_client "github.com/vast-data/go-vast-client"
	"github.com/vast-data/go-vast-client/resources/typed"
)

// GetViewPolicy fetches a view policy by name (GET /viewpolicies/?name=…).
func GetViewPolicy(rest *vast_client.TypedVMSRest, policyName string) (*typed.ViewPolicyDetailsModel, error) {
	policy, err := rest.ViewPolicies.Get(&typed.ViewPolicySearchParams{Name: policyName})
	if err != nil {
		return nil, fmt.Errorf("get view policy %q: %w", policyName, err)
	}
	if policy.TenantId == 0 {
		return nil, fmt.Errorf(
			"view policy %q: tenant_id missing after decode (id=%d); check VMS response",
			policyName, policy.Id,
		)
	}
	return policy, nil
}
