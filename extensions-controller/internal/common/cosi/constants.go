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
)
