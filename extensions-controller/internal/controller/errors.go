package controller

import (
	"errors"

	"github.com/vast-data/vast-csi/extensions-controller/internal/common"
	cerrors "github.com/vast-data/vast-csi/extensions-controller/internal/common/errors"
)

// isNetworkError is a package-local alias for common.IsNetworkError.
func isNetworkError(err error) bool { return common.IsNetworkError(err) }

// isValidationError reports whether err (or any wrapped error) is a
// *provisioner.ValidationError.
func isValidationError(err error) bool {
	var ve *cerrors.ValidationError
	return errors.As(err, &ve)
}
