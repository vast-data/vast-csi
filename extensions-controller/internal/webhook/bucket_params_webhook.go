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

package webhook

import (
	"context"
	"encoding/json"
	"fmt"
	"maps"
	"net/http"

	"github.com/vast-data/vast-csi/extensions-controller/internal/common/cosi"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/logging"
	"go.uber.org/zap"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/types"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/webhook/admission"
	objectstoragev1alpha1 "sigs.k8s.io/container-object-storage-interface/client/apis/objectstorage/v1alpha1"
)

const bucketParamsWebhookPath = "/mutate-bucket-parameters"

// BucketParamsInjector merges BucketClaim cosi.vastdata.com/* annotations into Bucket.spec.parameters.
type BucketParamsInjector struct {
	Client     client.Client
	Decoder    admission.Decoder
	Rainbow    *logging.RainbowLogger
	DriverName string
}

func (b *BucketParamsInjector) Handle(ctx context.Context, req admission.Request) admission.Response {
	log := b.Rainbow.For("bucket", req.Namespace+"/"+req.Name)

	bucket := &objectstoragev1alpha1.Bucket{}
	if err := b.Decoder.Decode(req, bucket); err != nil {
		log.Error("failed to decode Bucket", zap.Error(err))
		return admission.Errored(http.StatusBadRequest, err)
	}

	if bucket.Spec.DriverName == "" {
		return admission.Allowed("no driverName")
	}
	if bucket.Spec.DriverName != b.DriverName {
		return admission.Allowed("not a VAST COSI bucket")
	}

	if bucket.Spec.BucketClaim == nil {
		return admission.Allowed("no bucketClaim reference")
	}

	claim := &objectstoragev1alpha1.BucketClaim{}
	claimKey := types.NamespacedName{
		Namespace: bucket.Spec.BucketClaim.Namespace,
		Name:      bucket.Spec.BucketClaim.Name,
	}
	if claimKey.Namespace == "" {
		claimKey.Namespace = req.Namespace
	}
	if err := b.Client.Get(ctx, claimKey, claim); err != nil {
		if apierrors.IsNotFound(err) {
			return admission.Denied(fmt.Sprintf("BucketClaim %q not found", claimKey))
		}
		log.Error("failed to get BucketClaim", zap.String("claim", claimKey.String()), zap.Error(err))
		return admission.Errored(http.StatusInternalServerError, err)
	}

	claimParams := cosi.ParamsFromClaimAnnotations(claim.GetAnnotations())
	if len(claimParams) == 0 {
		return admission.Allowed("no cosi claim parameters")
	}

	merged := cosi.MergeParameters(bucket.Spec.Parameters, claimParams)
	if maps.Equal(bucket.Spec.Parameters, merged) {
		return admission.Allowed("parameters unchanged")
	}

	bucket.Spec.Parameters = merged
	modified, err := json.Marshal(bucket)
	if err != nil {
		log.Error("failed to marshal Bucket", zap.Error(err))
		return admission.Errored(http.StatusInternalServerError, err)
	}

	return admission.PatchResponseFromRaw(req.Object.Raw, modified)
}

// SetupBucketParamsWebhook registers the Bucket parameter merge webhook.
func SetupBucketParamsWebhook(mgr ctrl.Manager, rainbow *logging.RainbowLogger, driverName string) error {
	if driverName == "" {
		driverName = cosi.VastCOSIDriverName
	}
	decoder := admission.NewDecoder(mgr.GetScheme())
	mgr.GetWebhookServer().Register(bucketParamsWebhookPath, &admission.Webhook{
		Handler: &BucketParamsInjector{
			Client:     mgr.GetClient(),
			Decoder:    decoder,
			Rainbow:    rainbow,
			DriverName: driverName,
		},
	})
	return nil
}
