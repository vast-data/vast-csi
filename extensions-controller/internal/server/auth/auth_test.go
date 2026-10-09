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

package auth

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"math/big"
	"os"
	"path/filepath"
	"testing"
	"time"

	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	authv1 "k8s.io/api/authentication/v1"
	authorizationv1 "k8s.io/api/authorization/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/client-go/kubernetes/fake"
	ktesting "k8s.io/client-go/testing"
)

func TestTLSServerOptionsRequiresCertPaths(t *testing.T) {
	if _, err := TLSServerOptions("", "key.pem"); err == nil {
		t.Fatal("expected error when cert path is empty")
	}
	if _, err := TLSServerOptions("cert.pem", ""); err == nil {
		t.Fatal("expected error when key path is empty")
	}
}

func TestTLSServerOptionsLoadsCert(t *testing.T) {
	dir := t.TempDir()
	certFile := filepath.Join(dir, "tls.crt")
	keyFile := filepath.Join(dir, "tls.key")
	writeTestTLSPair(t, certFile, keyFile)

	opts, err := TLSServerOptions(certFile, keyFile)
	if err != nil {
		t.Fatal(err)
	}
	if len(opts) != 1 {
		t.Fatalf("expected Creds-only options, got %d", len(opts))
	}
}

func TestTCPServerOptionsRequiresClient(t *testing.T) {
	if _, err := TCPServerOptions(nil, "cert.pem", "key.pem"); err == nil {
		t.Fatal("expected error when kube client is nil")
	}
}

func TestTCPServerOptionsRequiresCertPaths(t *testing.T) {
	client := fake.NewSimpleClientset()
	if _, err := TCPServerOptions(client, "", "key.pem"); err == nil {
		t.Fatal("expected error when cert path is empty")
	}
	if _, err := TCPServerOptions(client, "cert.pem", ""); err == nil {
		t.Fatal("expected error when key path is empty")
	}
}

func TestTCPServerOptionsLoadsCert(t *testing.T) {
	dir := t.TempDir()
	certFile := filepath.Join(dir, "tls.crt")
	keyFile := filepath.Join(dir, "tls.key")
	writeTestTLSPair(t, certFile, keyFile)

	client := fake.NewSimpleClientset()
	opts, err := TCPServerOptions(client, certFile, keyFile)
	if err != nil {
		t.Fatal(err)
	}
	if len(opts) != 2 {
		t.Fatalf("expected Creds + interceptor options, got %d", len(opts))
	}
}

func TestIsDriverControllerSA(t *testing.T) {
	if !isDriverControllerSA("system:serviceaccount:ns:csi-vast-controller-sa") {
		t.Fatal("expected driver controller SA to be allowed")
	}
	if !isDriverControllerSA("system:serviceaccount:other:my-release-vast-controller-sa") {
		t.Fatal("expected any-namespace *-vast-controller-sa to be allowed")
	}
	if isDriverControllerSA("system:serviceaccount:ns:default") {
		t.Fatal("expected unrelated SA to be rejected")
	}
	if isDriverControllerSA("system:serviceaccount:ns:vast-extension-controller-sa") {
		t.Fatal("expected non-controller SA suffix to be rejected")
	}
	if isDriverControllerSA("") {
		t.Fatal("expected empty username to be rejected")
	}
}

