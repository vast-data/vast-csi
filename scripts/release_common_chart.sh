#!/usr/bin/env bash
# Publish charts/common to the same Helm repository that serves the public charts.
#
# The public charts are released by chart-releaser (GitHub Actions): each chart version is a
# GitHub Release named "helm-<chart>-<version>" carrying the .tgz as an asset, and the
# repository index on the pages branch points at that asset URL. This script reproduces the
# same layout for the library chart so `vast-common` resolves from the published repo.
#
# Overridable for testing:
#   GITHUB_REPO           owner/name used for the GitHub Release (default vast-data/vast-csi)
#   GIT_REMOTE            clone/push URL of the pages branch (default SSH)
#   PAGES_BRANCH          branch holding index.yaml (default gh-pages)
#   SSH_IDENTITY_FILE     path to SSH private key (sets GIT_SSH_COMMAND)
#   RELEASE_ASSET_BASE    base URL of release downloads
#   SKIP_GITHUB_RELEASE   set to 1 to skip the `gh release` call
#   DRY_RUN               set to 1 to skip the push
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHART_DIR="${ROOT}/charts/common"

GITHUB_REPO="${GITHUB_REPO:-vast-data/vast-csi}"
GIT_REMOTE="${GIT_REMOTE:-git@github.com:${GITHUB_REPO}.git}"
PAGES_BRANCH="${PAGES_BRANCH:-gh-pages}"
RELEASE_ASSET_BASE="${RELEASE_ASSET_BASE:-https://github.com/${GITHUB_REPO}/releases/download}"
SKIP_GITHUB_RELEASE="${SKIP_GITHUB_RELEASE:-0}"
DRY_RUN="${DRY_RUN:-0}"

if [[ -n "${SSH_IDENTITY_FILE:-}" ]]; then
  export GIT_SSH_COMMAND="ssh -i ${SSH_IDENTITY_FILE} -o IdentitiesOnly=yes"
  GIT_REMOTE="git@github.com:${GITHUB_REPO}.git"
fi

chart_field() {
    awk -v key="$1" '$1 == key":" { print $2; exit }' "${CHART_DIR}/Chart.yaml"
}

CHART_NAME="$(chart_field name)"
CHART_VERSION="$(chart_field version)"

if [[ -z "${CHART_NAME}" || -z "${CHART_VERSION}" ]]; then
    echo "Could not read name/version from ${CHART_DIR}/Chart.yaml" >&2
    exit 1
fi

RELEASE_TAG="helm-${CHART_NAME}-${CHART_VERSION}"
PACKAGE="${CHART_NAME}-${CHART_VERSION}.tgz"

WORKDIR="$(mktemp -d)"
trap 'rm -rf "${WORKDIR}"' EXIT
DIST="${WORKDIR}/dist"
PAGES="${WORKDIR}/pages"
mkdir -p "${DIST}"

echo "Releasing ${CHART_NAME} ${CHART_VERSION} to ${GITHUB_REPO} (${PAGES_BRANCH})"

git clone --depth 1 --branch "${PAGES_BRANCH}" "${GIT_REMOTE}" "${PAGES}"

# The library is versioned independently of the public charts, so a forgotten bump must fail
# loudly instead of silently republishing a different chart under an existing version.
if [[ -f "${PAGES}/index.yaml" ]] && CHART_NAME="${CHART_NAME}" CHART_VERSION="${CHART_VERSION}" \
        python3 -c '
import os, sys, yaml
index = yaml.safe_load(open(sys.argv[1])) or {}
entries = index.get("entries", {}).get(os.environ["CHART_NAME"], [])
sys.exit(0 if any(e.get("version") == os.environ["CHART_VERSION"] for e in entries) else 1)
' "${PAGES}/index.yaml"; then
    echo "${CHART_NAME} ${CHART_VERSION} is already published; bump charts/common/Chart.yaml" >&2
    exit 1
fi

helm package "${CHART_DIR}" --destination "${DIST}"

if [[ "${SKIP_GITHUB_RELEASE}" != "1" ]]; then
    if gh release view "${RELEASE_TAG}" --repo "${GITHUB_REPO}" >/dev/null 2>&1; then
        echo "GitHub release ${RELEASE_TAG} already exists; uploading asset if missing"
        gh release upload "${RELEASE_TAG}" "${DIST}/${PACKAGE}" \
            --repo "${GITHUB_REPO}" --clobber
    else
        gh release create "${RELEASE_TAG}" "${DIST}/${PACKAGE}" \
            --repo "${GITHUB_REPO}" \
            --title "${CHART_NAME}-${CHART_VERSION}" \
            --notes "Shared Helm template library for the VAST public charts."
    fi
fi

# Point the index entry at the release asset, matching the public charts' entries.
helm repo index "${DIST}" \
    --url "${RELEASE_ASSET_BASE}/${RELEASE_TAG}" \
    --merge "${PAGES}/index.yaml"

cp "${DIST}/index.yaml" "${PAGES}/index.yaml"

cd "${PAGES}"
if git diff --quiet -- index.yaml; then
    echo "index.yaml unchanged; nothing to publish" >&2
    exit 1
fi

git add index.yaml
git commit -m "Publish ${CHART_NAME}-${CHART_VERSION}"

if [[ "${DRY_RUN}" == "1" ]]; then
    echo "DRY_RUN=1: skipping push to ${GIT_REMOTE} ${PAGES_BRANCH}"
else
    git push origin "HEAD:${PAGES_BRANCH}"
fi

echo "Published ${CHART_NAME} ${CHART_VERSION}"
