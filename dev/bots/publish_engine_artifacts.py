#!/usr/bin/env python3
"""Publish once under upstream engine IDs. Caller MUST hold the Jenkins lock.

One origin-side receipt tracks exact paths, not a second engine identity. A
pending receipt is written before payload PUTs; a completed receipt only after
anonymous download verification. No remote deletion or automatic repair.
"""

from __future__ import annotations

import argparse
import hashlib
from http.client import IncompleteRead
import json
from pathlib import Path
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

from upload_artifact_tree import authentication_headers, _NoUploadRedirects, upload_file
from verify_maven_artifacts import response_details


MAX_RECEIPT = 2 * 1024 * 1024
RECOVERY = "Review the publication, then explicitly use DANGEROUSLY_OVERWRITE_BUILD_ARTIFACTS=true to repair it."


def object_url(base: str, relative: str) -> str:
    return base.rstrip("/") + "/" + urllib.parse.quote(relative, safe="/")


def check_path(path: str, engine_id: str) -> None:
    if (not isinstance(path, str) or "\\" in path
            or any(part in ("", ".", "..") for part in path.split("/"))):
        raise ValueError("Invalid artifact path")
    engine = path.startswith(f"flutter_infra_release/flutter/{engine_id}/")
    maven = re.fullmatch(
        rf"download\.flutter\.io/io/flutter/[\w.-]+/1\.0\.0-{engine_id}/[\w.-]+", path)
    if not engine and not maven:
        raise ValueError(f"Artifact is outside selected engine ID: {path}")


def origin_get(base: str, relative: str, limit: int) -> bytes | None:
    # GET also works with storage APIs that do not implement HEAD. Bound reads
    # (one byte for existence probes); never follow credential-bearing redirects.
    request = urllib.request.Request(object_url(base, relative), headers=authentication_headers())
    opener = urllib.request.build_opener(_NoUploadRedirects())
    try:
        with opener.open(request, timeout=120) as response:
            if response.status != 200:
                raise ValueError(f"Unexpected storage status for {relative}: {response.status}")
            return response.read(limit)
    except urllib.error.HTTPError as error:
        error.close()
        if error.code == 404:
            return None
        raise


