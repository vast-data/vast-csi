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

	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/kubernetes/scheme"
	typedcorev1 "k8s.io/client-go/kubernetes/typed/core/v1"
	"k8s.io/client-go/tools/record"
)

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
