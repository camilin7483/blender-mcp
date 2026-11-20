#!/usr/bin/env python3
"""Generate a small, auditable SBOM for the release gate."""

from __future__ import annotations

import json
import subprocess
import sys
from importlib.metadata import version as installed_version
from pathlib import Path

import tomllib
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
REQUIREMENTS = [
    ROOT / "pro" / "requirements.txt",
]


def parse_requirements(path: Path) -> list[dict]:
    components = []
    if not path.is_file():
        return components
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        requirement = Requirement(line)
        name = canonicalize_name(requirement.name)
        version = installed_version(requirement.name)
        if version not in requirement.specifier:
            raise ValueError(f"{requirement} is not satisfied by {version}")
        components.append({
            "type": "library",
            "name": name,
            "version": version,
            "scope": "required",
            "purl": f"pkg:pypi/{name}@{version}",
        })
    return components


def main() -> int:
    components = []
    seen = set()
    for path in REQUIREMENTS:
        for component in parse_requirements(path):
            key = component["name"].lower()
            if key not in seen:
                components.append(component)
                seen.add(key)
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "unknown"
    document = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "metadata": {
            "component": {
                "type": "application",
                "name": "blender-mcp",
                "version": VERSION,
                "properties": [{"name": "git.commit", "value": commit}],
            },
            "tools": [{"name": "generate_sbom.py", "version": "1"}],
        },
        "components": components,
    }
    json.dump(document, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
