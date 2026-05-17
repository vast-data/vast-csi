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

// isPermanentError reports whether err is a permanent, non-transient failure
// that requires user intervention.  Specifically it returns true for errors
// that are neither network errors (temporary connectivity loss) nor retryable
// errors (transient VAST states such as an initialising protected path).
func isPermanentError(err error) bool {
	if err == nil {
		return false
	}
	if isNetworkError(err) {
		return false
	}
	var retryable cerrors.Retryable
	return !errors.As(err, &retryable)
}
