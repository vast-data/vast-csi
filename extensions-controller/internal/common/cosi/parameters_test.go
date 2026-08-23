package cosi

import "testing"

func TestParamsFromClaimAnnotations(t *testing.T) {
	ann := map[string]string{
		"cosi.vastdata.com/sourceBucket":   "prod-data",
		"cosi.vastdata.com/blockingClones": "true",
		"cosi.vastdata.com/unknown":        "keep",
		"other.annotation":                 "skip",
		"cosi.vastdata.com/empty":          "",
	}
	got := ParamsFromClaimAnnotations(ann)
	if got["cosi.vastdata.com/sourceBucket"] != "prod-data" ||
		got["cosi.vastdata.com/blockingClones"] != "true" ||
		got["cosi.vastdata.com/unknown"] != "keep" {
		t.Fatalf("unexpected params: %#v", got)
	}
	if _, ok := got["other.annotation"]; ok {
		t.Fatal("non-prefix annotation should be ignored")
	}
	if _, ok := got["cosi.vastdata.com/empty"]; ok {
		t.Fatal("empty annotation value should be ignored")
	}
	if len(got) != 3 {
		t.Fatalf("expected 3 params, got %#v", got)
	}
}

func TestMergeParameters_claimWins(t *testing.T) {
	class := map[string]string{"view_policy": "p1"}
	claim := map[string]string{
		"cosi.vastdata.com/sourceBucket": "src",
	}
	merged := MergeParameters(class, claim)
	if merged["cosi.vastdata.com/sourceBucket"] != "src" || merged["view_policy"] != "p1" {
		t.Fatalf("merge wrong: %#v", merged)
	}
}
