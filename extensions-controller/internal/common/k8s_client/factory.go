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
	"github.com/pkg/errors"
	"github.com/spf13/pflag"
	vastv1alpha1 "github.com/vast-data/vast-csi/extensions-controller/api/v1alpha1"
	"go.uber.org/zap"
	"k8s.io/apimachinery/pkg/runtime"
	utilruntime "k8s.io/apimachinery/pkg/util/runtime"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	"k8s.io/client-go/rest"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/apiutil"
)

// Factory knows how to create a K8sClient for both in-cluster and local usage.
//
// For controller usage (in-cluster):
//
//	factory := k8s_client.NewFactory("extensions-controller")
//	k8sClient, err := factory.K8sClientForController(mgr.GetClient(), logger)
//
// For CLI usage (cobra integration, mirrors the velero pattern):
//
//	factory := k8s_client.NewFactory("vastrep")
//	factory.BindFlags(rootCmd.PersistentFlags()) // registers --kubeconfig, --kubecontext
//	// cobra parses the flags; then:
//	k8sClient, err := factory.K8sClientForLocal(logger)
type Factory interface {
	// BindFlags merges the factory's own connection flags (--kubeconfig, --kubecontext)
	// into the provided FlagSet so cobra can populate them from the command line.
	// Call this once during command construction, before cobra parses args.
	BindFlags(flags *pflag.FlagSet)
	// ClientConfig returns a rest.Config built from the factory's current settings.
	// Priority: --kubeconfig flag → KUBECONFIG env var → in-cluster config.
	ClientConfig() (*rest.Config, error)
	// K8sClientForController wraps an existing controller-runtime client (operator mode).
	K8sClientForController(controllerClient client.Client, logger *zap.Logger) (*K8sClient, error)
	// K8sClientForLocal builds a new client from kubeconfig (CLI mode).
	K8sClientForLocal(logger *zap.Logger) (*K8sClient, error)
	// SetKubeconfig overrides the kubeconfig path programmatically.
	SetKubeconfig(path string)
	// SetKubecontext overrides the kubecontext programmatically.
	SetKubecontext(context string)
	// SetClientQPS sets the Queries Per Second for the client.
	SetClientQPS(qps float32)
	// SetClientBurst sets the Burst for the client.
	SetClientBurst(burst int)
}

type factory struct {
	flags       *pflag.FlagSet
	kubeconfig  string
	kubecontext string
	baseName    string
	clientQPS   float32
	clientBurst int
}

// NewFactory returns a Factory for creating K8sClient instances.
// baseName is used as the HTTP User-Agent string.
// Connection flags (--kubeconfig, --kubecontext) are registered into an
// internal FlagSet; call BindFlags to expose them on a cobra command.
func NewFactory(baseName string) Factory {
	f := &factory{
		flags:    pflag.NewFlagSet("", pflag.ContinueOnError),
		baseName: baseName,
	}
	f.flags.StringVar(&f.kubeconfig, "kubeconfig", "",
		"Path to the kubeconfig file to use to talk to the Kubernetes apiserver. "+
			"If unset, try the environment variable KUBECONFIG, as well as in-cluster configuration.")
	f.flags.StringVar(&f.kubecontext, "kubecontext", "",
		"The context to use to talk to the Kubernetes apiserver. "+
			"If unset defaults to whatever your current-context is (kubectl config current-context).")
	return f
}

// BindFlags merges the factory's connection flags into flags so cobra can parse them.
func (f *factory) BindFlags(flags *pflag.FlagSet) {
	flags.AddFlagSet(f.flags)
}

func (f *factory) ClientConfig() (*rest.Config, error) {
	return Config(f.kubeconfig, f.kubecontext, f.baseName, f.clientQPS, f.clientBurst)
}

func (f *factory) K8sClientForController(controllerClient client.Client, logger *zap.Logger) (*K8sClient, error) {
	return NewK8sClient(controllerClient, logger), nil
}

func (f *factory) K8sClientForLocal(logger *zap.Logger) (*K8sClient, error) {
	config, err := f.ClientConfig()
	if err != nil {
		return nil, errors.Wrap(err, "failed to get client config")
	}

	scheme := runtime.NewScheme()
	utilruntime.Must(clientgoscheme.AddToScheme(scheme))
	utilruntime.Must(vastv1alpha1.AddToScheme(scheme))

	httpClient, err := rest.HTTPClientFor(config)
	if err != nil {
		return nil, errors.Wrap(err, "failed to create HTTP client")
	}

	mapper, err := apiutil.NewDynamicRESTMapper(config, httpClient)
	if err != nil {
		return nil, errors.Wrap(err, "failed to create REST mapper")
	}

	controllerClient, err := client.New(config, client.Options{
		Scheme: scheme,
		Mapper: mapper,
	})
	if err != nil {
		return nil, errors.Wrap(err, "failed to create controller client")
	}

	return NewK8sClient(controllerClient, logger), nil
}

func (f *factory) SetKubeconfig(path string) { f.kubeconfig = path }
func (f *factory) SetKubecontext(ctx string) { f.kubecontext = ctx }
func (f *factory) SetClientQPS(qps float32)  { f.clientQPS = qps }
func (f *factory) SetClientBurst(burst int)  { f.clientBurst = burst }
