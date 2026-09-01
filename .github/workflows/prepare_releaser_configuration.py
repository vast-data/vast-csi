"""
Generate releaser-config.yml for chart-releaser and remove chart sources outside the
selected release group.

Release groups:
  public — vastcsi, vastcosi, vastblock → gh-pages (or gh-pages-beta)
  gke    — vastcsi-gke → gke-gh-pages
  common — charts/common only (library); used to strip other sources if chart-releaser
           is invoked for that group

Beta/hotfix/stable versioning applies to public releases on version branches.
GKE releases use version.txt. Common is versioned in charts/common/Chart.yaml.
"""
import argparse
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHARTS_ROOT = ROOT / "charts"
RELEASE_GROUPS = {
    "public": [
        CHARTS_ROOT / "vastcsi" / "Chart.yaml",
        CHARTS_ROOT / "vastcosi" / "Chart.yaml",
        CHARTS_ROOT / "vastblock" / "Chart.yaml",
    ],
    "gke": [
        CHARTS_ROOT / "vastcsi-gke" / "Chart.yaml",
    ],
    "common": [
        CHARTS_ROOT / "common" / "Chart.yaml",
    ],
}


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


def prune_unpublished_charts(release_group: str) -> None:
    allowed_chart_dirs = {
        chart.parent.resolve() for chart in RELEASE_GROUPS[release_group]
    }
    for chart_file in CHARTS_ROOT.glob("*/Chart.yaml"):
        chart_dir = chart_file.parent
        if chart_dir.resolve() not in allowed_chart_dirs:
            print(f"Removing chart source outside release group: {chart_dir}")
            shutil.rmtree(chart_dir)


def prepare_release(release_group: str) -> None:
    branch = os.environ.get("GITHUB_REF_NAME", "")
    sha = os.environ.get("GITHUB_SHA", "0000000")[:7]
    base_version = ROOT.joinpath("version.txt").read_text().strip().lstrip("v")

    if release_group == "public" and branch and not re.search(
        r"[0-9]+\.[0-9]+\.?[0-9]*", branch
    ):
        sys.stderr.write(
            f"Branch name must contain a valid version number. "
            f"Got: {branch}. Skipping release...\n"
        )
        return

    is_beta = "beta" in branch
    is_hotfix = "-hf" in branch

    release_name_template = "helm-{{ .Name }}-{{ .Version }}"
    pages_branch = (
        "gke-gh-pages"
        if release_group == "gke"
        else ("gh-pages-beta" if is_beta else "gh-pages")
    )

    if release_group == "common":
        version = None
    elif release_group == "gke":
        version = base_version
    elif is_hotfix:
        version = branch.lstrip("v")
    elif is_beta:
        version = f"{base_version}-beta.{sha}"
    else:
        version = base_version

    if version is not None:
        for chart in RELEASE_GROUPS[release_group]:
            replace_chart_version(chart, version)

    ROOT.joinpath("releaser-config.yml").open("w").write(
        f"""
            pages-branch: {pages_branch}
            release-name-template: {release_name_template}
        """
    )

    prune_unpublished_charts(release_group)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--release-group",
        choices=RELEASE_GROUPS,
        default="public",
        help="Select the charts and pages branch to release",
    )
    args = parser.parse_args()
    prepare_release(args.release_group)
