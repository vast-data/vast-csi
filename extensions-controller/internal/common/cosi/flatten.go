package cosi

import (
	"encoding/json"
	"fmt"
	"net/url"
	"strings"
)

// FlatData holds Rook-style flat credential fields derived from BucketInfo JSON.
type FlatData struct {
	AccessKeyID     string
	SecretAccessKey string
	BucketName      string
	Endpoint        string
	Host            string
	Port            string
}

type bucketInfo struct {
	Spec struct {
		BucketName string `json:"bucketName"`
		SecretS3   struct {
			AccessKeyID     string `json:"accessKeyID"`
			AccessSecretKey string `json:"accessSecretKey"`
			Endpoint        string `json:"endpoint"`
		} `json:"secretS3"`
	} `json:"spec"`
}

// WantFlatten is true only when the annotation value is exactly "true".
func WantFlatten(annotations map[string]string) bool {
	if annotations == nil {
		return false
	}
	return annotations[AnnotationFlatten] == "true"
}

// FlatName returns the sibling Secret/ConfigMap name for a credentials secret.
func FlatName(credentialsSecretName string) string {
	return credentialsSecretName + "-flat"
}

// ParseBucketInfo parses locked COSI v1alpha1 / Rook-shaped BucketInfo JSON.
func ParseBucketInfo(raw []byte) (FlatData, error) {
	var bi bucketInfo
	if err := json.Unmarshal(raw, &bi); err != nil {
		return FlatData{}, fmt.Errorf("parse BucketInfo: %w", err)
	}
	s3 := bi.Spec.SecretS3
	if bi.Spec.BucketName == "" || s3.AccessKeyID == "" || s3.AccessSecretKey == "" || s3.Endpoint == "" {
		return FlatData{}, fmt.Errorf("BucketInfo incomplete: need spec.bucketName and spec.secretS3.{accessKeyID,accessSecretKey,endpoint}")
	}
	endpoint := normalizeEndpoint(s3.Endpoint)
	host, port, err := SplitEndpoint(endpoint)
	if err != nil {
		return FlatData{}, err
	}
	return FlatData{
		AccessKeyID:     s3.AccessKeyID,
		SecretAccessKey: s3.AccessSecretKey,
		BucketName:      bi.Spec.BucketName,
		Endpoint:        endpoint,
		Host:            host,
		Port:            port,
	}, nil
}

// SplitEndpoint returns host and port from an S3 endpoint URL.
// Default ports: http→80, https→443 when port is omitted.
func SplitEndpoint(endpoint string) (host, port string, err error) {
	u, err := url.Parse(normalizeEndpoint(endpoint))
	if err != nil {
		return "", "", fmt.Errorf("parse endpoint: %w", err)
	}
	if u.Host == "" {
		return "", "", fmt.Errorf("endpoint missing host: %q", endpoint)
	}
	h := u.Hostname()
	if h == "" {
		return "", "", fmt.Errorf("endpoint missing host: %q", endpoint)
	}
	p := u.Port()
	if p == "" {
		switch strings.ToLower(u.Scheme) {
		case "https":
			p = "443"
		case "http", "":
			p = "80"
		default:
			return "", "", fmt.Errorf("endpoint missing port for scheme %q", u.Scheme)
		}
	}
	return h, p, nil
}

func normalizeEndpoint(endpoint string) string {
	endpoint = strings.TrimSpace(endpoint)
	if strings.HasPrefix(endpoint, "://") {
		return "http" + endpoint
	}
	if !strings.Contains(endpoint, "://") {
		return "http://" + endpoint
	}
	return endpoint
}
