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
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from engine_identity import build_identity, head_content_hash


def _gn_option(arguments: list[str], name: str, default: str) -> str:
    for index, value in enumerate(arguments):
        if value == name:
            return arguments[index + 1]
        if value.startswith(name + "="):
            return value.split("=", 1)[1]
    return default


def _copy_maven(source: Path, output: Path, build: dict, revision: str, engine_id: str) -> None:
    # Upstream generates content-hash POMs/JAR names inside the Git-revision
    # directory. Its upload recipes relocate those variants; do not rewrite POMs
    # or recursively publish stale versions from persistent Ninja directories.
    mode = _gn_option(build["gn"], "--runtime-mode", "debug")
    cpu = _gn_option(build["gn"], "--android-cpu", "arm")
    abis = {"arm": "armeabi_v7a", "arm64": "arm64_v8a", "x86": "x86", "x64": "x86_64"}
    targets = build["ninja"]["targets"]
    artifacts = []
    if "flutter/shell/platform/android:abi_jars" in targets:
        artifacts.append(f"{abis[cpu]}_{mode}")
    if "flutter/shell/platform/android:embedding_jars" in targets:
        artifacts.append(f"flutter_embedding_{mode}")
    if not artifacts:
        raise ValueError(f"No supported Maven targets in {build['name']}")
    for artifact in artifacts:
        origin = source / "io/flutter" / artifact / f"1.0.0-{revision}"
        name = f"{artifact}-1.0.0-{engine_id}"
        pom = origin / f"{name}.pom"
        root = ET.parse(pom).getroot()
        ns = {"m": "http://maven.apache.org/POM/4.0.0"}
        for key, expected in (("groupId", "io.flutter"), ("artifactId", artifact), ("version", f"1.0.0-{engine_id}")):
            if root.findtext(f"m:{key}", namespaces=ns) != expected:
                raise ValueError(f"{pom}: invalid {key}; expected {expected}")
        destination = output / "download.flutter.io/io/flutter" / artifact / f"1.0.0-{engine_id}"
        suffixes = [".pom", ".jar"]
        if artifact.startswith("flutter_embedding_"):
            suffixes.append("-sources.jar")
        for suffix in suffixes:
            _copy_file(origin / f"{name}{suffix}", destination / f"{name}{suffix}")


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
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="Skip declared outputs absent on this host. Use only for cross-host common archives.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    repo = args.engine_src.resolve().parents[1]
    if head_content_hash(repo) != args.engine_id:
        raise ValueError("Publication engine ID must match the checked-out engine content hash")
    revision = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
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
        build_identity(args.engine_src / "out" / build["ninja"]["config"], args.engine_id, revision)
        for archive in build.get("archives", []):
            base_path = Path(archive["base_path"])
            for include in archive.get("include_paths", []):
                relative_source = Path(include)
                if not args.include_symbols and _is_symbol_archive(relative_source):
                    continue
                source = args.engine_src / relative_source
                if not source.exists():
                    if args.allow_missing:
                        continue
                    raise FileNotFoundError(f"Expected engine artifact was not built: {source}")
                relative_destination = relative_source.relative_to(base_path)
                # Android Maven artifacts are fetched from
                # FLUTTER_STORAGE_BASE_URL/download.flutter.io, not from the
                # revision-specific engine directory.
                if relative_destination.parts[0] == "download.flutter.io":
                    _copy_maven(source, args.output, build, revision, args.engine_id)
                else:
                    destination = engine_root / relative_destination
                    _copy_path(source, destination)
                copied += 1

    if args.include_global:
        for archive in builder.get("archives", []):
            source = args.engine_src / Path(archive["source"])
            if not source.exists():
                if Path(archive["destination"]).name == "engine_stamp.json":
                    raise FileNotFoundError(f"Missing engine build stamp: {source}")
                # Global generators are mode-dependent. Missing outputs for
                # deliberately disabled modes are expected.
                continue
            destination = engine_root / Path(archive["destination"])
            if destination.name == "engine_stamp.json":
                stamp = json.loads(source.read_text(encoding="utf-8"))
                if stamp.get("content_hash") != args.engine_id or stamp.get("git_revision") != revision:
                    raise ValueError(f"Stale engine stamp: {source}")
            _copy_path(source, destination)
            copied += 1

    if copied == 0:
        raise RuntimeError(f"No artifacts were collected from {builder_path}")
    print(f"Collected {copied} artifact entries from {args.builder}")


if __name__ == "__main__":
    main()
