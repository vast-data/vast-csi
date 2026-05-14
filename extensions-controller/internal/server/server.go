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
//	srv := server.New("/var/run/vast-extensions/extensions.sock", logger)
//	srv.RegisterService(discovery.NewService(k8sClient, logger))
//	if err := mgr.Add(srv); err != nil { ... }
package server

import (
	"context"
	"net"
	"os"

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
	// ExtensionsSocketPath is the unix socket path of the extensions gRPC server.
	// It must match the mountPath in the Helm chart and EXTENSIONS_SOCKET in
	// the Python extensions_client module.
	ExtensionsSocketPath = "/var/run/vast-extensions/extensions.sock"
)

// GRPCServer is a generic unix-socket gRPC server that starts and stops
// together with the controller-runtime manager.
type GRPCServer struct {
	socketPath string
	services   []Service
	log        *zap.Logger
}

// New creates a GRPCServer that will listen on socketPath.
func New(socketPath string, log *zap.Logger) *GRPCServer {
	return &GRPCServer{
		socketPath: socketPath,
		log:        log.Named("grpc-server"),
	}
}

// RegisterService enqueues svc for registration.  Must be called before Start.
func (s *GRPCServer) RegisterService(svc Service) {
	s.services = append(s.services, svc)
}

// Start implements controller-runtime's Runnable.  It creates the unix socket,
// registers all services, starts the gRPC server, and blocks until ctx is
// cancelled.
func (s *GRPCServer) Start(ctx context.Context) error {
	// Remove stale socket file from a previous run.
	if err := os.Remove(s.socketPath); err != nil && !os.IsNotExist(err) {
		return err
	}
	if err := os.MkdirAll(dirOf(s.socketPath), 0o700); err != nil {
		return err
	}

	lis, err := net.Listen("unix", s.socketPath)
	if err != nil {
		return err
	}

	srv := grpc.NewServer()
	for _, svc := range s.services {
		svc.RegisterService(srv)
	}

	s.log.Info("gRPC server listening", zap.String("socket", s.socketPath))

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

func dirOf(path string) string {
	for i := len(path) - 1; i >= 0; i-- {
		if path[i] == '/' {
			return path[:i]
		}
	}
	return "."
}
