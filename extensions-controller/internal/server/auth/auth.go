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

// Package auth implements CSI-Addons-style gRPC transport security for the
// VastExtensions TCP API: TLS with an ephemeral self-signed certificate, plus
// a Bearer ServiceAccount token checked via TokenReview.
package auth

import (
	"context"
	"crypto/rand"
	"crypto/rsa"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"fmt"
	"math/big"
	"strings"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	authv1 "k8s.io/api/authentication/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
)

const (
	ServerTLSName = "vast-extensions"

	bearerPrefix     = "Bearer "
	authorizationKey = "authorization"
)

// TCPServerOptions returns gRPC server options for a cluster-wide TCP listener:
// TLS (self-signed) and a TokenReview interceptor. Unix sockets do not use this.
func TCPServerOptions(kubeClient kubernetes.Interface) ([]grpc.ServerOption, error) {
	if kubeClient == nil {
		return nil, fmt.Errorf("kubernetes client is required for VastExtensions TCP auth")
	}
	cert, err := generateSelfSignedCert()
	if err != nil {
		return nil, fmt.Errorf("generate self-signed certificate: %w", err)
	}
	creds := credentials.NewTLS(&tls.Config{
		Certificates: []tls.Certificate{cert},
		MinVersion:   tls.VersionTLS12,
	})
	return []grpc.ServerOption{
		grpc.Creds(creds),
		grpc.UnaryInterceptor(authorizationInterceptor(kubeClient)),
	}, nil
}

func authorizationInterceptor(kubeClient kubernetes.Interface) grpc.UnaryServerInterceptor {
	return func(ctx context.Context, req interface{}, info *grpc.UnaryServerInfo, handler grpc.UnaryHandler) (interface{}, error) {
		if err := authorizeConnection(ctx, kubeClient); err != nil {
			return nil, err
		}
		return handler(ctx, req)
	}
}

func authorizeConnection(ctx context.Context, kubeClient kubernetes.Interface) error {
	md, ok := metadata.FromIncomingContext(ctx)
	if !ok {
		return status.Error(codes.Unauthenticated, "missing metadata")
	}
	authHeader, ok := md[authorizationKey]
	if !ok || len(authHeader) == 0 {
		return status.Error(codes.Unauthenticated, "missing authorization token")
	}
	authenticated, err := validateBearerToken(ctx, authHeader[0], kubeClient)
	if err != nil {
		return status.Errorf(codes.Internal, "token review failed: %v", err)
	}
	if !authenticated {
		return status.Error(codes.Unauthenticated, "invalid token")
	}
	return nil
}

func validateBearerToken(ctx context.Context, authHeader string, kubeClient kubernetes.Interface) (bool, error) {
	tokenReview := &authv1.TokenReview{
		Spec: authv1.TokenReviewSpec{
			Token: strings.TrimPrefix(authHeader, bearerPrefix),
		},
	}
	result, err := kubeClient.AuthenticationV1().TokenReviews().Create(ctx, tokenReview, metav1.CreateOptions{})
	if err != nil {
		return false, err
	}
	return result.Status.Authenticated, nil
}

func generateSelfSignedCert() (tls.Certificate, error) {
	privateKey, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		return tls.Certificate{}, err
	}

	template := x509.Certificate{
		SerialNumber: big.NewInt(1),
		Subject: pkix.Name{
			CommonName:   ServerTLSName,
			Organization: []string{"vast-extensions-grpc"},
		},
		DNSNames:    []string{ServerTLSName},
		NotBefore:   time.Now().Add(-time.Hour),
		NotAfter:    time.Now().Add(10 * 365 * 24 * time.Hour),
		KeyUsage:    x509.KeyUsageKeyEncipherment | x509.KeyUsageDigitalSignature,
		ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
		IsCA:        true,
	}

	certDER, err := x509.CreateCertificate(rand.Reader, &template, &template, &privateKey.PublicKey, privateKey)
	if err != nil {
		return tls.Certificate{}, err
	}
	certPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: certDER})
	keyPEM := pem.EncodeToMemory(&pem.Block{Type: "RSA PRIVATE KEY", Bytes: x509.MarshalPKCS1PrivateKey(privateKey)})
	return tls.X509KeyPair(certPEM, keyPEM)
}
