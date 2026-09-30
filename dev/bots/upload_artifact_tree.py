#!/usr/bin/env python3
"""Upload a static artifact tree using HTTP PUT.

Credentials are intentionally read from environment variables so secrets do
not appear in process arguments:

  ARTIFACT_UPLOAD_USER / ARTIFACT_UPLOAD_PASSWORD
  ARTIFACT_UPLOAD_BEARER_TOKEN
"""

from __future__ import annotations

import argparse
import base64
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--attempts", type=int, default=3)
    return parser.parse_args()


def _authorization_header() -> str | None:
    bearer = os.environ.get("ARTIFACT_UPLOAD_BEARER_TOKEN")
    if bearer:
        return f"Bearer {bearer}"
    username = os.environ.get("ARTIFACT_UPLOAD_USER")
    password = os.environ.get("ARTIFACT_UPLOAD_PASSWORD")
    if username is None and password is None:
        return None
    if username is None or password is None:
        raise RuntimeError("Both ARTIFACT_UPLOAD_USER and ARTIFACT_UPLOAD_PASSWORD are required")
    encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {encoded}"


def main() -> None:
    args = _parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        raise RuntimeError(f"Artifact root does not exist: {root}")
    files = sorted(path for path in root.rglob("*") if path.is_file())
    if not files:
        raise RuntimeError(f"Artifact root is empty: {root}")

    authorization = _authorization_header()
    base_url = args.base_url.rstrip("/")
    for index, path in enumerate(files, start=1):
        relative = path.relative_to(root).as_posix()
        quoted_relative = "/".join(urllib.parse.quote(part) for part in relative.split("/"))
        url = f"{base_url}/{quoted_relative}"
        print(f"[{index}/{len(files)}] PUT {url}")
        if args.dry_run:
            continue

        headers = {"Content-Length": str(path.stat().st_size)}
        if authorization:
            headers["Authorization"] = authorization
        for attempt in range(1, args.attempts + 1):
            try:
                with path.open("rb") as source:
                    request = urllib.request.Request(
                        url,
                        data=source,
                        headers=headers,
                        method="PUT",
                    )
                    with urllib.request.urlopen(request) as response:
                        if response.status < 200 or response.status >= 300:
                            raise RuntimeError(f"Upload returned HTTP {response.status}: {url}")
                break
            except (OSError, urllib.error.URLError) as error:
                if attempt == args.attempts:
                    raise RuntimeError(f"Failed to upload {path} to {url}") from error
                time.sleep(2**attempt)


if __name__ == "__main__":
    main()
