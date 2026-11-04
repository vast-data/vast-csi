#!/usr/bin/env python3
"""Build and optionally push VAST CSI packaging images.

Each build unit is a repeatable --build flag with comma-separated key=value
params:

    python3 scripts/build_images.py \\
      --build image=repo/csi:123,base=repo/base:tag,dockerfile=Dockerfile \\
      --build image=repo/vast-csi:base-distroless-tag,base=gke.gcr.io/gke-distroless/libc:latest,debian=gke.gcr.io/debian-base:bookworm-v1.0.8-gke.12,dockerfile=base-distroless.Dockerfile,push=true

Params per --build:
    image=       (required) output image tag
    dockerfile=  (required) bare name → packaging/<name>; absolute path → as-is;
                 relative path with / → repo-root relative
    base=        (optional) FROM image; passed as build-arg BASE_IMAGE
    debian=      (optional) Debian builder image; passed as build-arg DEBIAN_BASE
    context=     (optional) build context (default: .)
    cache=       (optional) --cache-from value
    platforms=   (optional) buildx platforms (implies registry --push)
    push=        (optional) true|false; push after plain docker build (default: false)

Multiple --build flags run in parallel across distinct Dockerfiles.

Environment / globals:
    CONTAINER_RUNTIME, PARALLEL_BUILDS, DEBUG,
    CI_COMMIT_SHA / GIT_TAG / CI_PIPELINE_ID,
    NO_CACHE (true/1/yes → pass --no-cache to docker/buildx)

Buildx always passes --provenance=false --sbom=false so the OCI index has only
platform manifests (no attestation children). Red Hat Connect often publishes
indexes without those blobs; oc-mirror / skopeo copy --all then fail (VCSI-705).
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import uuid

# ── ANSI ─────────────────────────────────────────────────────────────────────

GREEN = "\033[0;32m"
RED = "\033[0;31m"
BLUE = "\033[0;34m"
YELLOW = "\033[1;33m"
NC = "\033[0m"

# ── Paths / config ────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGING = REPO_ROOT / "packaging"

RUNTIME = os.environ.get("CONTAINER_RUNTIME", "docker")
DEBUG = os.environ.get("DEBUG", "0") == "1"
PARALLEL = os.environ.get("PARALLEL_BUILDS", "true").lower() == "true"

os.environ.setdefault("DOCKER_BUILDKIT", "1")

ALLOWED_BUILD_KEYS = frozenset(
    {"image", "base", "debian", "dockerfile", "context", "cache", "platforms", "push"}
)


class ImageSpec:
    def __init__(
        self,
        name: str,
        tag: str,
        dockerfile: str,
        context: str = ".",
        build_args: Optional[Dict[str, str]] = None,
        cache_from: str = "",
        platforms: str = "",
        push: bool = False,
    ):
        self.name = name
        self.tag = tag
        self.dockerfile = dockerfile
        self.context = context
        self.build_args = build_args or {}
        self.cache_from = cache_from
        self.platforms = platforms
        self.push = push

    @property
    def short_name(self) -> str:
        return self.name or self.tag.rsplit("/", 1)[-1]


class BuildResult:
    def __init__(
        self, spec: ImageSpec, status: str, duration: float = 0.0, exit_code: int = 0
    ):
        self.spec = spec
        self.status = status  # built | failed
        self.duration = duration
        self.exit_code = exit_code


def _run(cmd: List[str], **kw) -> "subprocess.CompletedProcess[str]":
    kw.setdefault("stdout", subprocess.PIPE)
    kw.setdefault("stderr", subprocess.PIPE)
    kw.setdefault("universal_newlines", True)
    return subprocess.run(cmd, **kw)


def log(msg: str, color: str = YELLOW) -> None:
    print(f"{color}{msg}{NC}", flush=True)


def resolve_dockerfile(dockerfile: str) -> Path:
    """Resolve dockerfile path.

    - Absolute path: use as-is.
    - Bare name (no directory): packaging/<name>.
    - Relative path with separators: repo-root relative.
    """
    raw = dockerfile.strip()
    if not raw:
        raise FileNotFoundError("Dockerfile path is empty")

    p = Path(raw)
    if p.is_absolute():
        if p.is_file():
            return p.resolve()
        raise FileNotFoundError(f"Dockerfile not found: {raw}")

    if p.name == raw or (os.sep not in raw and "/" not in raw):
        candidate = PACKAGING / p.name
        if candidate.is_file():
            return candidate.resolve()
        raise FileNotFoundError(
            f"Dockerfile not found: {raw} (looked in {PACKAGING / p.name})"
        )

    # Relative path (e.g. extensions-controller/Dockerfile)
    candidate = REPO_ROOT / raw
    if candidate.is_file():
        return candidate.resolve()
    raise FileNotFoundError(f"Dockerfile not found: {raw} (looked in {candidate})")


def read_version() -> str:
    vf = REPO_ROOT / "version.txt"
    if not vf.is_file() or not vf.read_text().strip():
        raise RuntimeError("version.txt does not exist or is empty.")
    return vf.read_text().strip()


def git_commit() -> str:
    return (
        os.environ.get("CI_COMMIT_SHA")
        or _run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"]).stdout.strip()
    )


def git_tag(version: str) -> str:
    return os.environ.get("GIT_TAG") or version


def common_build_args(version: str) -> Dict[str, str]:
    return {
        "GIT_COMMIT": git_commit(),
        "GIT_TAG": git_tag(version),
        "VERSION": version,
        "CI_PIPELINE_ID": os.environ.get("CI_PIPELINE_ID", "local"),
    }


# ── Build ─────────────────────────────────────────────────────────────────────


def _env_truthy(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in ("true", "1", "yes")


def _no_cache_flags() -> List[str]:
    if _env_truthy("NO_CACHE"):
        log("INFO: NO_CACHE set: building without layer cache", BLUE)
        return ["--no-cache"]
    return []


def _ensure_buildx_builder() -> None:
    if _run([RUNTIME, "buildx", "inspect", "builder"]).returncode != 0:
        log("INFO: Creating buildx builder instance", BLUE)
        subprocess.run(
            [RUNTIME, "buildx", "create", "--name", "builder", "--use"],
            check=True,
        )
    else:
        log("INFO: Using existing buildx builder", BLUE)


def _prepare_app_dockerfile(
    context: str, args: Dict[str, str]
) -> Tuple[Path, Path]:
    """Unique version.info + Dockerfile so parallel app builds do not race.

    packaging/Dockerfile has no shell (Distroless-safe); version.info is written
    on the host and COPY'd in. Each parallel unit gets its own filenames.
    """
    uid = uuid.uuid4().hex[:12]
    ver_name = f"version.info.build.{uid}"
    ver_path = Path(context) / ver_name
    name = args.get("NAME", "csi.vastdata.com")
    ver_path.write_text(
        f"{name} {args.get('VERSION', '')} {args.get('GIT_COMMIT', '')} "
        f"{args.get('CI_PIPELINE_ID', 'local')}\n"
    )

    src = (PACKAGING / "Dockerfile").read_text()
    needle = "COPY version.info.build version.info"
    if needle not in src:
        ver_path.unlink(missing_ok=True)
        raise SystemExit(
            f"packaging/Dockerfile must contain '{needle}' for host-generated version.info"
        )
    df_path = Path(context) / f"Dockerfile.app.{uid}"
    df_path.write_text(src.replace(needle, f"COPY {ver_name} version.info", 1))
    return ver_path, df_path


def build_image(spec: ImageSpec, version: str) -> int:
    dockerfile = resolve_dockerfile(spec.dockerfile)
    context = spec.context
    if not os.path.isabs(context):
        context = str(REPO_ROOT / context)

    args = dict(common_build_args(version))
    args.update({k: v for k, v in spec.build_args.items() if v is not None and v != ""})

    build_arg_flags: List[str] = []
    for k, v in args.items():
        build_arg_flags.extend(["--build-arg", f"{k}={v}"])

    cache_flags: List[str] = []
    if spec.cache_from:
        cache_flags = ["--cache-from", spec.cache_from]

    cleanup: List[Path] = []
    if dockerfile.resolve() == (PACKAGING / "Dockerfile").resolve():
        ver_path, df_path = _prepare_app_dockerfile(context, args)
        cleanup.extend([ver_path, df_path])
        dockerfile = df_path

    no_cache = _no_cache_flags()
    if spec.platforms:
        _ensure_buildx_builder()
        # Omit attestation manifests from the OCI index (VCSI-705 / RH Connect).
        cmd = [
            RUNTIME,
            "buildx",
            "build",
            "--platform",
            spec.platforms,
            "--provenance=false",
            "--sbom=false",
            *no_cache,
            "-t",
            spec.tag,
            *cache_flags,
            *build_arg_flags,
            "-f",
            str(dockerfile),
            "--push",
            context,
        ]
    else:
        cmd = [
            RUNTIME,
            "build",
            *no_cache,
            "-t",
            spec.tag,
            *cache_flags,
            *build_arg_flags,
            "-f",
            str(dockerfile),
            context,
        ]

    log(f"INFO: Building {spec.short_name} -> {spec.tag}", BLUE)
    log(f"  --build {format_build_unit(spec)}", BLUE)
    try:
        if DEBUG:
            print(" ".join(cmd), flush=True)
            return subprocess.run(cmd).returncode

        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"{RED}Build failed for {spec.tag}{NC}", file=sys.stderr)
            if r.stdout:
                print(r.stdout, file=sys.stderr)
            if r.stderr:
                print(r.stderr, file=sys.stderr)
        return r.returncode
    finally:
        for p in cleanup:
            p.unlink(missing_ok=True)



def _push(name: str) -> None:
    log(f"INFO: Pushing {name}", BLUE)
    subprocess.run([RUNTIME, "push", name], check=True)


def ensure_image(spec: ImageSpec, version: str) -> BuildResult:
    t0 = time.monotonic()
    rc = build_image(spec, version)
    dur = time.monotonic() - t0
    if rc != 0:
        return BuildResult(spec, "failed", dur, rc)

    # buildx --push already published; plain build may push on request
    if not spec.platforms and spec.push:
        try:
            _push(spec.tag)
        except subprocess.CalledProcessError:
            return BuildResult(spec, "failed", time.monotonic() - t0, 1)

    return BuildResult(spec, "built", dur)


# Split only on commas that introduce another known key= (so platforms=linux/amd64,linux/arm64 works).
_BUILD_PARAM_SPLIT = re.compile(
    r",(?=(?:" + "|".join(sorted(ALLOWED_BUILD_KEYS, key=len, reverse=True)) + r")=)"
)


def parse_build_unit(raw: str) -> Dict[str, str]:
    """Parse 'image=...,base=...,dockerfile=...' into a dict."""
    raw = raw.strip()
    if not raw:
        raise SystemExit("Empty --build value")

    params: Dict[str, str] = {}
    for part in _BUILD_PARAM_SPLIT.split(raw):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise SystemExit(
                f"Invalid --build param '{part}' (expected key=value). "
                f"Allowed keys: {', '.join(sorted(ALLOWED_BUILD_KEYS))}"
            )
        key, _, value = part.partition("=")
        key = key.strip()
        value = value.strip()
        if key not in ALLOWED_BUILD_KEYS:
            raise SystemExit(
                f"Unknown --build key '{key}'. "
                f"Allowed: {', '.join(sorted(ALLOWED_BUILD_KEYS))}"
            )
        if not value:
            raise SystemExit(f"--build key '{key}' has empty value")
        if key in params:
            raise SystemExit(f"Duplicate --build key '{key}' in: {raw}")
        params[key] = value

    if "image" not in params:
        raise SystemExit(f"--build missing required image=: {raw}")
    if "dockerfile" not in params:
        raise SystemExit(f"--build missing required dockerfile=: {raw}")

    params.setdefault("context", ".")
    params.setdefault("push", "false")
    return params


def _parse_push(raw: str) -> bool:
    v = raw.strip().lower()
    if v in ("true", "1", "yes"):
        return True
    if v in ("false", "0", "no"):
        return False
    raise SystemExit(f"push= must be true or false, got: {raw!r}")


def unit_to_spec(params: Dict[str, str]) -> ImageSpec:
    image = params["image"]
    dockerfile = params["dockerfile"]
    base = params.get("base", "")
    debian = params.get("debian", "")
    context = params.get("context", ".")
    cache_from = params.get("cache", "")
    platforms = params.get("platforms", "")
    push = _parse_push(params.get("push", "false"))

    # Validate dockerfile exists early
    try:
        resolve_dockerfile(dockerfile)
    except FileNotFoundError as e:
        raise SystemExit(str(e)) from e

    build_args: Dict[str, str] = {}
    if base:
        build_args["BASE_IMAGE"] = base
    if debian:
        build_args["DEBIAN_BASE"] = debian

    short = image.rsplit("/", 1)[-1]
    return ImageSpec(
        name=short,
        tag=image,
        dockerfile=dockerfile,
        context=context,
        build_args=build_args,
        cache_from=cache_from,
        platforms=platforms,
        push=push,
    )

def _fmt_duration(secs: float) -> str:
    s = int(secs)
    return f"{s // 60}m {s % 60}s" if s >= 60 else f"{s}s"


def build_unit_fields(spec: ImageSpec) -> List[tuple]:
    """Ordered (key, value) pairs for a resolved ImageSpec."""
    fields: List[tuple] = [
        ("image", spec.tag),
        ("dockerfile", spec.dockerfile),
    ]
    base = spec.build_args.get("BASE_IMAGE", "")
    if base:
        fields.append(("base", base))
    debian = spec.build_args.get("DEBIAN_BASE", "")
    if debian:
        fields.append(("debian", debian))
    if spec.cache_from:
        fields.append(("cache", spec.cache_from))
    if spec.platforms:
        fields.append(("platforms", spec.platforms))
    fields.append(("push", str(spec.push).lower()))
    if spec.context and spec.context != ".":
        fields.append(("context", spec.context))
    return fields


def format_build_unit(spec: ImageSpec) -> str:
    """Compact comma-separated --build params (for inline logs)."""
    return ",".join(f"{k}={v}" for k, v in build_unit_fields(spec))


def print_build_args(specs: List[ImageSpec]) -> None:
    header = f"{'=' * 16} ({len(specs)}) {'=' * 16}"
    print(f"{YELLOW}{header}{NC}", flush=True)
    for i, spec in enumerate(specs, 1):
        print(f"{BLUE}[{i}] --build:{NC}", flush=True)
        for key, value in build_unit_fields(spec):
            print(f"     - {key}={value}", flush=True)
    print(f"{YELLOW}{'=' * len(header)}{NC}", flush=True)


def print_result(r: BuildResult) -> None:
    label = r.spec.short_name
    if r.status == "built":
        print(f"{GREEN} ✔ {label:<40}{NC} Built in {_fmt_duration(r.duration)}")
    else:
        print(f"{RED} ✘ {label:<40}{NC} Build Failed")


# ── Main ──────────────────────────────────────────────────────────────────────


def run_builds(specs: List[ImageSpec], version: str) -> int:
    print_build_args(specs)
    print(f"{YELLOW}{'Image':<44} Status{NC}")
    print(f"{YELLOW}{'-----':<44} ------{NC}")

    t0 = time.monotonic()
    results: List[BuildResult] = []

    # Parallel across all --build units (same Dockerfile is OK: app builds use
    # unique version.info / Dockerfile.app.* temps).
    if PARALLEL and len(specs) > 1:
        with ThreadPoolExecutor(max_workers=len(specs)) as pool:
            futures = {pool.submit(ensure_image, s, version): s for s in specs}
            for f in as_completed(futures):
                results.append(f.result())
    else:
        results = [ensure_image(s, version) for s in specs]

    results.sort(key=lambda r: specs.index(r.spec))
    for r in results:
        print_result(r)

    failed = [r for r in results if r.status == "failed"]
    if failed:
        for r in failed:
            print(f"{RED}{r.spec.short_name} image build failed{NC}")
        return 1

    print(f"{GREEN}All builds completed in {_fmt_duration(time.monotonic() - t0)}{NC}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--build",
        action="append",
        default=[],
        metavar="PARAMS",
        help=(
            "Build unit: image=<tag>,dockerfile=<path>[,base=<ref>][,cache=<ref>]"
            "[,platforms=<list>][,push=true|false][,context=<dir>]. "
            "Repeatable; multiple units build in parallel across Dockerfiles."
        ),
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Parse --build units and print resolved specs, then exit",
    )
    args = parser.parse_args(argv)

    os.chdir(REPO_ROOT)
    version = read_version()

    if not args.build:
        parser.error(
            "at least one --build image=...,dockerfile=...[,base=...] is required"
        )

    units = [parse_build_unit(raw) for raw in args.build]
    specs = [unit_to_spec(u) for u in units]

    if args.list:
        print_build_args(specs)
        return 0

    return run_builds(specs, version)


if __name__ == "__main__":
    sys.exit(main())
