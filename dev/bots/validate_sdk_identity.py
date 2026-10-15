#!/usr/bin/env python3
"""Check WSC source tags and SDK ZIP metadata without extracting or building."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile

from engine_identity import head_content_hash


UPSTREAM_VERSION = r"\d+\.\d+\.\d+(?:-\d+\.\d+\.pre)?"
RELEASE_TAG = re.compile(rf"wsc-({UPSTREAM_VERSION})-r[1-9]\d*")
DEVELOPMENT_VERSION = re.compile(
    rf"wsc-{UPSTREAM_VERSION}(?:-r[1-9]\d*)?-dev\.\d+-g([0-9a-f]+)"
)


def select_release_tag(tags: list[str], require_release_tag: bool) -> str | None:
    releases = [tag for tag in tags if RELEASE_TAG.fullmatch(tag)]
    if len(releases) > 1:
        raise ValueError(f"Ambiguous WSC release tags on the source commit: {releases}")
    if not releases and require_release_tag:
        raise ValueError("Release SDKs require an exact wsc-<upstream-version>-r<number> tag.")
    return releases[0] if releases else None


def validate_engine_pin(engine_id: str, expected_engine_id: str) -> None:
    for name, value in (("engine ID", engine_id), ("expected engine ID", expected_engine_id)):
        if not re.fullmatch(r"[0-9a-f]{40}", value):
            raise ValueError(f"Invalid {name}: expected a full lowercase content hash.")
    if engine_id != expected_engine_id:
        raise ValueError(
            f"bin/internal/engine.version is {engine_id}, but the committed engine "
            f"content hash is {expected_engine_id}. Update the pin before building/publishing."
        )


def validate_archive(archive: Path, revision: str, channel: str, release_tag: str | None, engine_id: str) -> None:
    with zipfile.ZipFile(archive) as sdk:
        metadata = json.loads(sdk.read("flutter/bin/cache/flutter.version.json"))
        stamp = json.loads(sdk.read("flutter/bin/cache/engine_stamp.json"))
        for name in ("bin/internal/engine.version", "bin/cache/engine.stamp"):
            validate_engine_pin(sdk.read("flutter/" + name).decode("ascii").strip(), engine_id)
        if not isinstance(stamp, dict) or stamp.get("content_hash") != engine_id:
            raise ValueError(f"{archive.name}: engine stamp content hash does not match the pin")
        engine_revision = stamp.get("git_revision", "")
        if not isinstance(engine_revision, str) or not re.fullmatch(r"[0-9a-f]{40}", engine_revision):
            raise ValueError(f"{archive.name}: invalid engine build-source revision")
    if not isinstance(metadata, dict):
        raise ValueError(f"{archive.name}: version metadata must be a JSON object.")
    expected = {"frameworkRevision": revision, "channel": channel,
                "engineRevision": engine_revision, "engineContentHash": engine_id}
    if release_tag:
        expected.update(
            wscVersion=release_tag,
            frameworkVersion=RELEASE_TAG.fullmatch(release_tag).group(1),
        )
    for field, value in expected.items():
        if metadata.get(field) != value:
            raise ValueError(f"{archive.name}: {field} is {metadata.get(field)!r}, expected {value!r}")
    framework_version = metadata.get("frameworkVersion")
    if not framework_version or metadata.get("flutterVersion") != framework_version:
        raise ValueError(f"{archive.name}: flutterVersion and frameworkVersion must agree.")
    wsc_version = metadata.get("wscVersion", "")
    if not isinstance(wsc_version, str):
        raise ValueError(f"{archive.name}: wscVersion must be a string.")
    if not release_tag:
        development = DEVELOPMENT_VERSION.fullmatch(wsc_version)
        if not development or not revision.startswith(development.group(1)):
            raise ValueError(f"{archive.name}: expected a WSC development identity for {revision}.")
    if not archive.name.startswith("flutter_") or not archive.name.endswith(f"_{wsc_version}-{channel}.zip"):
        raise ValueError(f"{archive.name}: filename does not match the packaged WSC identity/channel.")


def write_checksum(archive: Path) -> None:
    digest = hashlib.sha256()
    with archive.open('rb') as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    archive.with_name(archive.name + '.sha256').write_text(
        f'{digest.hexdigest()}  {archive.name}\n', encoding='utf-8',
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True, help="Full source commit SHA")
    parser.add_argument("--require-release-tag", action="store_true")
    parser.add_argument("--directory", type=Path, help="SDK output directory; omit for source preflight")
    parser.add_argument("--channel", choices=["main", "master", "beta", "stable"])
    parser.add_argument("--write-checksums", action="store_true", help="Write SHA256 sidecars after validation")
    parser.add_argument("--engine-id", help="Tracked engine pin to check during CI preflight")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        parser.error("--revision must be a full lowercase commit SHA")
    if args.directory is not None and args.channel is None:
        parser.error("--channel is required when validating SDK archives")
    try:
        repo = Path(__file__).resolve().parents[2]
        actual_revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, cwd=repo,
        ).strip()
        if actual_revision != args.revision:
            raise ValueError(
                f"Checkout is {actual_revision}, but --revision requests {args.revision}. "
                "Check out the requested revision before validating its pin or SDK."
            )
        tags = subprocess.check_output(
            ["git", "tag", "--points-at", args.revision], text=True,
            cwd=Path(__file__).resolve().parents[2],
        ).splitlines()
        release_tag = select_release_tag(tags, args.require_release_tag)
        print(f"Source identity: {release_tag or 'untagged WSC development build'}")
        engine_id = (repo / "bin/internal/engine.version").read_text().strip()
        validate_engine_pin(engine_id, head_content_hash(repo))
        if args.engine_id is not None:
            validate_engine_pin(args.engine_id, engine_id)
        if args.directory is not None:
            archives = sorted(args.directory.glob("*.zip"))
            if not archives:
                raise ValueError(f"No SDK ZIP found in {args.directory}")
            for archive in archives:
                validate_archive(archive, args.revision, args.channel, release_tag, engine_id)
                if args.write_checksums:
                    write_checksum(archive)
                print(f"Validated SDK identity: {archive.name}")
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError, zipfile.BadZipFile) as error:
        parser.exit(1, f"SDK identity validation failed: {error}\n")


if __name__ == "__main__":
    main()
