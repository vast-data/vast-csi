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

// Package auth implements CSI-Addons-style gRPC transport security for the
// VastExtensions API: TLS with a mounted server certificate for all listeners,
// plus TokenReview, a hardcoded Vast CSI driver SA allowlist, and per-request
// SubjectAccessReview for TCP.
package auth

import (
	"context"
	"crypto/tls"
	"fmt"
	"strings"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	authv1 "k8s.io/api/authentication/v1"
	authorizationv1 "k8s.io/api/authorization/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
)

const (
	ServerTLSName = "vast-extensions"

	bearerPrefix     = "Bearer "
	authorizationKey = "authorization"

	saUsernamePrefix = "system:serviceaccount:"
	// driverControllerSASuffix matches VastCSIDriver / standalone controller
	// ServiceAccounts: {release}-vast-controller-sa.
	driverControllerSASuffix = "-vast-controller-sa"
)

type contextKey int

const userInfoKey contextKey = 1

// SubjectAccessReviewCreator creates SubjectAccessReviews (satisfied by k8s_client.K8sClient).
type SubjectAccessReviewCreator interface {
	CreateSubjectAccessReview(ctx context.Context, sar *authorizationv1.SubjectAccessReview) error
}

// WithUser stores the TokenReview UserInfo for downstream authorization.
func WithUser(ctx context.Context, user authv1.UserInfo) context.Context {
	return context.WithValue(ctx, userInfoKey, user)
}

// UserFromContext returns the authenticated caller, if present (TCP path only).
func UserFromContext(ctx context.Context) (authv1.UserInfo, bool) {
	user, ok := ctx.Value(userInfoKey).(authv1.UserInfo)
	return user, ok
}

// isDriverControllerSA reports whether username is a Vast CSI driver controller
// ServiceAccount (system:serviceaccount:<ns>:<release>-vast-controller-sa).
func isDriverControllerSA(username string) bool {
	if !strings.HasPrefix(username, saUsernamePrefix) {
		return false
	}
	parts := strings.Split(username, ":")
	if len(parts) != 4 || parts[2] == "" || parts[3] == "" {
		return false
	}
	return strings.HasSuffix(parts[3], driverControllerSASuffix)
}

// TLSServerOptions returns gRPC server options with TLS credentials only.
// Used for unix sockets (same-pod IPC); TokenReview is not applied.
func TLSServerOptions(certFile, keyFile string) ([]grpc.ServerOption, error) {
	if certFile == "" || keyFile == "" {
		return nil, fmt.Errorf("TLS certificate and key paths are required for VastExtensions gRPC (got cert=%q key=%q)", certFile, keyFile)
	}
	cert, err := tls.LoadX509KeyPair(certFile, keyFile)
	if err != nil {
		return nil, fmt.Errorf("load VastExtensions TLS certificate: %w", err)
	}
	creds := credentials.NewTLS(&tls.Config{
		Certificates: []tls.Certificate{cert},
		MinVersion:   tls.VersionTLS12,
	})
	return []grpc.ServerOption{grpc.Creds(creds)}, nil
}

// TCPServerOptions returns gRPC server options for a cluster-wide TCP listener:
// TLS, TokenReview, and a hardcoded allowlist of Vast CSI driver controller SAs.
func TCPServerOptions(kubeClient kubernetes.Interface, certFile, keyFile string) ([]grpc.ServerOption, error) {
	if kubeClient == nil {
		return nil, fmt.Errorf("kubernetes client is required for VastExtensions TCP auth")
	}
	opts, err := TLSServerOptions(certFile, keyFile)
	if err != nil {
		return nil, err
	}
	return append(opts, grpc.UnaryInterceptor(authorizationInterceptor(kubeClient))), nil
}

func authorizationInterceptor(kubeClient kubernetes.Interface) grpc.UnaryServerInterceptor {
	return func(ctx context.Context, req interface{}, info *grpc.UnaryServerInfo, handler grpc.UnaryHandler) (interface{}, error) {
		ctx, err := authorizeConnection(ctx, kubeClient)
		if err != nil {
			return nil, err
		}
		return handler(ctx, req)
	}
}

func authorizeConnection(ctx context.Context, kubeClient kubernetes.Interface) (context.Context, error) {
	md, ok := metadata.FromIncomingContext(ctx)
	if !ok {
		return nil, status.Error(codes.Unauthenticated, "missing metadata")
	}
	authHeader, ok := md[authorizationKey]
	if !ok || len(authHeader) == 0 {
		return nil, status.Error(codes.Unauthenticated, "missing authorization token")
	}
	user, authenticated, err := validateBearerToken(ctx, authHeader[0], kubeClient)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "token review failed: %v", err)
	}
	if !authenticated {
		return nil, status.Error(codes.Unauthenticated, "invalid token")
	}
	if !isDriverControllerSA(user.Username) {
		return nil, status.Errorf(codes.PermissionDenied, "identity %q is not an allowed VastExtensions caller", user.Username)
	}
	return WithUser(ctx, user), nil
}

func validateBearerToken(ctx context.Context, authHeader string, kubeClient kubernetes.Interface) (authv1.UserInfo, bool, error) {
	tokenReview := &authv1.TokenReview{
		Spec: authv1.TokenReviewSpec{
			Token: strings.TrimPrefix(authHeader, bearerPrefix),
		},
	}
	result, err := kubeClient.AuthenticationV1().TokenReviews().Create(ctx, tokenReview, metav1.CreateOptions{})
	if err != nil {
		return authv1.UserInfo{}, false, err
	}
	return result.Status.User, result.Status.Authenticated, nil
}

// AuthorizeSecretGet checks that the TCP caller may get the named Secret.
// On the unix path (no UserInfo in context) this is a no-op.
func AuthorizeSecretGet(ctx context.Context, reviewer SubjectAccessReviewCreator, secretName, secretNamespace string) error {
	user, ok := UserFromContext(ctx)
	if !ok {
		return nil
	}
	if reviewer == nil {
		return status.Error(codes.Internal, "subject access review client is required for secret authorization")
	}
	sar := &authorizationv1.SubjectAccessReview{
		Spec: authorizationv1.SubjectAccessReviewSpec{
			User:   user.Username,
			UID:    user.UID,
			Groups: user.Groups,
			Extra:  extraToSAR(user.Extra),
			ResourceAttributes: &authorizationv1.ResourceAttributes{
				Namespace: secretNamespace,
				Verb:      "get",
				Group:     "",
				Resource:  "secrets",
				Name:      secretName,
			},
		},
	}
	if err := reviewer.CreateSubjectAccessReview(ctx, sar); err != nil {
		return status.Errorf(codes.Internal, "subject access review failed: %v", err)
	}
	if !sar.Status.Allowed {
		return status.Errorf(codes.PermissionDenied,
			"caller is not allowed to get secret %s/%s", secretNamespace, secretName)
	}
	return nil
}

func extraToSAR(extra map[string]authv1.ExtraValue) map[string]authorizationv1.ExtraValue {
	if len(extra) == 0 {
		return nil
	}
	out := make(map[string]authorizationv1.ExtraValue, len(extra))
	for k, v := range extra {
		out[k] = authorizationv1.ExtraValue(v)
	}
	return out
}
