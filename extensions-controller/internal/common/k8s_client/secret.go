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

	corev1 "k8s.io/api/core/v1"
)

// GetSecret fetches a Kubernetes secret by name and namespace.
func (k *K8sClient) GetSecret(ctx context.Context, name, namespace string) (*corev1.Secret, error) {
	secret := &corev1.Secret{}
	if err := k.GetObject(ctx, name, namespace, secret); err != nil {
		return nil, fmt.Errorf("failed to get secret %s/%s: %w", namespace, name, err)
	}
	return secret, nil
}

// GetSecretValue fetches a specific value from a secret by name and namespace.
func (k *K8sClient) GetSecretValue(ctx context.Context, name, namespace, key string) (string, error) {
	secret, err := k.GetSecret(ctx, name, namespace)
	if err != nil {
		return "", err
	}

	value, ok := secret.Data[key]
	if !ok || len(value) == 0 {
		return "", fmt.Errorf("secret %s/%s is missing key '%s'", namespace, name, key)
	}

	return string(value), nil
}