func TestAuthorizeConnection(t *testing.T) {
	client := fake.NewSimpleClientset()
	client.PrependReactor("create", "tokenreviews", func(action ktesting.Action) (bool, runtime.Object, error) {
		create := action.(ktesting.CreateAction)
		tr := create.GetObject().(*authv1.TokenReview)
		tr = tr.DeepCopy()
		switch tr.Spec.Token {
		case "good-driver":
			tr.Status.Authenticated = true
			tr.Status.User = authv1.UserInfo{Username: "system:serviceaccount:ns:csi-vast-controller-sa"}
		case "good-other":
			tr.Status.Authenticated = true
			tr.Status.User = authv1.UserInfo{Username: "system:serviceaccount:ns:default"}
		default:
			tr.Status.Authenticated = false
		}
		return true, tr, nil
	})

	t.Run("missing metadata", func(t *testing.T) {
		_, err := authorizeConnection(context.Background(), client)
		if status.Code(err) != codes.Unauthenticated {
			t.Fatalf("got %v", err)
		}
	})

	t.Run("missing token", func(t *testing.T) {
		ctx := metadata.NewIncomingContext(context.Background(), metadata.MD{})
		_, err := authorizeConnection(ctx, client)
		if status.Code(err) != codes.Unauthenticated {
			t.Fatalf("got %v", err)
		}
	})

	t.Run("invalid token", func(t *testing.T) {
		ctx := metadata.NewIncomingContext(context.Background(), metadata.Pairs("authorization", "Bearer bad-token"))
		_, err := authorizeConnection(ctx, client)
		if status.Code(err) != codes.Unauthenticated {
			t.Fatalf("got %v", err)
		}
	})

	t.Run("valid token unexpected identity", func(t *testing.T) {
		ctx := metadata.NewIncomingContext(context.Background(), metadata.Pairs("authorization", "Bearer good-other"))
		_, err := authorizeConnection(ctx, client)
		if status.Code(err) != codes.PermissionDenied {
			t.Fatalf("got %v", err)
		}
	})

	t.Run("valid token expected identity", func(t *testing.T) {
		ctx := metadata.NewIncomingContext(context.Background(), metadata.Pairs("authorization", "Bearer good-driver"))
		out, err := authorizeConnection(ctx, client)
		if err != nil {
			t.Fatal(err)
		}
		user, ok := UserFromContext(out)
		if !ok || user.Username != "system:serviceaccount:ns:csi-vast-controller-sa" {
			t.Fatalf("user not stored in context: %+v ok=%v", user, ok)
		}
	})
}

func TestAuthorizeSecretGet(t *testing.T) {
	reviewer := &fakeSARCreator{
		allow: func(sar *authorizationv1.SubjectAccessReview) bool {
			attrs := sar.Spec.ResourceAttributes
			return attrs != nil &&
				attrs.Namespace == "allowed-ns" &&
				attrs.Name == "allowed-secret" &&
				attrs.Resource == "secrets" &&
				attrs.Verb == "get"
		},
	}

	t.Run("unix path skips SAR", func(t *testing.T) {
		if err := AuthorizeSecretGet(context.Background(), reviewer, "any", "any"); err != nil {
			t.Fatal(err)
		}
	})

	t.Run("unrelated namespace denied", func(t *testing.T) {
		ctx := WithUser(context.Background(), authv1.UserInfo{Username: "system:serviceaccount:ns:csi-vast-controller-sa"})
		err := AuthorizeSecretGet(ctx, reviewer, "secret", "other-ns")
		if status.Code(err) != codes.PermissionDenied {
			t.Fatalf("got %v", err)
		}
	})

	t.Run("expected identity referenced secret allowed", func(t *testing.T) {
		ctx := WithUser(context.Background(), authv1.UserInfo{Username: "system:serviceaccount:ns:csi-vast-controller-sa"})
		if err := AuthorizeSecretGet(ctx, reviewer, "allowed-secret", "allowed-ns"); err != nil {
			t.Fatal(err)
		}
	})
}

type fakeSARCreator struct {
	allow func(*authorizationv1.SubjectAccessReview) bool
}

func (f *fakeSARCreator) CreateSubjectAccessReview(_ context.Context, sar *authorizationv1.SubjectAccessReview) error {
	sar.Status.Allowed = f.allow != nil && f.allow(sar)
	return nil
}

func writeTestTLSPair(t *testing.T, certFile, keyFile string) {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	template := &x509.Certificate{
		SerialNumber: big.NewInt(1),
		Subject:      pkix.Name{CommonName: ServerTLSName},
		DNSNames:     []string{ServerTLSName},
		NotBefore:    time.Now().Add(-time.Hour),
		NotAfter:     time.Now().Add(time.Hour),
		KeyUsage:     x509.KeyUsageDigitalSignature | x509.KeyUsageKeyEncipherment,
		ExtKeyUsage:  []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
	}
	der, err := x509.CreateCertificate(rand.Reader, template, template, &key.PublicKey, key)
	if err != nil {
		t.Fatal(err)
	}
	certPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})
	keyDER, err := x509.MarshalECPrivateKey(key)
	if err != nil {
		t.Fatal(err)
	}
	keyPEM := pem.EncodeToMemory(&pem.Block{Type: "EC PRIVATE KEY", Bytes: keyDER})
	if err := os.WriteFile(certFile, certPEM, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(keyFile, keyPEM, 0o600); err != nil {
		t.Fatal(err)
	}
}
