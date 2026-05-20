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
	"k8s.io/client-go/kubernetes"
	ctrl "sigs.k8s.io/controller-runtime"
)

// Event types (aligned with Kubernetes event types)
const (
	EventTypeNormal  = corev1.EventTypeNormal
	EventTypeWarning = corev1.EventTypeWarning
)

// EventReporter aggregates multiple EventRecorders and reports to all of them
type EventReporter struct {
	recorders []EventRecorder
}

// NewEventReporter creates a new EventReporter with the given recorder options
func NewEventReporter(recorderOptions []RecorderOption) (*EventReporter, error) {
	recorders := make([]EventRecorder, len(recorderOptions))
	for i, opt := range recorderOptions {
		rec, err := opt.newRecorder()
		if err != nil {
			return nil, fmt.Errorf("failed to create recorder: %w", err)
		}
		recorders[i] = rec
	}

	return &EventReporter{
		recorders: recorders,
	}, nil
}

// NewEventReporterForManager creates an EventReporter with K8s and log recorders
// This is the recommended way to create an EventReporter for use in controllers
func NewEventReporterForManager(mgr ctrl.Manager, logger *zap.Logger, component string) (*EventReporter, error) {
	// Get the Kubernetes clientset from the manager
	k8sClient, err := kubernetes.NewForConfig(mgr.GetConfig())
	if err != nil {
		return nil, fmt.Errorf("failed to create Kubernetes client: %w", err)
	}

	// Create event reporter with both K8s and log recorders
	recorderOptions := []RecorderOption{
		WithK8sEventRecorder(k8sClient, component),
		WithLogRecorder(logger),
	}

	return NewEventReporter(recorderOptions)
}

// Event records an event for the given object using all configured recorders
func (er *EventReporter) Event(ctx context.Context, object runtime.Object, eventType, reason, message string) {
	for _, recorder := range er.recorders {
		if err := recorder.Event(ctx, object, eventType, reason, message); err != nil {
			fmt.Printf("failed to record event: %v\n", err)
		}
	}
}

// eventK8sOnly records a Kubernetes event for object but skips any logRecorder
// so that the event is visible on the K8s object without producing a duplicate
// log line (used for propagation to bound parent objects).
func (er *EventReporter) eventK8sOnly(ctx context.Context, object runtime.Object, eventType, reason, message string) {
	for _, recorder := range er.recorders {
		if _, ok := recorder.(*logRecorder); ok {
			continue
		}
		if err := recorder.Event(ctx, object, eventType, reason, message); err != nil {
			fmt.Printf("failed to record event: %v\n", err)
		}
	}
}

// Eventf records an event with formatted message using all configured recorders
func (er *EventReporter) Eventf(ctx context.Context, object runtime.Object, eventType, reason, messageFmt string, args ...interface{}) {
	message := fmt.Sprintf(messageFmt, args...)
	er.Event(ctx, object, eventType, reason, message)
}

func (er *EventReporter) EventfReason(ctx context.Context, object runtime.Object, reason string) func(string, string, ...interface{}) {
	return func(eventType string, messageFmt string, args ...interface{}) {
		er.Eventf(ctx, object, eventType, reason, messageFmt, args...)
	}
}

// Logger returns the underlying *zap.Logger from the first log recorder found in
// the reporter, or a no-op logger if none is configured.  This allows code that
// receives a BoundReporter to still perform structured zap logging without
// keeping a separate logger reference.
func (er *EventReporter) Logger() *zap.Logger {
	for _, rec := range er.recorders {
		if lr, ok := rec.(*logRecorder); ok {
			return lr.logger
		}
	}
	return zap.NewNop()
}

// withLogger returns a shallow copy of the EventReporter where the logRecorder
// is replaced with one using l.  All other recorders (e.g. the K8s recorder)
// are reused as-is.
func (er *EventReporter) withLogger(l *zap.Logger) *EventReporter {
	newRecorders := make([]EventRecorder, len(er.recorders))
	for i, rec := range er.recorders {
		if _, ok := rec.(*logRecorder); ok {
			newRecorders[i] = &logRecorder{logger: l}
		} else {
			newRecorders[i] = rec
		}
	}
	return &EventReporter{recorders: newRecorders}
}

