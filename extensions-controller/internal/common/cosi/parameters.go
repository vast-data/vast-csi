package cosi

import "strings"

const (
	AnnotationPrefix   = "cosi.vastdata.com/"
	VastCOSIDriverName = "csi.vastdata.com"
)

// ParamsFromClaimAnnotations copies cosi.vastdata.com/* annotations into parameters
// using the full annotation key (no prefix trim) so claim params stay visible and
// do not collide with native BucketClass parameters.
func ParamsFromClaimAnnotations(annotations map[string]string) map[string]string {
	out := make(map[string]string)
	for key, value := range annotations {
		if !strings.HasPrefix(key, AnnotationPrefix) {
			continue
		}
		if value == "" {
			continue
		}
		out[key] = value
	}
	return out
}

// MergeParameters overlays claim-derived params onto class params (claim wins).
func MergeParameters(classParams, claimParams map[string]string) map[string]string {
	merged := make(map[string]string, len(classParams)+len(claimParams))
	for k, v := range classParams {
		merged[k] = v
	}
	for k, v := range claimParams {
		merged[k] = v
	}
	return merged
}
