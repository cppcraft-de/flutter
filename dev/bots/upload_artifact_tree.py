#!/usr/bin/env python3
"""Upload a static artifact tree using HTTP PUT.

Credentials are intentionally read from environment variables so secrets do
not appear in process arguments:

  ARTIFACT_UPLOAD_USER / ARTIFACT_UPLOAD_PASSWORD
  ARTIFACT_UPLOAD_BEARER_TOKEN
  HTTP_UPLOAD_KEY (sent as AccessKey)
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


class _NoUploadRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        # Never forward upload credentials to a redirect destination.
        return None


def upload_file(path: Path, url: str, attempts: int = 3) -> None:
    if attempts < 1:
        raise ValueError("attempts must be positive")
    headers = {"Content-Length": str(path.stat().st_size)}
    access_key = os.environ.get("HTTP_UPLOAD_KEY")
    if access_key is not None and not access_key.strip():
        raise ValueError("HTTP_UPLOAD_KEY must not be empty (use a dummy value for local testing)")
    if access_key:
        headers["AccessKey"] = access_key
    else:
        authorization = _authorization_header()
        if authorization:
            headers["Authorization"] = authorization
    opener = urllib.request.build_opener(_NoUploadRedirects())
    for attempt in range(1, attempts + 1):
        try:
            with path.open("rb") as source:
                request = urllib.request.Request(url, data=source, headers=headers, method="PUT")
                with opener.open(request, timeout=300) as response:
                    if not 200 <= response.status < 300:
                        raise RuntimeError(f"Upload returned HTTP {response.status}: {url}")
            return
        except (OSError, urllib.error.URLError) as error:
            if isinstance(error, urllib.error.HTTPError):
                error.close()
            if attempt == attempts:
                raise RuntimeError(f"Failed to upload {path} to {url}") from error
            time.sleep(2**attempt)


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

    if args.attempts < 1:
        raise ValueError("--attempts must be positive")
    base_url = args.base_url.rstrip("/")
    for index, path in enumerate(files, start=1):
        relative = path.relative_to(root).as_posix()
        quoted_relative = "/".join(urllib.parse.quote(part) for part in relative.split("/"))
        url = f"{base_url}/{quoted_relative}"
        print(f"[{index}/{len(files)}] PUT {url}")
        if args.dry_run:
            continue

        upload_file(path, url, args.attempts)


if __name__ == "__main__":
    main()
