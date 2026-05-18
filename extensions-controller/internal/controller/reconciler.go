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
	"context"
	"errors"
	"fmt"
	"time"

	cerrors "github.com/vast-data/vast-csi/extensions-controller/internal/common/errors"
	"go.uber.org/zap"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	ctrl "sigs.k8s.io/controller-runtime"

	"github.com/vast-data/vast-csi/extensions-controller/internal/common/backoff"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/config"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/events"
	k8sclient "github.com/vast-data/vast-csi/extensions-controller/internal/common/k8s_client"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/logging"
)

// BaseReconciler holds the shared dependencies for every controller.
type BaseReconciler struct {
	K8sClient     *k8sclient.K8sClient
	Log           *zap.Logger
	Config        *config.Config
	EventReporter *events.EventReporter
	Locker        *KeyLocker
	Rainbow       *logging.RainbowLogger
	Backoff       *backoff.Tracker
}

func NewBaseReconciler(
	mgr ctrl.Manager,
	k8sClient *k8sclient.K8sClient,
	log *zap.Logger,
	cfg *config.Config,
	controllerName string,
) (BaseReconciler, error) {
	reporter, err := events.NewEventReporterForManager(mgr, log, controllerName)
	if err != nil {
		return BaseReconciler{}, fmt.Errorf("failed to create event reporter for %s: %w", controllerName, err)
	}

	return BaseReconciler{
		K8sClient:     k8sClient,
		Log:           log,
		Config:        cfg,
		EventReporter: reporter,
		Locker:        NewKeyLocker(),
		Rainbow:       logging.New(log, cfg.DevLogging),
		Backoff:       backoff.New(10*time.Second, 1*time.Minute),
	}, nil
}

// LogFor returns a logger scoped to a specific resource and stamped with a
// fresh, optionally coloured reconcile ID in the name column, correlating all
// log lines (including REST interceptor lines) for one reconcile invocation.
func (b *BaseReconciler) LogFor(key, value string) *zap.Logger {
	return b.Rainbow.For(key, value)
}

// K8sFor returns a K8sClient that uses the given logger.
// Always pair this with LogFor() so that K8sClient log lines share the same
// reconcile ID as the rest of the reconcile loop.
func (b *BaseReconciler) K8sFor(log *zap.Logger) *k8sclient.K8sClient {
	return b.K8sClient.WithLogger(log)
}

func (b *BaseReconciler) EmitFor(ctx context.Context, log *zap.Logger, obj runtime.Object) *events.BoundReporter {
	return b.EventReporter.For(ctx, obj).WithLogger(log)
}

// BackoffFor returns a BoundBackoff with the given key pre-bound, mirroring
// the EmitFor / BoundReporter pattern so callers never pass the key explicitly.
func (b *BaseReconciler) BackoffFor(key types.NamespacedName) *backoff.BoundBackoff {
	return b.Backoff.For(key)
}

// maybeBackoffRetry translates a reconcile error into the appropriate
// ctrl.Result / error pair:
//
//   - nil error → (Result{}, nil): reconcile succeeded, no requeue needed.
//   - Retryable error with a specific RetryAfter delay → requeue after that
//     delay; the error is logged at Warn level and swallowed (nil returned to
//     controller-runtime so it does not increment the error counter).
//   - Retryable error without a delay → same as above, but the next
//     exponential-backoff interval from bo is used as the delay.
//   - Non-retryable error, bo non-nil → requeue after the next backoff
//     interval so transient infrastructure errors do not flood the work queue.
//   - Non-retryable error, bo nil → propagate the error to controller-runtime
//     for standard error handling (rate-limited retry + error metrics).
func (b *BaseReconciler) maybeBackoffRetry(bo *backoff.BoundBackoff, err error, log *zap.Logger) (ctrl.Result, error) {
	var retryable cerrors.Retryable
	if errors.As(err, &retryable) {
		var delay time.Duration
		delayPtr := retryable.RetryAfter()
		if delayPtr != nil {
			delay = *delayPtr
		} else {
			delay = bo.Next()
		}
		log.Info("requesting with backoff",
			zap.Duration("delay", delay), zap.Error(err))

		return ctrl.Result{RequeueAfter: delay}, nil

	}

	if err != nil && bo != nil {
		return ctrl.Result{RequeueAfter: bo.Next()}, nil
	}

	return ctrl.Result{}, err
}
