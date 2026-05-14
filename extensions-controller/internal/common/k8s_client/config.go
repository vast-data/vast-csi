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

package k8s_client

import (
	"fmt"

	"github.com/pkg/errors"
	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/clientcmd"
)

// Config returns a *rest.Config, using either the kubeconfig (if specified) or an in-cluster
// configuration. It uses the following priority to specify the cluster configuration:
// 1. kubeconfig parameter
// 2. KUBECONFIG environment variable
// 3. In-cluster configuration
func Config(kubeconfig, kubecontext, baseName string, qps float32, burst int) (*rest.Config, error) {
	loadingRules := clientcmd.NewDefaultClientConfigLoadingRules()
	loadingRules.ExplicitPath = kubeconfig
	configOverrides := &clientcmd.ConfigOverrides{CurrentContext: kubecontext}
	kubeConfig := clientcmd.NewNonInteractiveDeferredLoadingClientConfig(loadingRules, configOverrides)

	clientConfig, err := kubeConfig.ClientConfig()
	if err != nil {
		return nil, errors.Wrap(err, "error finding Kubernetes API server config in --kubeconfig, $KUBECONFIG, or in-cluster configuration")
	}

	if qps > 0.0 {
		clientConfig.QPS = qps
	}
	if burst > 0 {
		clientConfig.Burst = burst
	}

	if baseName != "" {
		clientConfig.UserAgent = buildUserAgent(
			baseName,
			"",
			"",
		)
	}

	return clientConfig, nil
}

// buildUserAgent builds a User-Agent string from given args.
func buildUserAgent(command, version, formattedSha string) string {
	if version == "" && formattedSha == "" {
		return command
	}
	if formattedSha == "" {
		return fmt.Sprintf("%s/%s", command, version)
	}
	return fmt.Sprintf("%s/%s (%s)", command, version, formattedSha)
}
