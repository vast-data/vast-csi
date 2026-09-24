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

func TestSecretRefFromParameters(t *testing.T) {
	name, ns, ok := SecretRefFromParameters(map[string]string{
		SecretNameParam:      "team-auth",
		SecretNamespaceParam: "app-team",
	})
	if !ok || name != "team-auth" || ns != "app-team" {
		t.Fatalf("got name=%q ns=%q ok=%v", name, ns, ok)
	}

	_, _, ok = SecretRefFromParameters(map[string]string{"view_policy": "p1"})
	if ok {
		t.Fatal("expected ok=false when secret refs absent")
	}

	name, ns, ok = SecretRefFromParameters(map[string]string{SecretNameParam: "only-name"})
	if !ok || name != "only-name" || ns != "" {
		t.Fatalf("partial ref: name=%q ns=%q ok=%v", name, ns, ok)
	}
}
