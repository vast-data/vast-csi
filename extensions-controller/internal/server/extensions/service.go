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

// Package extensions implements the VastExtensions gRPC service.
// The service exposes management operations to non-native clients

package extensions

import (
	"context"

	vastv1alpha1 "github.com/vast-data/vast-csi/extensions-controller/api/v1alpha1"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/k8s_client"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/logging"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/vmsrest"
	extensionsv1 "github.com/vast-data/vast-csi/extensions-controller/internal/server/extensions/v1"
	"go.uber.org/zap"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

// Service implements the VastExtensions gRPC service and satisfies the
// server.Service interface so it can be plugged into a server.GRPCServer.
type Service struct {
	extensionsv1.UnimplementedVastExtensionsServer
	k8sClient *k8s_client.K8sClient
	sslVerify bool
	log       *zap.Logger
	rainbow   *logging.RainbowLogger
}

// NewService creates a VastExtensions Service.
func NewService(k8sClient *k8s_client.K8sClient, sslVerify bool, log *zap.Logger, rainbow *logging.RainbowLogger) *Service {
	return &Service{
		k8sClient: k8sClient,
		sslVerify: sslVerify,
		log:       log.Named("extensions-service"),
		rainbow:   rainbow,
	}
}

// RegisterService implements server.Service — registers the VastExtensions
// handler on the provided gRPC server.
func (s *Service) RegisterService(srv grpc.ServiceRegistrar) {
	extensionsv1.RegisterVastExtensionsServer(srv, s)
}

// ---------------------------------------------------------------------------
// gRPC handlers
// ---------------------------------------------------------------------------

// GetReplicationTenant resolves the VAST tenant GUID.
func (s *Service) GetReplicationTenant(
	ctx context.Context,
	req *extensionsv1.GetReplicationTenantRequest,
) (*extensionsv1.GetReplicationTenantResponse, error) {
	if req.StorageClass == "" {
		return nil, status.Error(codes.InvalidArgument, "storage_class must not be empty")
	}

	log := s.rainbow.For("storageClass", req.StorageClass)

	rest, sc, err := vmsrest.NewFromStorageClassName(ctx, s.k8sClient, req.StorageClass, s.sslVerify, log)
	if err != nil {
		return nil, status.Errorf(codes.Internal,
			"failed to build VMS REST client from StorageClass %q: %v", req.StorageClass, err)
	}

	tenant, err := vmsrest.ResolveTenant(rest, sc)
	if err != nil {
		return nil, status.Errorf(codes.Internal,
			"failed to resolve tenant GUID via VIP pool for StorageClass %q: %v", req.StorageClass, err)
	}
	tenantGUID := tenant.Guid

	log.Info("resolved tenant GUID for StorageClass",
		zap.String("tenantGUID", tenantGUID))

	return &extensionsv1.GetReplicationTenantResponse{
		StorageClass: req.StorageClass,
		TenantGuid:   tenantGUID,
	}, nil
}

// GetReplicationInfo finds the VastStorageClassReplication or
// VastVolumeReplication that owns the given StorageClass and reports
// replication info.
func (s *Service) GetReplicationInfo(
	ctx context.Context,
	req *extensionsv1.GetReplicationInfoRequest,
) (*extensionsv1.GetReplicationInfoResponse, error) {
	if req.StorageClass == "" {
		return nil, status.Error(codes.InvalidArgument, "storage_class must not be empty")
	}

	log := s.rainbow.For("storageClass", req.StorageClass)

	vscrList, err := s.k8sClient.ListVastStorageClassReplications(ctx, req.Namespace)
	if err != nil {
		return nil, status.Error(codes.Internal, err.Error())
	}
	for _, vscr := range vscrList {
		for _, sc := range vscr.Spec.AllStorageClasses() {
			if sc == req.StorageClass {
				resp := &extensionsv1.GetReplicationInfoResponse{
					ResourceName:   vscr.Name,
					Namespace:      vscr.Namespace,
					ResourceKind:   "VastStorageClassReplication",
					IsPrimary:      vscr.Spec.PrimaryStorageClass == req.StorageClass,
					StorageClasses: vscr.Spec.AllStorageClasses(),
					FailoverType:   failoverTypeToProto(vscr.Spec.FailoverType),
				}
				log.Info("replication info resolved",
					zap.String("resource", vscr.Namespace+"/"+vscr.Name),
					zap.String("kind", resp.ResourceKind),
					zap.Bool("isPrimary", resp.IsPrimary),
					zap.Strings("storageClasses", resp.StorageClasses),
					zap.String("failoverType", resp.FailoverType.String()))
				return resp, nil
			}
		}
	}

	vvrList, err := s.k8sClient.ListVastVolumeReplications(ctx, req.Namespace)
	if err != nil {
		return nil, status.Errorf(codes.Internal, "failed to list VastVolumeReplications: %v", err)
	}
	for _, vvr := range vvrList {
		for _, sc := range vvr.Spec.AllStorageClasses() {
			if sc == req.StorageClass {
				resp := &extensionsv1.GetReplicationInfoResponse{
					ResourceName:   vvr.Name,
					Namespace:      vvr.Namespace,
					ResourceKind:   "VastVolumeReplication",
					IsPrimary:      vvr.Spec.PrimaryStorageClass == req.StorageClass,
					StorageClasses: vvr.Spec.AllStorageClasses(),
					FailoverType:   failoverTypeToProto(vvr.Spec.FailoverType),
				}
				log.Info("replication info resolved",
					zap.String("resource", vvr.Namespace+"/"+vvr.Name),
					zap.String("kind", resp.ResourceKind),
					zap.Bool("isPrimary", resp.IsPrimary),
					zap.Strings("storageClasses", resp.StorageClasses),
					zap.String("failoverType", resp.FailoverType.String()))
				return resp, nil
			}
		}
	}

	return nil, status.Errorf(codes.NotFound,
		"StorageClass %q is not part of any VastStorageClassReplication or VastVolumeReplication", req.StorageClass)
}

// failoverTypeToProto converts the CR FailoverAction to the corresponding
// proto enum value.
func failoverTypeToProto(a vastv1alpha1.FailoverAction) extensionsv1.FailoverType {
	switch a {
	case vastv1alpha1.FailoverTypeGraceful:
		return extensionsv1.FailoverType_FAILOVER_TYPE_GRACEFUL
	default:
		return extensionsv1.FailoverType_FAILOVER_TYPE_UNGRACEFUL
	}
}