// For creates a BoundReporter that binds context and object for cleaner event emission.
// Usage:
//
//	emit := r.EventReporter.For(ctx, node)
//	emit.Warning(events.ReasonNodeValidationFailed, "Validation failed: %v", err)
//	emit.Normal(events.ReasonNodeScheduled, "Node scheduled successfully")
func (er *EventReporter) For(ctx context.Context, object runtime.Object) *BoundReporter {
	return &BoundReporter{er: er, ctx: ctx, objects: []runtime.Object{object}}
}

// BoundReporter is an EventReporter with context and one-or-more objects
// pre-bound for convenience.  Every event is dispatched to all bound objects.
//
// Use Bind to add additional propagation targets (e.g. a parent VVR/VSCR so
// that events emitted on a VastReplicationContent are also visible on the
// owning parent resource).
type BoundReporter struct {
	er      *EventReporter
	ctx     context.Context
	objects []runtime.Object
	warned  bool
}

// Logger returns the underlying *zap.Logger from the parent EventReporter.
// Useful when detailed structured logging is needed alongside event emission.
func (br *BoundReporter) Logger() *zap.Logger {
	return br.er.Logger()
}

// WithLogger returns a new BoundReporter whose log recorder uses l.
// Use this after the concrete provisioner type is known (e.g. in setProvisioner)
// so that all event log lines carry the provisioner context in the logger field.
func (br *BoundReporter) WithLogger(l *zap.Logger) *BoundReporter {
	return &BoundReporter{
		er:      br.er.withLogger(l),
		ctx:     br.ctx,
		objects: br.objects,
	}
}

// Bind returns a new BoundReporter that propagates every event to parent in
// addition to all already-bound objects.  Use this to mirror events emitted
// on a child resource (e.g. VastReplicationContent) onto its parent (VVR/VSCR)
// so that the parent's event stream also reflects child activity.
func (br *BoundReporter) Bind(parent runtime.Object) *BoundReporter {
	newObjects := make([]runtime.Object, len(br.objects), len(br.objects)+1)
	copy(newObjects, br.objects)
	newObjects = append(newObjects, parent)
	return &BoundReporter{
		er:      br.er,
		ctx:     br.ctx,
		objects: newObjects,
	}
}

// Event records an event with the given type, reason, and message.
// The primary (first) object receives a full emit — both a Kubernetes Event
// and a log line.  Every additional bound object (e.g. a parent VVR/VSCR)
// receives only the Kubernetes Event so that the log is not duplicated.
func (br *BoundReporter) Event(eventType, reason, message string) {
	if len(br.objects) == 0 {
		return
	}
	br.er.Event(br.ctx, br.objects[0], eventType, reason, message)
	for _, obj := range br.objects[1:] {
		br.er.eventK8sOnly(br.ctx, obj, eventType, reason, message)
	}
}

// Eventf records an event with the given type, reason, and formatted message
// on all bound objects.
func (br *BoundReporter) Eventf(eventType, reason, messageFmt string, args ...interface{}) {
	message := fmt.Sprintf(messageFmt, args...)
	br.Event(eventType, reason, message)
}

// Warning records a warning event with the given reason and message.
func (br *BoundReporter) Warning(reason, message string) {
	br.warned = true
	br.Event(EventTypeWarning, reason, message)
}

// Warningf records a warning event with the given reason and formatted message.
func (br *BoundReporter) Warningf(reason, messageFmt string, args ...interface{}) {
	br.warned = true
	br.Event(EventTypeWarning, reason, fmt.Sprintf(messageFmt, args...))
}

// HasWarned reports whether a Warning event has been emitted through this
// reporter during the current reconcile.
func (br *BoundReporter) HasWarned() bool {
	return br.warned
}

// Normal records a normal event with the given reason and message on all
// bound objects.
func (br *BoundReporter) Normal(reason, message string) {
	br.Event(EventTypeNormal, reason, message)
}

// Normalf records a normal event with the given reason and formatted message
// on all bound objects.
func (br *BoundReporter) Normalf(reason, messageFmt string, args ...interface{}) {
	br.Event(EventTypeNormal, reason, fmt.Sprintf(messageFmt, args...))
}
