package vmsrest

import (
	"context"
	"net/http"

	vast_client "github.com/vast-data/go-vast-client"
	"github.com/vast-data/go-vast-client/resources/typed"
)

// PathExists reports whether path exists on the cluster reached via rest.
//
// POST /folders/stat_path returns HTTP 503 when the path is absent; that is
// treated as exists=false with a nil error. Any other error is returned to the
// caller.
func PathExists(ctx context.Context, rest *vast_client.TypedVMSRest, path string, tenantId int64) (bool, error) {
	stat, err := StatPath(ctx, rest, path, tenantId)
	if err != nil {
		return false, err
	}
	return stat != nil, nil
}

// StatPath calls POST /folders/stat_path and returns folder attributes.
//
// When the path is absent the VMS API responds with HTTP 503; StatPath returns
// (nil, nil) in that case. Any other error is returned to the caller.
func StatPath(ctx context.Context, rest *vast_client.TypedVMSRest, path string, tenantId int64) (*typed.FolderStatPath_POST_Model, error) {
	stat, err := rest.Folders.FolderStatPathWithContext_POST(ctx, path, tenantId)
	if err == nil {
		return stat, nil
	}
	if vast_client.ExpectStatusCodes(err, http.StatusServiceUnavailable) {
		return nil, nil
	}
	return nil, err
}

// DeleteFolder calls DELETE /folders/delete_folder/ for path on the given tenant.
func DeleteFolder(ctx context.Context, rest *vast_client.TypedVMSRest, path string, tenantId int64) error {
	return rest.Folders.FolderDeleteFolderWithContext_DELETE(ctx, path, tenantId)
}
