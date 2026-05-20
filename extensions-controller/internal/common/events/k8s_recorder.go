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
	"errors"
	"fmt"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/kubernetes/scheme"
	typedcorev1 "k8s.io/client-go/kubernetes/typed/core/v1"
	"k8s.io/client-go/tools/record"
)

// k8sMultiEventRecorder fans out every event to all contained EventRecorders.
// Use NewMultiEventRecorder to construct one.
type k8sMultiEventRecorder struct {
	recorders []EventRecorder
}

// assert on EventRecorder interface
var _ EventRecorder = &k8sMultiEventRecorder{}

// NewMultiEventRecorder returns an EventRecorder that dispatches each event to
// all provided recorders.  Errors from individual recorders are joined and
// returned together so that a partial failure is still visible.
func NewMultiEventRecorder(recorders ...EventRecorder) EventRecorder {
	return &k8sMultiEventRecorder{recorders: recorders}
}

func (m *k8sMultiEventRecorder) Event(ctx context.Context, object runtime.Object, eventType, reason, message string) error {
	var errs []error
	for _, r := range m.recorders {
		if err := r.Event(ctx, object, eventType, reason, message); err != nil {
			errs = append(errs, err)
		}
	}
	return errors.Join(errs...)
}

func (m *k8sMultiEventRecorder) Eventf(ctx context.Context, object runtime.Object, eventType, reason, messageFmt string, args ...interface{}) error {
	return m.Event(ctx, object, eventType, reason, fmt.Sprintf(messageFmt, args...))
}

type k8sEventRecorder struct {
	recorder record.EventRecorder
}

// assert on EventRecorder interface
var _ EventRecorder = &k8sEventRecorder{}

// WithK8sEventRecorder creates a recorder that sends events to Kubernetes API
func WithK8sEventRecorder(client *kubernetes.Clientset, component string) RecorderOption {
	return RecorderOption{
		newRecorder: func() (EventRecorder, error) {
			return newK8sEventRecorder(client, component)
		},
	}
}

func newK8sEventRecorder(client *kubernetes.Clientset, component string) (EventRecorder, error) {
	eventBroadcaster := record.NewBroadcaster()
	eventBroadcaster.StartRecordingToSink(
		&typedcorev1.EventSinkImpl{
			Interface: client.CoreV1().Events(""),
		},
	)
	recorder := eventBroadcaster.NewRecorder(
		scheme.Scheme,
		corev1.EventSource{
			Component: component,
		},
	)

	return &k8sEventRecorder{
		recorder: recorder,
	}, nil
}

func (kr *k8sEventRecorder) Event(ctx context.Context, object runtime.Object, eventType, reason, message string) error {
	kr.recorder.Event(object, eventType, reason, message)
	return nil
}

func (kr *k8sEventRecorder) Eventf(ctx context.Context, object runtime.Object, eventType, reason, messageFmt string, args ...interface{}) error {
	message := fmt.Sprintf(messageFmt, args...)
	return kr.Event(ctx, object, eventType, reason, message)
}
