package flatten

import (
	"strings"
	"testing"
)

const happyBucketInfo = `{
  "spec": {
    "bucketName": "my-bucket",
    "authenticationType": "KEY",
    "secretS3": {
      "accessKeyID": "AKIAEXAMPLE",
      "accessSecretKey": "secret",
      "endpoint": "http://172.0.0.1:80"
    }
  }
}`

func TestWantFlatten(t *testing.T) {
	tests := []struct {
		name string
		ann  map[string]string
		want bool
	}{
		{"exact true", map[string]string{AnnotationFlatten: "true"}, true},
		{"True rejected", map[string]string{AnnotationFlatten: "True"}, false},
		{"1 rejected", map[string]string{AnnotationFlatten: "1"}, false},
		{"empty value", map[string]string{AnnotationFlatten: ""}, false},
		{"missing", nil, false},
		{"other key", map[string]string{"other": "true"}, false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := WantFlatten(tt.ann); got != tt.want {
				t.Fatalf("WantFlatten() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestFlatName(t *testing.T) {
	if got := FlatName("sample-access-secret"); got != "sample-access-secret-flat" {
		t.Fatalf("FlatName() = %q", got)
	}
}

func TestParseBucketInfo_happy(t *testing.T) {
	got, err := ParseBucketInfo([]byte(happyBucketInfo))
	if err != nil {
		t.Fatalf("ParseBucketInfo: %v", err)
	}
	want := FlatData{
		AccessKeyID:     "AKIAEXAMPLE",
		SecretAccessKey: "secret",
		BucketName:      "my-bucket",
		Endpoint:        "http://172.0.0.1:80",
		Host:            "172.0.0.1",
		Port:            "80",
	}
	if got != want {
		t.Fatalf("got %#v, want %#v", got, want)
	}
}

func TestParseBucketInfo_httpsEndpoint(t *testing.T) {
	raw := strings.Replace(happyBucketInfo, "http://172.0.0.1:80", "https://vip.example:443", 1)
	got, err := ParseBucketInfo([]byte(raw))
	if err != nil {
		t.Fatalf("ParseBucketInfo: %v", err)
	}
	if got.Endpoint != "https://vip.example:443" || got.Host != "vip.example" || got.Port != "443" {
		t.Fatalf("endpoint split wrong: %#v", got)
	}
}

func TestParseBucketInfo_malformedEndpoint(t *testing.T) {
	raw := strings.Replace(happyBucketInfo, "http://172.0.0.1:80", "://11.0.0.102:80", 1)
	got, err := ParseBucketInfo([]byte(raw))
	if err != nil {
		t.Fatalf("ParseBucketInfo: %v", err)
	}
	if got.Endpoint != "http://11.0.0.102:80" || got.Host != "11.0.0.102" || got.Port != "80" {
		t.Fatalf("malformed endpoint normalize wrong: %#v", got)
	}
}

func TestParseBucketInfo_badJSON(t *testing.T) {
	cases := [][]byte{
		[]byte(``),
		[]byte(`not-json`),
		[]byte(`{}`),
		[]byte(`{"spec":{}}`),
		[]byte(`{"spec":{"bucketName":"b","secretS3":{"accessKeyID":"a","accessSecretKey":"s"}}}`),
	}
	for i, raw := range cases {
		if _, err := ParseBucketInfo(raw); err == nil {
			t.Fatalf("case %d: expected error", i)
		}
	}
}

func TestSplitEndpoint(t *testing.T) {
	host, port, err := SplitEndpoint("http://172.0.0.1:80")
	if err != nil || host != "172.0.0.1" || port != "80" {
		t.Fatalf("got %q %q %v", host, port, err)
	}
	host, port, err = SplitEndpoint("https://vip.example:443")
	if err != nil || host != "vip.example" || port != "443" {
		t.Fatalf("got %q %q %v", host, port, err)
	}
	host, port, err = SplitEndpoint("http://vip.example")
	if err != nil || host != "vip.example" || port != "80" {
		t.Fatalf("default http port: got %q %q %v", host, port, err)
	}
	host, port, err = SplitEndpoint("https://vip.example")
	if err != nil || host != "vip.example" || port != "443" {
		t.Fatalf("default https port: got %q %q %v", host, port, err)
	}
	host, port, err = SplitEndpoint("://11.0.0.102:80")
	if err != nil || host != "11.0.0.102" || port != "80" {
		t.Fatalf("scheme-missing-prefix endpoint: got %q %q %v", host, port, err)
	}
	host, port, err = SplitEndpoint("11.0.0.102:80")
	if err != nil || host != "11.0.0.102" || port != "80" {
		t.Fatalf("scheme-missing endpoint: got %q %q %v", host, port, err)
	}
}
