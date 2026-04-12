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

package config

import (
	"fmt"
	"reflect"
	"strings"
)

// Config holds all CLI flags and configuration values.
// It is a singleton that should be initialized once during application startup.
// The structure aligns with the Helm values structure in charts/vastcsi/values.yaml
//
// Fields are tagged with component:"<name>" to indicate which subcommand owns
// them.  Display(component) uses this tag to filter the output.
type Config struct {
	// PVC Label Injection Webhook
	//
	// PvcLabelWebhookEnabled is set by the --enable-pvc-label-webhook CLI flag.
	// The Helm chart forwards extensions.webhook.disablePvcLabelsWebhook as this
	// flag: when disablePvcLabelsWebhook is false (the default), --enable-pvc-label-webhook
	// is passed to the process, enabling label injection.  When true the flag is
	// omitted and only replication CRD validation webhooks remain active.
	PvcLabelWebhookEnabled bool   `component:"pvc-label-webhook"`
	WebhookCertPath        string `component:"pvc-label-webhook"`
	WebhookCertName        string `component:"pvc-label-webhook"`
	WebhookCertKey         string `component:"pvc-label-webhook"`
	StorageClassName       string `component:"pvc-label-webhook"`
	StorageClassNameRegex  string `component:"pvc-label-webhook"`
	PVCNameRegex           string `component:"pvc-label-webhook"`
	CSIDriverName          string `component:"pvc-label-webhook"`

	// Format strings for replication resources
	PVCNameFormat                    string `component:"replication"`
	PVNameFormat                     string `component:"replication"`
	VolumeReplicationNameFormat      string `component:"replication"`
	VolumeGroupReplicationNameFormat string `component:"replication"`

	// SSL verification for VAST REST API calls (replication only)
	SSLVerify bool `component:"replication"`

	// Shared manager configuration (always displayed)
	HealthProbeBindAddress string
	MetricsBindAddress     string
	EnableHTTP2            bool
	// DevLogging enables human-readable console logging instead of JSON.
	// Use during development / debugging; leave false in production.
	DevLogging bool
}

// Display prints the configuration in an aligned key-value format.
//
// component filters which fields are shown:
//   - "pvc-label-webhook" → only fields whose component tag contains "pvc-label-webhook"
//   - "replication"       → only fields whose component tag contains "replication"
//
// The component struct tag may list multiple values separated by commas, e.g.
// `component:"pvc-label-webhook,replication"` — such a field is included
// whenever the requested component matches any of the listed values.
//
// Fields with no component tag are only shown when component is "".
//
// Example output:
//
//   - key:    value
//   - key2:   value2
func (c *Config) Display(component string) string {
	if c == nil {
		return "Config: <nil>"
	}

	v := reflect.ValueOf(c).Elem()
	t := v.Type()

	type fieldInfo struct {
		name  string
		value reflect.Value
	}
	var fields []fieldInfo
	maxKeyLen := 0

	for i := 0; i < t.NumField(); i++ {
		f := t.Field(i)
		if !f.IsExported() {
			continue
		}
		tagVal := f.Tag.Get("component")
		if component != "" {
			// Check whether the requested component appears in the
			// comma-separated tag value.
			found := false
			for _, part := range strings.Split(tagVal, ",") {
				if strings.TrimSpace(part) == component {
					found = true
					break
				}
			}
			if !found {
				continue
			}
		}
		if len(f.Name) > maxKeyLen {
			maxKeyLen = len(f.Name)
		}
		fields = append(fields, fieldInfo{name: f.Name, value: v.Field(i)})
	}

	lines := make([]string, 0, len(fields)+1)
	lines = append(lines, "Configuration:")
	for _, field := range fields {
		var valueStr string
		switch field.value.Kind() {
		case reflect.String:
			if s := field.value.String(); s == "" {
				valueStr = "<empty>"
			} else {
				valueStr = s
			}
		case reflect.Bool:
			valueStr = fmt.Sprintf("%t", field.value.Bool())
		case reflect.Int, reflect.Int8, reflect.Int16, reflect.Int32, reflect.Int64:
			valueStr = fmt.Sprintf("%d", field.value.Int())
		case reflect.Uint, reflect.Uint8, reflect.Uint16, reflect.Uint32, reflect.Uint64:
			valueStr = fmt.Sprintf("%d", field.value.Uint())
		case reflect.Float32, reflect.Float64:
			valueStr = fmt.Sprintf("%g", field.value.Float())
		default:
			valueStr = fmt.Sprintf("%v", field.value.Interface())
		}
		lines = append(lines, fmt.Sprintf("  - %-*s: %s", maxKeyLen, field.name, valueStr))
	}

	return strings.Join(lines, "\n")
}
