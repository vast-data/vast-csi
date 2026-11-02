package cosi

const (
	SecretNameParam      = "vastdata.com/secret-name"
	SecretNamespaceParam = "vastdata.com/secret-namespace"

	// AnnotationFlatten enables Rook-style flat credential Secret/ConfigMap creation.
	AnnotationFlatten = "cosi.vastdata.com/flatten-credentials"
	// LabelBucketAccessUID marks Secret/ConfigMap created by the flattener for a BucketAccess.
	LabelBucketAccessUID = "cosi.vastdata.com/bucketaccess-uid"
	// BucketInfoKey is the COSI credentials Secret data key holding BucketInfo JSON.
	BucketInfoKey = "BucketInfo"
	// SecretProtectionFinalizer is the stock objectstorage-sidecar finalizer on
	// credentials Secrets. Must be cleared or Delete stalls in Terminating.
	SecretProtectionFinalizer = "cosi.objectstorage.k8s.io/secret-protection"
	// BucketClaimProtectionFinalizer is the stock objectstorage-controller
	// finalizer on BucketClaims. Stock COSI may skip adding it when a sidecar
	// race marks the claim ready before the controller finishes reconcile.
	BucketClaimProtectionFinalizer = "cosi.objectstorage.k8s.io/bucketclaim-protection"
)
