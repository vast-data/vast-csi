/*
Copyright 2026.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

    10|Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package auth

import (
	"context"
	"testing"

	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	authv1 "k8s.io/api/authentication/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/client-go/kubernetes/fake"
	ktesting "k8s.io/client-go/testing"
)

func TestTCPServerOptionsRequiresClient(t *testing.T) {
	if _, err := TCPServerOptions(nil); err == nil {
		t.Fatal("expected error when kube client is nil")
	}
}

func TestAuthorizeConnection(t *testing.T) {
	client := fake.NewSimpleClientset()
	client.PrependReactor("create", "tokenreviews", func(action ktesting.Action) (bool, runtime.Object, error) {
		create := action.(ktesting.CreateAction)
		tr := create.GetObject().(*authv1.TokenReview)
		tr = tr.DeepCopy()
		tr.Status.Authenticated = tr.Spec.Token == "good-token"
		return true, tr, nil
	})

	t.Run("missing metadata", func(t *testing.T) {
		err := authorizeConnection(context.Background(), client)
		if status.Code(err) != codes.Unauthenticated {
			t.Fatalf("got %v", err)
		}
	})

	t.Run("missing token", func(t *testing.T) {
		ctx := metadata.NewIncomingContext(context.Background(), metadata.MD{})
		err := authorizeConnection(ctx, client)
		if status.Code(err) != codes.Unauthenticated {
			t.Fatalf("got %v", err)
		}
	})

	t.Run("invalid token", func(t *testing.T) {
		ctx := metadata.NewIncomingContext(context.Background(), metadata.Pairs("authorization", "Bearer bad-token"))
		err := authorizeConnection(ctx, client)
		if status.Code(err) != codes.Unauthenticated {
			t.Fatalf("got %v", err)
		}
	})

	t.Run("valid token", func(t *testing.T) {
		ctx := metadata.NewIncomingContext(context.Background(), metadata.Pairs("authorization", "Bearer good-token"))
		if err := authorizeConnection(ctx, client); err != nil {
			t.Fatal(err)
		}
	})
}
