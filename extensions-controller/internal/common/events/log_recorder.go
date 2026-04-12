/*
Copyright 2025.

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

package events

import (
	"context"
	"fmt"

	"go.uber.org/zap"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
)

type logRecorder struct {
	logger *zap.Logger
}

// assert on EventRecorder interface
var _ EventRecorder = &logRecorder{}

// WithLogRecorder creates a recorder that logs events to stdout via zap logger
func WithLogRecorder(logger *zap.Logger) RecorderOption {
	return RecorderOption{
		newRecorder: func() (EventRecorder, error) {
			return &logRecorder{
				logger: logger,
			}, nil
		},
	}
}

func (lr *logRecorder) Event(ctx context.Context, object runtime.Object, eventType, reason, message string) error {
	// Extract object metadata
	obj, ok := object.(client.Object)
	if !ok {
		lr.logger.Warn("Cannot extract metadata from object", zap.String("type", fmt.Sprintf("%T", object)))
		return nil
	}

	name := obj.GetName()
	namespace := obj.GetNamespace()
	kind := obj.GetObjectKind().GroupVersionKind().Kind

	// Log at appropriate level based on event type
	switch eventType {
	case corev1.EventTypeWarning:
		lr.logger.Warn("Event",
			zap.String("type", eventType),
			zap.String("kind", kind),
			zap.String("namespace", namespace),
			zap.String("name", name),
			zap.String("reason", reason),
			zap.String("message", message))
	case corev1.EventTypeNormal:
		lr.logger.Info("Event",
			zap.String("type", eventType),
			zap.String("kind", kind),
			zap.String("namespace", namespace),
			zap.String("name", name),
			zap.String("reason", reason),
			zap.String("message", message))
	default:
		lr.logger.Info("Event",
			zap.String("type", eventType),
			zap.String("kind", kind),
			zap.String("namespace", namespace),
			zap.String("name", name),
			zap.String("reason", reason),
			zap.String("message", message))
	}

	return nil
}

func (lr *logRecorder) Eventf(ctx context.Context, object runtime.Object, eventType, reason, messageFmt string, args ...interface{}) error {
	message := fmt.Sprintf(messageFmt, args...)
	return lr.Event(ctx, object, eventType, reason, message)
}
