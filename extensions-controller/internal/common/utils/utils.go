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

package utils

import (
	"fmt"
	"regexp"
	"strings"
)

// tokenPattern matches format tokens like {pvc_name}, {pvc_name_suf:30}, {endpoint}, etc.
var tokenPattern = regexp.MustCompile(`\{(\w+?)(?::(\d+))?\}`)

// ValidateNameFormat checks that a format string contains only known tokens.
// Returns an error if unknown tokens are found.
func ValidateNameFormat(format string, kind string) error {
	validPVCTokens := map[string]bool{
		"pvc_name": true, "pvc_name_suf": true, "pvc_name_pref": true,
		"endpoint": true, "sc_name": true, "sc_name_suf": true, "sc_name_pref": true,
	}
	validPVTokens := map[string]bool{
		"pv_name": true, "pv_name_suf": true, "pv_name_pref": true,
		"endpoint": true, "sc_name": true, "sc_name_suf": true, "sc_name_pref": true,
	}

	var validTokens map[string]bool
	switch kind {
	case "pvc":
		validTokens = validPVCTokens
	case "pv":
		validTokens = validPVTokens
	default:
		return fmt.Errorf("unknown kind %q, expected 'pvc' or 'pv'", kind)
	}

	matches := tokenPattern.FindAllStringSubmatch(format, -1)
	for _, m := range matches {
		token := m[1]
		if !validTokens[token] {
			return fmt.Errorf("unknown token {%s} in %s name format %q", token, kind, format)
		}
	}
	return nil
}

// SanitizeK8sName converts an arbitrary string into a valid Kubernetes object
// name (RFC 1123 subdomain, ≤ 253 characters):
//   - lowercased
//   - any character outside [a-z0-9-.] replaced with a dash
//   - consecutive dashes collapsed to one
//   - leading / trailing dashes and dots trimmed
//   - truncated to 253 characters (trailing dashes/dots removed after truncation)
//
// If the result is empty, "resource" is returned as a safe fallback.
func SanitizeK8sName(name string) string {
	name = strings.ToLower(name)
	sanitized := strings.Map(func(r rune) rune {
		if (r >= 'a' && r <= 'z') || (r >= '0' && r <= '9') || r == '-' || r == '.' {
			return r
		}
		return '-'
	}, name)
	for strings.Contains(sanitized, "--") {
		sanitized = strings.ReplaceAll(sanitized, "--", "-")
	}
	sanitized = strings.Trim(sanitized, "-.")
	if len(sanitized) > 253 {
		sanitized = strings.TrimRight(sanitized[:253], "-.")
	}
	if sanitized == "" {
		sanitized = "resource"
	}
	return sanitized
}

// ParseCommaSeparated splits a comma-separated string, trims whitespace from
// each element, and drops empty elements.
func ParseCommaSeparated(s string) []string {
	parts := strings.Split(s, ",")
	result := make([]string, 0, len(parts))
	for _, p := range parts {
		p = strings.TrimSpace(p)
		if p != "" {
			result = append(result, p)
		}
	}
	return result
}

// SanitizeLabelValue converts a string to a valid Kubernetes label value.
// Label values must be <= 63 chars, start/end with alphanumeric, and contain
// only [-_.a-zA-Z0-9].
func SanitizeLabelValue(value string) string {
	if value == "" {
		return ""
	}
	// Import common package to use InvalidLabelCharsRegex
	// For now, we'll define the regex here to avoid circular dependency
	invalidLabelCharsRegex := regexp.MustCompile(`[^a-zA-Z0-9\-_.]`)
	sanitized := invalidLabelCharsRegex.ReplaceAllString(value, "_")
	sanitized = strings.Trim(sanitized, "-_.")
	if len(sanitized) > 63 {
		sanitized = sanitized[:63]
	}
	return sanitized
}
