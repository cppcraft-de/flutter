#!/usr/bin/env python3
"""Stage missing upstream-owned SDK inputs; never substitute engine artifacts.

Probe the authenticated storage origin before staging. The caller must hold the
publication lock through staging and upload_artifact_tree.py publication.
--verify-only checks anonymous CDN visibility before packaging an SDK.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

from publish_engine_artifacts import origin_get


UPSTREAM = "https://storage.googleapis.com"
IOS_TOOLS = (
    "libimobiledevice", "libusbmuxd", "libplist", "openssl",
    "libimobiledeviceglue", "ios-deploy",
)


def seed_paths(checkout: Path, hosts: set[str]) -> list[str]:
    pins = checkout / "bin" / "internal"
    paths = []
    for name in ("material_fonts", "gradle_wrapper"):
        value = (pins / f"{name}.version").read_text().strip()
        if not re.fullmatch(r"flutter_infra_release/[A-Za-z0-9_./-]+", value):
            raise ValueError(f"Invalid {name} path: {value}")
        if any(part in (".", "..", "") for part in value.split("/")):
            raise ValueError(f"Unsafe {name} path: {value}")
        paths.append(value)
    if "macos" in hosts:
        for name in IOS_TOOLS:
            revision = (pins / f"{name}.version").read_text().strip()
            if not re.fullmatch(r"[A-Za-z0-9_-]+", revision):
                raise ValueError(f"Invalid {name} revision: {revision}")
            paths.append(
                f"flutter_infra_release/ios-usb-dependencies/arm64_x86_64/"
                f"{name}/{revision}/{name}.zip"
            )
    # This upstream object is not versioned. Preserve an existing mirror copy;
    # log the SHA256 when first seeding it rather than silently refreshing it.
    paths.append("flutter_infra_release/flutter/coverage/lcov.info")
    return paths


def exists(url: str) -> bool:
    request = urllib.request.Request(url, method="HEAD", headers={"Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            if response.status != 200:
                raise RuntimeError(f"Unexpected HEAD status {response.status}: {url}")
            return True
    except urllib.error.HTTPError as error:
        error.close()
        if error.code == 404:
            return False
        raise


def download(relative: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".partial")
    try:
        with urllib.request.urlopen(f"{UPSTREAM}/{relative}", timeout=120) as response:
            if response.status != 200:
                raise RuntimeError(f"Unexpected upstream status: {response.status}")
            # Google can send one comma-separated field or repeated fields.
            # HTTPMessage.get() reads only one and may miss the MD5 entirely.
            hashes = dict(
                item.strip().split("=", 1)
                for header in response.headers.get_all("x-goog-hash", [])
                for item in header.split(",")
                if "=" in item
            )
            expected_md5 = hashes.get("md5")
            if not expected_md5:
                raise RuntimeError(f"Upstream provided no MD5 integrity checksum: {relative}")
            md5 = hashlib.md5(usedforsecurity=False)
            sha256 = hashlib.sha256()
            with partial.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                    md5.update(chunk)
                    sha256.update(chunk)
            if base64.b64encode(md5.digest()).decode() != expected_md5:
                raise RuntimeError(f"Upstream checksum mismatch: {relative}")
        partial.replace(destination)
        print(f"Seed SHA256 {sha256.hexdigest()}  {relative}")
    finally:
        partial.unlink(missing_ok=True)


def prepare(checkout: Path, hosts: set[str], base_url: str, output: Path,
            verify_only: bool = False, *, upload_base_url: str | None = None) -> None:
    if not verify_only:
        if not upload_base_url:
            raise ValueError("--upload-base-url is required when staging seeds")
        output.mkdir(parents=True, exist_ok=True)
    for relative in seed_paths(checkout, hosts):
        url = f"{base_url.rstrip('/')}/{relative}"
        if not verify_only:
            # A stale CDN 404 must never cause an existing origin file to be
            # replaced. GET supports origins without HEAD; read only one byte.
            if origin_get(upload_base_url, relative, 1) is not None:
                print(f"Preserve existing origin seed: {relative}")
            else:
                print(f"Missing at origin: {relative}")
                download(relative, output / relative)
            continue
        # Allow bounded CDN propagation time after a successful upload.
        for attempt in range(6):
            if exists(url):
                print(f"Available: {url}")
                break
            if attempt == 5:
                raise RuntimeError(f"Seed is still unavailable through the download endpoint: {url}")
            time.sleep(5)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, default=Path("."))
    parser.add_argument("--hosts", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--upload-base-url")
    parser.add_argument("--output", type=Path, default=Path("build/seed-payload"))
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    hosts = set(args.hosts.split(","))
    if not hosts or hosts - {"windows", "macos"}:
        parser.error("--hosts must select windows and/or macos")
    if not args.verify_only and not args.upload_base_url:
        parser.error("--upload-base-url is required when staging seeds")
    prepare(args.checkout, hosts, args.base_url, args.output, args.verify_only,
            upload_base_url=args.upload_base_url)


if __name__ == "__main__":
    main()
