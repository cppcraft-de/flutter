#!/usr/bin/env python3
"""Verify published Maven objects through the SDK's anonymous download endpoint."""

import argparse
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request


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
                        raise ValueError(f"Unexpected HTTP status for {relative}: {response.status}")
                    if is_pom:
                        # Bound reads so a bad endpoint cannot return an unbounded page.
                        if response.read(path.stat().st_size + 1) != path.read_bytes():
                            raise ValueError(f"Published POM differs from staged artifact: {relative}")
                    elif response.headers.get("Content-Length") != str(path.stat().st_size):
                        raise ValueError(f"Published JAR size differs from staged artifact: {relative}")
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
