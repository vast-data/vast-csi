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

// Package logging provides the RainbowLogger — a per-request logger that
// stamps each log line with a unique, optionally coloured request ID so that
// all lines belonging to one request (reconcile loop, gRPC call, etc.) are
// visually correlated in dev-logging mode.
package logging

import (
	"fmt"
	"math"
	"math/rand"
	"sync/atomic"

	"go.uber.org/zap"
)

var rcIDCounter = rand.Uint32() % (uint32(math.MaxUint32/2) + 1)

// newRequestID returns a unique hex string for one request invocation.
func newRequestID() string {
	return fmt.Sprintf("0x%08x", atomic.AddUint32(&rcIDCounter, 1))
}

var devColorPalette = []func(string) string{
	ansiWrap("\033[35m"), // magenta
	ansiWrap("\033[36m"), // cyan
	ansiWrap("\033[90m"), // dark grey
	ansiWrap("\033[33m"), // yellow
	ansiWrap("\033[32m"), // green
	ansiWrap("\033[34m"), // blue
}

var colorCounter uint32

func ansiWrap(code string) func(string) string {
	return func(s string) string { return "| " + code + s + "\033[0m" + " |" }
}

// RainbowLogger produces per-request loggers stamped with a unique, optionally
// coloured ID.  Each RainbowLogger instance is assigned one color from the
// palette so that log lines from different controllers/services are visually
// distinct from one another in dev-logging mode.
type RainbowLogger struct {
	base    *zap.Logger
	colorID func(string) string
}

// New returns a RainbowLogger backed by base.  When devLogging is true each
// instance is assigned the next color from the palette; otherwise the ID is
// printed without color.
func New(base *zap.Logger, devLogging bool) *RainbowLogger {
	colorID := func(s string) string { return s }
	if devLogging {
		idx := atomic.AddUint32(&colorCounter, 1) - 1
		colorID = devColorPalette[idx%uint32(len(devColorPalette))]
	}
	return &RainbowLogger{base: base, colorID: colorID}
}

// For returns a logger scoped to a specific resource and stamped with a fresh,
// optionally coloured request ID in the name column.  All log lines produced
// by the returned logger (including REST interceptor lines) share the same ID,
// making it easy to correlate one request/reconcile loop in a busy log stream.
func (l *RainbowLogger) For(key, value string) *zap.Logger {
	return l.base.With(zap.String(key, value)).Named(l.colorID(newRequestID()))
}
