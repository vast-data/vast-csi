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

package vmsrest

import (
	"context"
	"fmt"
	"io"
	"net/http"

	vast_client "github.com/vast-data/go-vast-client"
	"go.uber.org/zap"
	corev1 "k8s.io/api/core/v1"
	storagev1 "k8s.io/api/storage/v1"

	replicationv1alpha1 "github.com/csi-addons/kubernetes-csi-addons/api/replication.storage/v1alpha1"
	vastv1alpha1 "github.com/vast-data/vast-csi/extensions-controller/api/v1alpha1"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/k8s_client"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/version"
)

// New creates a VMS REST client with logging hooks and sets a request-ID on the context.
func New(
	ctx context.Context,
	username string,
	password string,
	endpoint string,
	tenant string,
	token string,
	sslVerify bool,
	l *zap.Logger,
) (*vast_client.TypedVMSRest, error) {
	config := &vast_client.VMSConfig{
		ApiVersion: "latest",
		Host:       endpoint,
		Username:   username,
		Password:   password,
		Tenant:     tenant,
		ApiToken:   token,
		SslVerify:  sslVerify,
		UserAgent:  getUserAgent(version.Version),
		BeforeRequestFn: func(ctx context.Context, r *http.Request, verb, url string, body io.Reader) error {
			return BeforeRequestFnCallback(ctx, r, verb, url, body, l)
		},
		AfterRequestFn: func(ctx context.Context, response vast_client.Renderable) (vast_client.Renderable, error) {
			return AfterRequestFnCallback(ctx, response, l)
		},
	}
	rest, err := vast_client.NewTypedVMSRest(config)
	if err != nil {
		return nil, err
	}
	rest.SetCtx(ctx)
	return rest, nil
}

// NewFromStorageClass builds a go-vast-client by reading the CSI provisioner
// secret referenced in the StorageClass parameters.
func NewFromStorageClass(ctx context.Context, k8sClient *k8s_client.K8sClient, sc *storagev1.StorageClass, sslVerify bool, logger *zap.Logger) (*vast_client.TypedVMSRest, error) {
	// Get CSI-prefixed parameters with prefix stripped
	csiParams := k8sClient.ExtractPrefixedParams(common.CSIParameterPrefix, sc.Parameters)

	secretName := csiParams["provisioner-secret-name"]
	secretNamespace := csiParams["provisioner-secret-namespace"]
	if secretName == "" {
		return nil, fmt.Errorf("StorageClass %s missing parameter %s", sc.Name, "provisioner-secret-name")
	}
	if secretNamespace == "" {
		return nil, fmt.Errorf("StorageClass %s missing parameter %s", sc.Name, "provisioner-secret-namespace")
	}

	secret, err := k8sClient.GetSecret(ctx, secretName, secretNamespace)
	if err != nil {
		return nil, fmt.Errorf("failed to get secret %s/%s: %w", secretNamespace, secretName, err)
	}

	return NewFromSecretData(ctx, secret.Data, sslVerify, logger)
}

// NewFromStorageClassName fetches the named StorageClass, builds a
// TypedVMSRest client from its provisioner secret, and sets a request-ID on
// the context.  Both the client and the StorageClass are returned so callers
// can read StorageClass parameters after the call without a second API round-trip.
func NewFromStorageClassName(
	ctx context.Context,
	k8sClient *k8s_client.K8sClient,
	scName string,
	sslVerify bool,
	logger *zap.Logger,
) (*vast_client.TypedVMSRest, *storagev1.StorageClass, error) {
	sc, err := k8sClient.GetStorageClass(ctx, scName)
	if err != nil {
		return nil, nil, fmt.Errorf("failed to get StorageClass %s: %w", scName, err)
	}
	rest, err := NewFromStorageClass(ctx, k8sClient, sc, sslVerify, logger)
	if err != nil {
		return nil, nil, err
	}
	return rest, sc, nil
}

// NewFromVastReplicationContent builds a TypedVMSRest client and returns the
// StorageClass for the VastReplicationContent's Spec.StorageClass field.
// It is a thin wrapper around NewFromStorageClassName.
func NewFromVastReplicationContent(
	ctx context.Context,
	k8sClient *k8s_client.K8sClient,
	rp *vastv1alpha1.VastReplicationContent,
	sslVerify bool,
	logger *zap.Logger,
) (*vast_client.TypedVMSRest, *storagev1.StorageClass, error) {
	return NewFromStorageClassName(ctx, k8sClient, rp.Spec.StorageClass, sslVerify, logger)
}

