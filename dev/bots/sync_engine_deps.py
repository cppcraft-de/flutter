#!/usr/bin/env python3
"""CI-local gclient sync policy; never deletes or relocates build outputs."""

import argparse
import hashlib
import os
from pathlib import Path
import platform
import subprocess


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args])


def configuration(root, web):
    config = (root / "engine/scripts/standard.gclient").read_text(encoding="utf-8")
    if web:
        disabled = '    # "custom_vars": {\n    #   "download_emsdk": True,\n    # },'
        enabled = '    "custom_vars": {\n      "download_emsdk": True,\n    },'
        if disabled not in config:
            raise ValueError("standard.gclient no longer contains the documented Web custom_vars block")
        config = config.replace(disabled, enabled)
    return config


def host_name():
    if platform.system() == "Windows":
        return "windows-x64"
    os_name = {"Linux": "linux", "Darwin": "macos"}[platform.system()]
    cpu = {"x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}[platform.machine().lower()]
    return f"{os_name}-{cpu}"


def fingerprint(root, config, host):
    # Track source contents, not branch names, HEAD, tags, or mtimes. Cover the
    # tools subtree conservatively: it contains patch scripts and local hooks
    # plus their helpers. Nested dependency hook code is pinned through DEPS.
    paths = git(
        root, "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "DEPS", ":(glob)**/DEPS",
        "engine/scripts/standard.gclient", "engine/src/flutter/tools",
        ":(glob)engine/**/pubspec.yaml", ":(glob)engine/**/pubspec.lock",
        "dev/bots/sync_engine_deps.py",
    ).decode("utf-8").split("\0")
    digest = hashlib.sha256(("v2\0" + host + "\0" + config).encode())
    for name in sorted(set(filter(None, paths))):
        digest.update(name.encode() + b"\0")
        path = root / name
        # A patch may be added or removed while being ported, before git add.
        digest.update(b"file\0" + hashlib.sha256(path.read_bytes()).digest()
                      if path.exists() else b"deleted\0")
    return digest.hexdigest()


def dependencies_present(root, host):
    dart = root / f"engine/src/flutter/prebuilts/{host}/dart-sdk/bin/dart"
    if host.startswith("windows-"):
        dart = dart.with_suffix(".exe")
    return (
        (root / ".gclient").is_file() and dart.is_file()
        and (host.startswith("windows-") or os.access(dart, os.X_OK))
        and all((root / f"engine/src/flutter/third_party/{name}/.git").exists()
                for name in ("skia", "freetype2"))
    )


def run_gclient(root, web):
    # Reduce bursts against upstream Git servers; compilation is unaffected.
    command = ["gclient", "sync", "-D", "-j", "1" if web else "2"]
    # Windows depot_tools supplies a batch command. Arguments are constants.
    subprocess.run(command, cwd=root, check=True, shell=os.name == "nt")


def sync(root, mode, web=False):
    if mode not in ("auto", "true", "false"):
        raise ValueError(f"Invalid dependency sync mode: {mode}")
    root = root.resolve()
    if Path(git(root, "rev-parse", "--show-toplevel").decode().strip()).resolve() != root:
        raise ValueError("Run from the engine workspace's Flutter checkout root")
    config = configuration(root, web)
    host = host_name()
    desired = fingerprint(root, config, host)
    marker = Path(git(root, "rev-parse", "--git-path", "wsc-deps-sync.sha256").decode().strip())
    if not marker.is_absolute():
        marker = root / marker
    previous = marker.read_text().strip() if marker.is_file() else None
    present = dependencies_present(root, host)
    config_matches = (root / ".gclient").is_file() and (root / ".gclient").read_text(encoding="utf-8") == config
    if present and (mode == "false" or (mode == "auto" and previous == desired and config_matches)):
        print(f"Skipping dependency sync ({mode}); " + ("explicit override." if mode == "false" else "inputs unchanged."), flush=True)
        return

    reason = "forced" if mode == "true" else "missing dependencies or changed/unrecorded inputs"
    print(f"Synchronizing dependencies ({mode}): {reason}. Ninja outputs are retained.", flush=True)
    # Invalidate first, including forced attempts, so failures/interruptions
    # cannot leave a successful stamp for a partially changed dependency tree.
    marker.unlink(missing_ok=True)
    (root / ".gclient").write_text(config, encoding="utf-8")
    run_gclient(root, web)
    if not dependencies_present(root, host):
        raise RuntimeError("gclient returned success but required dependency sentinels are missing")
    if fingerprint(root, config, host) != desired:
        raise RuntimeError("Dependency inputs changed during sync; no success marker recorded")
    marker.write_text(desired + "\n", encoding="ascii")
    print("Dependency sync succeeded; recorded workspace-local fingerprint.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("auto", "true", "false"), default="auto")
    parser.add_argument("--web", action="store_true")
    args = parser.parse_args()
    sync(Path.cwd(), args.mode, args.web)


if __name__ == "__main__":
    main()
