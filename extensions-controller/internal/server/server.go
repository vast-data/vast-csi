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

// Package server provides a generic gRPC server that supports dynamic service
// registration.  It is designed to be used as a controller-runtime Runnable so
// it starts and stops together with the manager.
//
// Usage:
//
//	srv := server.New(":9090", logger) // TCP — cluster-wide via a Kubernetes Service
//	srv := server.New(server.ExtensionsSocketPath, logger) // unix — co-located sidecar
//	srv.RegisterService(discovery.NewService(k8sClient, logger))
//	if err := mgr.Add(srv); err != nil { ... }
package server

import (
	"context"
	"net"
	"os"
	"strings"

	"go.uber.org/zap"
	"google.golang.org/grpc"
)

// Service is implemented by any gRPC service that wants to register itself
// with a GRPCServer.  RegisterService is called once during Start, before the
// server begins accepting connections.
type Service interface {
	RegisterService(srv grpc.ServiceRegistrar)
}

const (
	// ExtensionsSocketPath is the default unix socket path for co-located
	// extensions-manager and replication-vast-plugin containers (standalone Helm chart).
	// It must match the mountPath in the Helm chart and the Python client default.
	ExtensionsSocketPath = "/var/run/vast-extensions/extensions.sock"

	// DefaultExtensionsGRPCBindAddress is the default TCP bind address for the
	// cluster-wide VastExtensionsManager (operator / cross-pod model).
	DefaultExtensionsGRPCBindAddress = ":9090"
)

// GRPCServer is a gRPC server that starts and stops together with the
// controller-runtime manager.  It listens on TCP or a unix socket depending on
// bindAddress (see parseBindAddress).
type GRPCServer struct {
	network     string
	bindAddress string
	services    []Service
	log         *zap.Logger
}

// New creates a GRPCServer that will listen on bindAddress.
// Use a TCP address (e.g. ":9090") for cross-pod access, or an absolute unix
// socket path for co-located sidecars.
func New(bindAddress string, log *zap.Logger) *GRPCServer {
	network, addr := parseBindAddress(bindAddress)
	return &GRPCServer{
		network:     network,
		bindAddress: addr,
		log:         log.Named("grpc-server"),
	}
}

// RegisterService enqueues svc for registration.  Must be called before Start.
func (s *GRPCServer) RegisterService(svc Service) {
	s.services = append(s.services, svc)
}

// Start implements controller-runtime's Runnable.  It creates the listener,
// registers all services, starts the gRPC server, and blocks until ctx is
// cancelled.
func (s *GRPCServer) Start(ctx context.Context) error {
	if s.network == "unix" {
		if err := os.Remove(s.bindAddress); err != nil && !os.IsNotExist(err) {
			return err
		}
		if err := os.MkdirAll(dirOf(s.bindAddress), 0o700); err != nil {
			return err
		}
	}

	lis, err := net.Listen(s.network, s.bindAddress)
	if err != nil {
		return err
	}

	srv := grpc.NewServer()
	for _, svc := range s.services {
		svc.RegisterService(srv)
	}

	s.log.Info("gRPC server listening",
		zap.String("network", s.network),
		zap.String("address", s.bindAddress))

	errCh := make(chan error, 1)
	go func() { errCh <- srv.Serve(lis) }()

	select {
	case <-ctx.Done():
		srv.GracefulStop()
		return nil
	case err := <-errCh:
		return err
	}
}

func parseBindAddress(bindAddress string) (network, addr string) {
	if strings.HasPrefix(bindAddress, "unix://") {
		return "unix", strings.TrimPrefix(bindAddress, "unix://")
	}
	if strings.HasPrefix(bindAddress, "/") {
		return "unix", bindAddress
	}
	return "tcp", bindAddress
}

func dirOf(path string) string {
	for i := len(path) - 1; i >= 0; i-- {
		if path[i] == '/' {
			return path[:i]
		}
	}
	return "."
}
