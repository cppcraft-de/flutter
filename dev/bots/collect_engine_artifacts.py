#!/usr/bin/env python3
"""Collect engine build outputs into a Flutter artifact-mirror tree.

The source paths and upload-relative paths come from the checked-in engine CI
builder JSON files. This deliberately stages complete generated archives, not
individual engine binaries.
"""

from __future__ import annotations

import argparse
import filecmp
import json
import shutil
from pathlib import Path


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if filecmp.cmp(source, destination, shallow=False):
            return
        raise RuntimeError(f"Conflicting artifact for {destination}")
    shutil.copy2(source, destination)


def _copy_path(source: Path, destination: Path) -> None:
    if source.is_dir():
        for child in source.rglob("*"):
            if child.is_file():
                _copy_file(child, destination / child.relative_to(source))
        return
    _copy_file(source, destination)


def _is_symbol_archive(path: Path) -> bool:
    return path.name == "symbols.zip" or path.suffix.lower() == ".pdb"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine-src", type=Path, required=True)
    parser.add_argument("--engine-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--builder", required=True)
    parser.add_argument("--build", action="append", default=[])
    parser.add_argument("--include-global", action="store_true")
    parser.add_argument("--include-symbols", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    builder_path = (
        args.engine_src / "flutter" / "ci" / "builders" / f"{args.builder}.json"
    )
    builder = json.loads(builder_path.read_text(encoding="utf-8"))
    requested_builds = set(args.build)
    known_builds = {build["name"] for build in builder.get("builds", [])}
    unknown_builds = requested_builds - known_builds
    if unknown_builds:
        raise RuntimeError(
            f"Unknown builds in {args.builder}: {', '.join(sorted(unknown_builds))}"
        )

    engine_root = (
        args.output
        / "flutter_infra_release"
        / "flutter"
        / args.engine_id
    )

    copied = 0
    for build in builder.get("builds", []):
        if build["name"] not in requested_builds:
            continue
        for archive in build.get("archives", []):
            base_path = Path(archive["base_path"])
            for include in archive.get("include_paths", []):
                relative_source = Path(include)
                if not args.include_symbols and _is_symbol_archive(relative_source):
                    continue
                source = args.engine_src / relative_source
                if not source.exists():
                    raise FileNotFoundError(f"Expected engine artifact was not built: {source}")
                relative_destination = relative_source.relative_to(base_path)
                # Android Maven artifacts are fetched from
                # FLUTTER_STORAGE_BASE_URL/download.flutter.io, not from the
                # revision-specific engine directory.
                if relative_destination.parts[0] == "download.flutter.io":
                    destination = args.output / relative_destination
                else:
                    destination = engine_root / relative_destination
                _copy_path(source, destination)
                copied += 1

    if args.include_global:
        for archive in builder.get("archives", []):
            source = args.engine_src / Path(archive["source"])
            if not source.exists():
                # Global generators are mode-dependent. Missing outputs for
                # deliberately disabled modes are expected.
                continue
            destination = engine_root / Path(archive["destination"])
            _copy_path(source, destination)
            copied += 1

    if copied == 0:
        raise RuntimeError(f"No artifacts were collected from {builder_path}")
    print(f"Collected {copied} artifact entries from {args.builder}")


if __name__ == "__main__":
    main()
