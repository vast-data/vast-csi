"""
This script generates the releaser configuration file for the following `Run chart-releaser` step.
Releases are separated into two categories: beta and stable.
Beta releases are created from branches with name pattern <version>-beta
Stable releases are created from branches with a valid version number (e.g. `1.0.0`).
"""
import os
import re
import sys
from pathlib import Path
import fileinput

ROOT = Path.cwd()
BRANCH = os.environ["GITHUB_REF_NAME"]
SHA = os.environ["GITHUB_SHA"][:7]
VERSION = ROOT.joinpath("version.txt").read_text().strip().lstrip("v")
CHARTS = [
    ROOT / "charts" / "vastcsi" / "Chart.yaml",
    ROOT / "charts" / "vastcosi" / "Chart.yaml",
]

if __name__ == '__main__':
    if not re.search('[0-9]+\.[0-9]+\.?[0-9]*', BRANCH):
        sys.stderr.write(
            f"Branch name must contain a valid version number. "
            f"Got: {BRANCH}. Skipping release...\n"
        )
        sys.exit(0)
    is_beta = "beta" in BRANCH

    release_name_template = "helm-{{ .Name }}-{{ .Version }}"
    pages_branch = "gh-pages-beta" if is_beta else "gh-pages"
    version = f"{VERSION}-beta.{SHA}" if is_beta else VERSION

    # Create unique release name based on version and commit sha
    for chart in CHARTS:
        for line in fileinput.input(chart, inplace=True):
            if line.startswith("version:"):
                line = line.replace(line, f"version: {version}\n")
            sys.stdout.write(line)

    ROOT.joinpath("releaser-config.yml").open("w").write(
        f"""
            pages-branch: {pages_branch}
            release-name-template: {release_name_template}
        """)
