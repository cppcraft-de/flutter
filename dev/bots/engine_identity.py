#!/usr/bin/env python3
"""Check the upstream engine content hash for committed WSC build inputs.

Uses the same git ls-tree | git hash-object operation and paths as upstream's
bin/internal/content_aware_hash.{sh,ps1}, explicitly at HEAD. Unlike the launcher
helper this source/publication check must never select a development merge-base.
It does not change branches, pins, objects, or upstream's hashing behavior.
"""

import argparse
from pathlib import Path
import re
import subprocess


def head_content_hash(repo: Path) -> str:
    # Match upstream's command-scoped workaround for Xcode's older Apple Git.
    # https://github.com/flutter/flutter/issues/184376
    version = subprocess.check_output(["git", "--version"], text=True)
    git_options = ["-c", "core.multiPackIndex=false"] if "Apple Git" in version else []
    inputs = subprocess.check_output([
        "git", *git_options, "-C", str(repo), "ls-tree", "HEAD", "--",
        "DEPS", "engine", "bin/internal/release-candidate-branch.version",
    ])
    paths = {line.split(b"\t", 1)[1] for line in inputs.splitlines()}
    if paths != {b"DEPS", b"engine", b"bin/internal/release-candidate-branch.version"}:
        raise ValueError("Missing committed upstream engine hash inputs")
    return subprocess.check_output(
        ["git", "-C", str(repo), "hash-object", "--stdin"], input=inputs,
    ).decode("ascii").strip()


def build_identity(build_dir: Path, engine_id: str, revision: str) -> None:
    """Reject stale GN outputs or merge-base hashes before publication."""
    args = (build_dir / "args.gn").read_text(encoding="utf-8")
    for key, expected in (("engine_version", revision), ("content_hash", engine_id)):
        values = re.findall(rf'^\s*{key}\s*=\s*"([0-9a-f]{{40}})"\s*$', args, re.MULTILINE)
        if values != [expected]:
            raise ValueError(f"{build_dir}: {key} is {values}, expected {expected}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    print(head_content_hash(args.repo))
