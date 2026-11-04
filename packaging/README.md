# Packaging images

Build and push packaging images with [`scripts/build_images.py`](../scripts/build_images.py).
Each build is a `--build` unit: comma-separated `key=value` params.

## Make

### Single image (env vars → one `--build`)

```bash
export IMAGE_TAG=.../dev/vast-csi:local
export DOCKERFILE=Dockerfile   # bare name → packaging/Dockerfile
export CSI_BASE=.../dev/vast-csi-base:2026-10-08   # optional; → base=
export DEBIAN_BASE=            # optional; → debian= (GKE base build)
export PLATFORMS=              # empty = plain docker; set → buildx --push
export CACHE_FROM=
export PUSH_ON_SUCCESS=false
export NO_CACHE=false          # true/1/yes → --no-cache

make build_image
```

Buildx builds always pass `--provenance=false --sbom=false` so the pushed OCI
index has only platform manifests (no attestation children). That avoids
oc-mirror / `skopeo copy --all` failures against Red Hat Connect when
attestation digests are listed but missing (VCSI-705).

### Multiple images (ready-made `--build` flags, parallel)

```bash
# Distroless = default tag; UBI = :<tag>-ubi (OpenShift / operator)
make build_images BUILD_ARGS='--build image=.../vast-csi:1,dockerfile=Dockerfile,base=$CSI_BASE_DISTROLESS,push=false --build image=.../vast-csi:1-ubi,dockerfile=Dockerfile,base=$CSI_BASE,push=false'
```

`DOCKERFILE` resolution:
- bare name (e.g. `Dockerfile`, `operator.Dockerfile`) → `packaging/<name>`
- absolute path → use as-is
- relative path with `/` (e.g. `extensions-controller/Dockerfile`) → repo-root relative

## CLI

```bash
python3 scripts/build_images.py \
  --build image=.../vast-csi:123,base=.../vast-csi:base-distroless-2026-11-02,dockerfile=Dockerfile,push=false \
  --build image=.../vast-csi:123-ubi,base=.../vast-csi-base:2026-10-08,dockerfile=Dockerfile,push=false

python3 scripts/build_images.py --list \
  --build image=repo/csi:1,base=repo/base:1,dockerfile=Dockerfile,push=false
```

**Params per `--build`:**

| Key | Required | Meaning |
|-----|----------|---------|
| `image=` | yes | Output image tag |
| `dockerfile=` | yes | See resolution rules above |
| `base=` | no | FROM image → build-arg `BASE_IMAGE` |
| `debian=` | no | Debian builder → build-arg `DEBIAN_BASE` |
| `cache=` | no | `--cache-from` |
| `platforms=` | no | buildx platforms; implies registry `--push` |
| `push=` | no | `true`\|`false` after plain docker build (default `false`) |
| `context=` | no | Build context (default `.`) |

**Env (all `--build` units):** `NO_CACHE=true|1|yes` → `--no-cache` on docker/buildx.

## Dockerfiles

| `DOCKERFILE` | Typical `base=` / `debian=` |
|--------------|------------------------------|
| `base.Dockerfile` | (omit; UBI hardcoded) |
| `base-distroless.Dockerfile` | `debian=` `gke.gcr.io/debian-base:…`, `base=` `gke.gcr.io/gke-distroless/libc:…` |
| `Dockerfile` | pinned `CSI_BASE_DISTROLESS` (default release) or `CSI_BASE` (UBI / `:…-ubi`) |
| `operator-base.Dockerfile` | (omit) |
| `operator.Dockerfile` | `OPERATOR_BASE` (as `base=` / Make `CSI_BASE`) |
| `extensions-controller/Dockerfile` | (omit) |

## CSI image tags

| Flavor | Where | Tag |
|--------|-------|-----|
| Distroless (default) | Docker Hub, ECR | `:<pipe>` / `:VERSION` / `:latest` |
| UBI | ECR (CI only) | `:<pipe>-ubi` / `:latest-ubi` |
| UBI | Red Hat Connect | `:VERSION` (certification; not published to Docker Hub) |

## Distroless base

Multi-stage: **gke-debian** builder → **gke-distroless** final.

| Role | Registry | Example tag |
|------|----------|-------------|
| Builder (`debian=`) | `gke.gcr.io/debian-base` | `bookworm-v1.0.8-gke.12` (also `latest`) |
| Final (`base=`) | `gke.gcr.io/gke-distroless/libc` | `gke_distroless_20260928.00_p0` (also `latest`) |

Note: `gke.gcr.io/gke-distroless:latest` does **not** exist — pull a **child**
image (`libc`, `static`, `bash`, …). Python is copied from the debian-base
builder into the distroless final (libc image has no interpreter).

```bash
# Prefer ECR mirrors (CI defaults); upstream gke.gcr.io works locally too.
export DEBIAN_BASE=${AWS_ACCOUNT_ID}.dkr.ecr.eu-west-1.amazonaws.com/dev/vast-csi:bookworm-v1.0.8-gke.12
export CSI_BASE=${AWS_ACCOUNT_ID}.dkr.ecr.eu-west-1.amazonaws.com/dev/vast-csi:gke_distroless_20260928.00_p0

export IMAGE_TAG=.../vast-csi:base-distroless-$(date +%Y-%m-%d)
export DOCKERFILE=base-distroless.Dockerfile
export PUSH_ON_SUCCESS=true
make build_image
# then pin CSI_BASE_DISTROLESS in .gitlab-ci.yml to $IMAGE_TAG
```
