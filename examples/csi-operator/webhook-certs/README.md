# Webhook TLS certificate test environment

End-to-end environment for validating the extension controller admission webhook TLS
stack installed via a `VastCSIDriver` CR (Helm self-signed certs — the default path).

This does **not** require a working VAST backend. Certificate checks and admission
webhook calls only need the operator, extension controller, and Kubernetes API server.

## What gets tested

| Layer | Check |
|-------|--------|
| Secret | `tls.crt`, `tls.key`, `ca.crt` present |
| Certificate | CN/SAN match `{release}-vast-extension-controller-webhook.{ns}.svc` |
| Trust chain | `MutatingWebhookConfiguration.caBundle` == secret `ca.crt` |
| Pod mount | `extensions-webhook` mounts secret at `/tmp/k8s-webhook-server/serving-certs` |
| TLS | In-cluster `openssl s_client` to webhook Service :443 |
| Admission | PVC `CREATE` succeeds (no `x509` / webhook TLS errors) |

> **Note:** With `certManager.enabled: true`, Helm does **not** create `Issuer` or `Certificate`
> CRs — install those separately from [`cert-manager/`](cert-manager/). Helm only mounts the
> resulting Secret and annotates `MutatingWebhookConfiguration` for cainjector.

## Cert-manager mode (production-style)

```bash
cd examples/csi-operator/webhook-certs

# Full end-to-end: install cert-manager, apply Issuer+Certificate, helm upgrade, verify
./scripts/setup-cert-manager.sh

# Restore Helm self-signed mode
helm upgrade csi.vastdata.com ../../charts/vastcsi-operator/crd-charts/vastcsidriver -n vast-csi \
  --reuse-values --set extensions.webhook.certManager.enabled=false
kubectl apply -f manifests/01-vastcsidriver.yaml
```

## Prerequisites

1. Kubernetes cluster with `kubectl` access.
2. **VAST CSI Operator** installed in `vast-csi` — see [`../deploy/README.md`](../deploy/README.md).
3. Pull secret if using private images (e.g. ECR):
   ```bash
   kubectl create secret docker-registry regcred \
     --docker-server=<registry> --docker-username=AWS \
     --docker-password=$(aws ecr get-login-password) \
     -n vast-csi --dry-run=client -o yaml | kubectl apply -f -
   ```

## Quick start

```bash
cd examples/csi-operator/webhook-certs

# 1. Edit image tags in manifests/01-vastcsidriver.yaml if needed.

# 2. Install driver with extensions (webhook enabled by default)
./scripts/setup.sh

# 3. Run all certificate + admission checks
./scripts/verify-webhook-certs.sh --functional

# 4. Cleanup test resources (keeps VastCSIDriver unless --all)
./scripts/teardown.sh
```

## Layout

| Path | Purpose |
|------|---------|
| `manifests/01-vastcsidriver.yaml` | NFS driver + extensions (webhook on, replication off for a lighter stack) |
| `manifests/02-test-namespace.yaml` | Isolated namespace for webhook PVC tests |
| `manifests/03-test-storageclass-pvc.yaml` | Fake StorageClass + PVC to trigger `/mutate-pvc` |
| `scripts/setup.sh` | Apply manifests and wait for extension controller |
| `scripts/verify-webhook-certs.sh` | Static TLS checks; `--functional` runs admission test |
| `scripts/teardown.sh` | Remove test namespace/PVC; optional `--all` deletes VastCSIDriver |

## Manual verification

```bash
export DRIVER_NS=vast-csi
export DRIVER_NAME=csi.vastdata.com
./scripts/verify-webhook-certs.sh

# Inspect resources directly
DNS_SAFE=$(echo "$DRIVER_NAME" | tr '.' '-')
kubectl get secret,svc,mutatingwebhookconfiguration -n "$DRIVER_NS" | grep "$DNS_SAFE"

kubectl get secret "${DNS_SAFE}-vast-extension-controller-webhook-tls" -n "$DRIVER_NS" \
  -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -text
```

## Negative test (optional, test clusters only)

Break webhook trust and confirm admission fails:

```bash
DNS_SAFE=$(echo csi.vastdata.com | tr '.' '-')
kubectl patch mutatingwebhookconfiguration "${DNS_SAFE}-vast-extension-controller-webhook" \
  --type=json -p='[{"op":"replace","path":"/webhooks/0/clientConfig/caBundle","value":"YQ=="}]'

kubectl apply -f manifests/03-test-storageclass-pvc.yaml   # should fail with TLS/x509 error

# Restore by re-applying the driver or running setup.sh again
./scripts/setup.sh
```

## Troubleshooting

| Symptom | Likely cause |
|---------|----------------|
| No TLS secret | `extensions.enabled` false or helm reconcile error — check operator logs |
| `caBundle` mismatch | Upgrade regenerated cert but not webhook config — delete secret and reconcile |
| PVC fails `x509` | Secret not mounted or Service DNS doesn't match cert SAN |
| Webhook pod not ready | Check `extensions-webhook` logs; cert path must be `/tmp/k8s-webhook-server/serving-certs` |