def read_receipt(base: str, relative: str, engine_id: str) -> dict:
    raw = origin_get(base, relative, MAX_RECEIPT + 1)
    if raw is None:
        return {"schema": 1, "engine_id": engine_id, "files": {}, "pending": []}
    if len(raw) > MAX_RECEIPT:
        raise ValueError("Publication receipt is too large")
    receipt = json.loads(raw)
    if (not isinstance(receipt, dict) or receipt.get("schema") != 1
            or receipt.get("engine_id") != engine_id
            or not isinstance(receipt.get("files"), dict)
            or not isinstance(receipt.get("pending"), list)):
        raise ValueError("Invalid publication receipt; manual inspection required")
    for path, entry in receipt["files"].items():
        check_path(path, engine_id)
        if (not isinstance(entry, dict) or type(entry.get("size")) is not int
                or entry["size"] < 0
                or not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256", "")))):
            raise ValueError(f"Invalid receipt entry: {path}")
    for path in receipt["pending"]:
        check_path(path, engine_id)
    return receipt


def file_identity(path: Path) -> dict:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return {"size": path.stat().st_size, "sha256": checksum.hexdigest()}


def verify_download(base: str, relative: str, expected: dict, *, full: bool) -> None:
    # New/replaced objects get a streamed byte-level check, including large ZIPs
    # and JARs. Reused binaries need only HEAD; reused POM/JSON metadata is hashed.
    full = full or relative.endswith((".pom", ".json"))
    request = urllib.request.Request(object_url(base, relative), method="GET" if full else "HEAD")
    print(f"Verify download ({request.method}): {request.full_url}", flush=True)
    for attempt in range(6):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                details = response_details(response)
                if response.status != 200 or response.headers.get("Content-Length") != str(expected["size"]):
                    raise ValueError(f"Published artifact size/status differs: {relative}; "
                                     f"expected size={expected['size']}; {details}")
                if full:
                    digest = hashlib.sha256()
                    received = 0
                    while block := response.read(min(1024 * 1024, expected["size"] + 1 - received)):
                        received += len(block)
                        digest.update(block)
                        if received > expected["size"]:
                            break
                    if received != expected["size"] or digest.hexdigest() != expected["sha256"]:
                        raise ValueError(f"Published artifact SHA-256 differs: {relative}; "
                                         f"expected size={expected['size']}; received={received}; {details}")
            return
        except (urllib.error.URLError, ConnectionError, TimeoutError, IncompleteRead) as error:
            if isinstance(error, urllib.error.HTTPError):
                error.close()
                retryable = error.code in (404, 408, 429, 500, 502, 503, 504)
            else:
                reason = error.reason if isinstance(error, urllib.error.URLError) else error
                retryable = isinstance(reason, (ConnectionError, TimeoutError, IncompleteRead))
            # Do not mask authentication, TLS configuration or integrity errors.
            if not retryable or attempt == 5:
                raise
            print(f"Download verification attempt {attempt + 1}/6 failed: {error}; "
                  f"retrying in 5s: {request.full_url}", flush=True)
            time.sleep(5)


def save_receipt(base: str, relative: str, receipt: dict) -> None:
    data = json.dumps(receipt, sort_keys=True, indent=2).encode() + b"\n"
    if len(data) > MAX_RECEIPT:
        raise ValueError("Publication receipt is too large")
    with tempfile.TemporaryDirectory(prefix="wsc-receipt-") as temporary:
        path = Path(temporary) / "receipt.json"
        path.write_bytes(data)
        upload_file(path, object_url(base, relative))
    # Origin read-back catches a misconfigured storage endpoint before payload
    # changes, and prevents reporting success if the final receipt wasn't saved.
    if origin_get(base, relative, MAX_RECEIPT + 1) != data:
        raise ValueError("Storage receipt read-back failed; stop publication and inspect the origin")


def publish(root: Path, upload_base: str, download_base: str, engine_id: str,
            overwrite: bool = False) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", engine_id):
        raise ValueError("Expected lowercase engine content hash")
    files = {path.relative_to(root).as_posix(): path for path in sorted(root.rglob("*")) if path.is_file()}
    if not files:
        raise ValueError("No engine artifacts staged")
    for relative in files:
        check_path(relative, engine_id)
    receipt_path = f"wsc-publications/{engine_id}.json"
    receipt = read_receipt(upload_base, receipt_path, engine_id)
    pending = set(receipt["pending"])
    if pending and not overwrite:
        raise ValueError(f"Incomplete publication for {engine_id}. {RECOVERY}")
    if pending - files.keys():
        raise ValueError("Recovery must include all interrupted paths; select the original target/modes: "
                         + ", ".join(sorted(pending - files.keys())))
    if overwrite:
        print(f"DANGER: replacing {len(files)} selected artifacts for engine {engine_id} at {upload_base}. "
              "Existing SDKs are affected. Purge/disable CDN caches and refresh developer Gradle/Flutter caches. "
              "This flag does NOT clean or rebuild local outputs.", flush=True)

    replace = {}
    for relative, path in files.items():
        if not overwrite and relative in receipt["files"]:
            if origin_get(upload_base, relative, 1) is None:
                raise ValueError(f"Recorded artifact missing at storage origin: {relative}. {RECOVERY}")
            verify_download(download_base, relative, receipt["files"][relative], full=False)
            print(f"Reuse published artifact (not newly compiled bytes): {relative}", flush=True)
        else:
            if not overwrite and origin_get(upload_base, relative, 1) is not None:
                raise ValueError(f"Unrecorded existing artifact: {relative}. {RECOVERY}")
            replace[relative] = file_identity(path)
    if not replace:
        print("All selected artifacts already published and available; no PUTs.", flush=True)
        return

    # Invalidate before the first payload write. Preserve inventory for other
    # targets, but no caller may regard a nonempty pending list as complete.
    receipt["pending"] = sorted(replace)
    save_receipt(upload_base, receipt_path, receipt)
    for relative, expected in replace.items():
        print(f"Publish and verify: {relative}", flush=True)
        upload_file(files[relative], object_url(upload_base, relative))
        verify_download(download_base, relative, expected, full=True)
    receipt["files"].update(replace)
    receipt["pending"] = []
    save_receipt(upload_base, receipt_path, receipt)
    print(f"Publication receipt complete: {receipt_path} ({len(receipt['files'])} recorded files)", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--upload-base-url", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--engine-id", required=True)
    parser.add_argument("--dangerously-overwrite", action="store_true")
    args = parser.parse_args()
    publish(args.root, args.upload_base_url, args.base_url, args.engine_id, args.dangerously_overwrite)
