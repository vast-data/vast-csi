"""
This script generates the releaser configuration file for the following `Run chart-releaser` step.
Releases are separated into three categories: beta, hotfix, and stable.
Beta releases are created from branches with name pattern <version>-beta
Hotfix releases are created from branches with name pattern <version>-hf<number> (e.g. `2.6.4-hf1`)
Stable releases are created from branches with a valid version number (e.g. `1.0.0`).
"""
import argparse
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHARTS_ROOT = ROOT / "charts"
PUBLIC_CHARTS = [
    CHARTS_ROOT / "vastcsi" / "Chart.yaml",
    CHARTS_ROOT / "vastcosi" / "Chart.yaml",
    CHARTS_ROOT / "vastblock" / "Chart.yaml",
]


def replace_chart_version(chart: Path, version: str) -> None:
    content = chart.read_text()
    updated, count = re.subn(
        r"(?m)^version:\s*[^\s#]+",
        f"version: {version}",
        content,
        count=1,
    )
    if count != 1:
        raise RuntimeError(f"Expected one chart version in {chart}")
    chart.write_text(updated)


def prepare_release() -> None:
    branch = os.environ["GITHUB_REF_NAME"]
    sha = os.environ["GITHUB_SHA"][:7]
    base_version = ROOT.joinpath("version.txt").read_text().strip().lstrip("v")

    if not re.search(r"[0-9]+\.[0-9]+\.?[0-9]*", branch):
        sys.stderr.write(
            f"Branch name must contain a valid version number. "
            f"Got: {branch}. Skipping release...\n"
        )
        return
    is_beta = "beta" in branch
    is_hotfix = "-hf" in branch

    release_name_template = "helm-{{ .Name }}-{{ .Version }}"
    # Hotfixes go to prod gh-pages (same as stable releases)
    pages_branch = "gh-pages-beta" if is_beta else "gh-pages"
    
    # For hotfixes, use the branch name as version (e.g., 2.6.4-hf1)
    # For beta, append beta suffix with commit SHA
    # For stable, use version.txt as-is
    if is_hotfix:
        version = branch.lstrip("v")  # Remove 'v' prefix if present
    elif is_beta:
        version = f"{base_version}-beta.{sha}"
    else:
        version = base_version

    for chart in PUBLIC_CHARTS:
        replace_chart_version(chart, version)

    ROOT.joinpath("releaser-config.yml").open("w").write(
        f"""
            pages-branch: {pages_branch}
            release-name-template: {release_name_template}
        """)


def prune_unpublished_charts() -> None:
    public_chart_dirs = {chart.parent.resolve() for chart in PUBLIC_CHARTS}
    for chart_file in CHARTS_ROOT.glob("*/Chart.yaml"):
        chart_dir = chart_file.parent
        if chart_dir.resolve() not in public_chart_dirs:
            print(f"Removing unpublished chart source: {chart_dir}")
            shutil.rmtree(chart_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--prune-unpublished-charts",
        action="store_true",
        help="Remove top-level charts not listed in PUBLIC_CHARTS",
    )
    args = parser.parse_args()
    if args.prune_unpublished_charts:
        prune_unpublished_charts()
    else:
        prepare_release()