// NewFromPVC builds a TypedVMSRest client using the StorageClass referenced by the PVC.
// It internally calls NewFromStorageClass and sets request-id context for REST logging.
func NewFromPVC(ctx context.Context, k8sClient *k8s_client.K8sClient, pvc *corev1.PersistentVolumeClaim, sslVerify bool, logger *zap.Logger) (*vast_client.TypedVMSRest, error) {
	scName, err := k8sClient.GetPVCClass(pvc)
	if err != nil {
		return nil, fmt.Errorf("failed to get PVC class %s: %w", pvc.Name, err)
	}

	destSC, err := k8sClient.GetStorageClass(ctx, scName)
	if err != nil {
		return nil, fmt.Errorf("failed to get StorageClass %s: %w", scName, err)
	}

	return NewFromStorageClass(ctx, k8sClient, destSC, sslVerify, logger)
}

// NewFromReplicationClass builds a TypedVMSRest client from the Kubernetes
// Secret referenced in a VolumeReplicationClass's parameters.
func NewFromReplicationClass(
	ctx context.Context,
	k8sClient *k8s_client.K8sClient,
	vrc *replicationv1alpha1.VolumeReplicationClass,
	sslVerify bool,
	logger *zap.Logger,
) (*vast_client.TypedVMSRest, error) {
	secretName := vrc.Spec.Parameters[common.CSIAddonsParamReplicationSecretName]
	secretNamespace := vrc.Spec.Parameters[common.CSIAddonsParamReplicationSecretNamespace]
	if secretName == "" {
		return nil, fmt.Errorf("VolumeReplicationClass %s missing parameter %s", vrc.Name, common.CSIAddonsParamReplicationSecretName)
	}
	if secretNamespace == "" {
		return nil, fmt.Errorf("VolumeReplicationClass %s missing parameter %s", vrc.Name, common.CSIAddonsParamReplicationSecretNamespace)
	}
	secret, err := k8sClient.GetSecret(ctx, secretName, secretNamespace)
	if err != nil {
		return nil, fmt.Errorf("failed to get secret %s/%s for VolumeReplicationClass %s: %w", secretNamespace, secretName, vrc.Name, err)
	}
	return NewFromSecretData(ctx, secret.Data, sslVerify, logger)
}

// RestFromStorageClasses constructs one TypedVMSRest client per StorageClass
// name and returns them keyed by StorageClass name.
func RestFromStorageClasses(
	ctx context.Context,
	k8sClient *k8s_client.K8sClient,
	scNames []string,
	sslVerify bool,
	logger *zap.Logger,
) (map[string]*vast_client.TypedVMSRest, error) {
	restByStorageClass := make(map[string]*vast_client.TypedVMSRest, len(scNames))
	for _, scName := range scNames {
		sc, err := k8sClient.GetStorageClass(ctx, scName)
		if err != nil {
			return nil, fmt.Errorf("failed to get StorageClass %s: %w", scName, err)
		}
		rest, err := NewFromStorageClass(ctx, k8sClient, sc, sslVerify, logger)
		if err != nil {
			return nil, fmt.Errorf("failed to build VMS REST client for SC %s: %w", scName, err)
		}
		restByStorageClass[scName] = rest
	}
	return restByStorageClass, nil
}

// NewFromSecretData creates a TypedVMSRest client from Kubernetes Secret data.
func NewFromSecretData(ctx context.Context, secretData map[string][]byte, sslVerify bool, logger *zap.Logger) (*vast_client.TypedVMSRest, error) {
	username := string(secretData["username"])
	password := string(secretData["password"])
	token := string(secretData["token"])
	tenant := string(secretData["tenant"])
	endpoint := string(secretData["endpoint"])

	if endpoint == "" {
		return nil, fmt.Errorf("secret is missing required key 'endpoint'")
	}

	hasUserPass := username != "" && password != ""
	hasToken := token != ""
	if !hasUserPass && !hasToken {
		return nil, fmt.Errorf("secret must contain either 'username'+'password' or 'token' for authentication")
	}

	return New(ctx, username, password, endpoint, tenant, token, sslVerify, logger)
}
