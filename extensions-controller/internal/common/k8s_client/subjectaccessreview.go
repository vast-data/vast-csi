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

package k8s_client

import (
	"context"
	"fmt"

	authorizationv1 "k8s.io/api/authorization/v1"
)

// CreateSubjectAccessReview submits a SubjectAccessReview. On success, sar is
// updated in place with the API server's Status (including Allowed).
func (k *K8sClient) CreateSubjectAccessReview(ctx context.Context, sar *authorizationv1.SubjectAccessReview) error {
	if sar == nil {
		return fmt.Errorf("subject access review must not be nil")
	}
	if err := k.client.Create(ctx, sar); err != nil {
		return fmt.Errorf("create SubjectAccessReview: %w", err)
	}
	return nil
}
