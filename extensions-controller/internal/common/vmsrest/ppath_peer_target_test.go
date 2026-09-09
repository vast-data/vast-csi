package vmsrest

import (
	"errors"
	"strings"
	"testing"

	cerrors "github.com/vast-data/vast-csi/extensions-controller/internal/common/errors"
)

func TestIsPathOnPeerExistsErr(t *testing.T) {
	t.Parallel()
	if !isPathOnPeerExistsErr(errors.New(`Cannot create remote stream: path on peer exists`)) {
		t.Fatal("expected match")
	}
	if isPathOnPeerExistsErr(errors.New("unrelated")) {
		t.Fatal("expected no match")
	}
	if isPathOnPeerExistsErr(nil) {
		t.Fatal("nil must be false")
	}
}

func TestHandlePathOnPeerExistsRejectsUnsafePaths(t *testing.T) {
	t.Parallel()

	for _, path := range []string{"", "/", "   ", " / "} {
		err := handlePathOnPeerExists(nil, path, 1, nil, true)
		if err == nil {
			t.Fatalf("path %q: expected error", path)
		}
		if !strings.Contains(err.Error(), "unsafe peer target_exported_dir") {
			t.Fatalf("path %q: unexpected error %v", path, err)
		}
		var retryable cerrors.Retryable
		if errors.As(err, &retryable) {
			t.Fatalf("path %q: unsafe path must be permanent, got retryable", path)
		}
	}
}

func TestHandlePathOnPeerExistsBlockSkipsCleanup(t *testing.T) {
	t.Parallel()
	err := handlePathOnPeerExists(nil, "/source", 1, nil, false)
	if err == nil {
		t.Fatal("expected error")
	}
	if !strings.Contains(err.Error(), "block replication") {
		t.Fatalf("expected block-specific error, got %v", err)
	}
	if !strings.Contains(err.Error(), "/source") {
		t.Fatalf("expected path in error, got %v", err)
	}
	var ra *cerrors.RetryAfterError
	if errors.As(err, &ra) {
		t.Fatalf("block path-on-peer must be permanent, got RetryAfterError")
	}
}

func TestHandlePathOnPeerExistsMissingRemoteIsPermanent(t *testing.T) {
	t.Parallel()
	err := handlePathOnPeerExists(nil, "/vast", 1, nil, true)
	if err == nil {
		t.Fatal("expected error")
	}
	var ra *cerrors.RetryAfterError
	if errors.As(err, &ra) {
		t.Fatalf("missing remote must not be RetryAfterError, got %v", err)
	}
}
