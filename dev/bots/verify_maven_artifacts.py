#!/usr/bin/env python3
"""Verify published Maven objects through the SDK's anonymous download endpoint."""

import argparse
import json
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request


def response_details(response) -> str:
    # Allowlist diagnostic headers: never dump arbitrary headers, credentials,
    # response bodies or signed request URLs into the build log.
    names = (
        "Content-Length", "Content-Encoding", "Content-Type", "ETag",
        "Last-Modified", "Date", "Age", "Cache-Control", "Via", "X-Cache",
        "CDN-Cache", "CDN-CachedAt", "CDN-RequestId", "CDN-Status",
    )
    headers = {name: str(response.headers[name])[:500]
               for name in names if response.headers.get(name) is not None}
    return f"HTTP {response.status}; response headers: {json.dumps(headers, sort_keys=True)}"


def verify(root: Path, base_url: str, attempts: int = 6) -> None:
    files = sorted((root / "download.flutter.io").rglob("*"))
    files = [path for path in files if path.is_file()]
    if not files:
        raise ValueError("No staged Maven artifacts to verify")
    for path in files:
        relative = path.relative_to(root).as_posix()
        url = base_url.rstrip("/") + "/" + urllib.parse.quote(relative, safe="/")
        is_pom = path.suffix == ".pom"
        request = urllib.request.Request(url, method="GET" if is_pom else "HEAD")
        for attempt in range(attempts):
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    if response.status != 200:
                        raise ValueError(f"Unexpected HTTP status for {relative}: {response_details(response)}")
                    expected_size = path.stat().st_size
                    if is_pom:
                        # Bound reads so a bad endpoint cannot return an unbounded page.
                        received = response.read(expected_size + 1)
                        if received != path.read_bytes():
                            raise ValueError(
                                f"Published POM differs from staged artifact: {relative}; "
                                f"expected size={expected_size} bytes; read={len(received)} bytes "
                                f"(capped at {expected_size + 1}); {response_details(response)}"
                            )
                    elif response.headers.get("Content-Length") != str(expected_size):
                        raise ValueError(
                            f"Published JAR size differs from staged artifact: {relative}; "
                            f"expected size={expected_size} bytes; "
                            f"received Content-Length={response.headers.get('Content-Length', '<missing>')!r}; "
                            f"{response_details(response)}"
                        )
                break
            except urllib.error.HTTPError as error:
                error.close()
                if error.code != 404 or attempt == attempts - 1:
                    raise
                time.sleep(5)
        print(f"Verified Maven artifact: {relative}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    verify(args.root, args.base_url)
