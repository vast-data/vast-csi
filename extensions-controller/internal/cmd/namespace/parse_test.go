package namespace

import (
	"reflect"
	"testing"
)

func TestSplitLeadingFlags_boolDoesNotSwallowNamespace(t *testing.T) {
	ns := map[string]struct{}{"webhook": {}, "server": {}, "cosi": {}}
	root, rest := splitLeadingFlags([]string{
		"--health-probe-bind-address=:8081",
		"--metrics-bind-address=0",
		"--dev-logging",
		"webhook",
		"--webhook-cert-path=/tmp/x",
		"cosi",
		"server",
		"--extensions-grpc-bind-address=/tmp/e.sock",
	}, ns)
	wantRoot := []string{
		"--health-probe-bind-address=:8081",
		"--metrics-bind-address=0",
		"--dev-logging",
	}
	wantRest := []string{
		"webhook",
		"--webhook-cert-path=/tmp/x",
		"cosi",
		"server",
		"--extensions-grpc-bind-address=/tmp/e.sock",
	}
	if !reflect.DeepEqual(root, wantRoot) {
		t.Fatalf("root flags: got %#v want %#v", root, wantRoot)
	}
	if !reflect.DeepEqual(rest, wantRest) {
		t.Fatalf("rest: got %#v want %#v", rest, wantRest)
	}
}
