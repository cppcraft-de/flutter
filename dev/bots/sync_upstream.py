#!/usr/bin/env python3
"""Copy upstream branches/tags to a fork without moving its WSC channel refs.

Preview by default; --apply requests an atomic push. --prune removes stale upstream
branches only. No checkout or builds.
See docs/wsc/upstream-sync.md. Python stdlib and Git only.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


class SyncError(Exception):
    pass


def git(repo: Path, *args: str, env=None) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode:
        detail = (result.stdout + result.stderr).decode("utf-8", errors="replace")
        raise SyncError(f"Git {args[0]} failed ({result.returncode}):\n{detail}")
    return result.stdout.decode("utf-8").strip()


def remote_url(repo: Path, name: str, *, push=False) -> str:
    if name not in git(repo, "remote").splitlines():
        raise SyncError(f"Configure the named remote {name!r} first.")
    urls = git(repo, "remote", "get-url", *(["--push"] if push else []), "--all", name).splitlines()
    if len(urls) != 1:
        raise SyncError(f"Remote {name!r} must have exactly one {'push' if push else 'fetch'} URL.")
    url = urls[0]
    # A relative filesystem remote must still resolve from the temporary repo.
    if (repo / url).exists():
        url = str((repo / url).resolve())
    return url


def read_refs(repo: Path, url: str, *, env=None) -> dict[str, str]:
    output = git(repo, "ls-remote", "--refs", "--heads", "--tags", "--", url, env=env)
    return {ref: oid for oid, ref in (line.split() for line in output.splitlines())}


def destinations(source: dict[str, str]) -> dict[str, str]:
    if not any(ref.startswith("refs/heads/") for ref in source):
        raise SyncError("Source has no branches; check the upstream remote and permissions.")
    return {
        ("refs/heads/upstream/" + ref.removeprefix("refs/heads/")
         if ref.startswith("refs/heads/") else ref): oid
        for ref, oid in source.items()
    }


def check_tags(wanted: dict[str, str], existing: dict[str, str]) -> None:
    conflicts = [ref for ref, oid in wanted.items()
                 if ref.startswith("refs/tags/") and ref in existing and existing[ref] != oid]
    if conflicts:
        raise SyncError("Conflicting upstream tags; nothing pushed. Investigate without reseating tags:\n"
                        + "\n".join(sorted(conflicts)))


def sync(repo: Path, source="upstream", destination="origin", *, apply=False, prune=False) -> None:
    # These override -C and can redirect initialization/fetch into the caller's
    # checkout. Fail before any Git command rather than silently ignoring them.
    overrides = sorted(set(os.environ) & {
        "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY", "GIT_NAMESPACE", "GIT_SHALLOW_FILE",
    })
    if overrides:
        raise SyncError("Unset Git repository overrides before syncing: " + ", ".join(overrides))
    repo = repo.resolve()
    source_url = remote_url(repo, source)
    destination_url = remote_url(repo, destination, push=True)
    if source_url == destination_url:
        raise SyncError("Source and destination must be different repositories.")
    upstream = read_refs(repo, source_url)
    wanted = destinations(upstream)
    existing = read_refs(repo, destination_url)
    check_tags(wanted, existing)
    changed = {ref: oid for ref, oid in wanted.items() if existing.get(ref) != oid}
    stale = sorted(ref for ref in existing.keys() - wanted.keys()
                   if ref.startswith("refs/heads/upstream/"))
    deleted = stale if prune else []
    for ref, oid in sorted(changed.items()):
        print(f"{'UPDATE' if ref in existing else 'CREATE'} {ref}: {existing.get(ref, '(absent)')} -> {oid}")
    for ref in stale:
        if prune:
            print(f"DELETE {ref}: {existing[ref]} (no longer present upstream)")
        else:
            print(f"KEEP {ref}: no longer present upstream (use --prune to delete)")
    print(f"{source} -> {destination}: {len(changed)} changes; {len(deleted)} deletions; "
          f"{len(wanted) - len(changed)} already equal.")
    if not changed and not deleted:
        print("Already synchronized. Nothing pushed.")
        return
    if not apply:
        print("Preview only. Re-run with --apply to push. Non-upstream branches are never changed.")
        return

    # Isolate refs: no local tags (including experimental WSC tags) can leak.
    # Borrow complete existing objects read-only to avoid a fresh Flutter clone.
    env = os.environ.copy()
    if git(repo, "rev-parse", "--is-shallow-repository") == "false":
        objects = Path(git(repo, "rev-parse", "--path-format=absolute", "--git-path", "objects"))
        alternate = json.dumps(objects.as_posix(), ensure_ascii=False)
        previous = env.get("GIT_ALTERNATE_OBJECT_DIRECTORIES")
        env["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = alternate + (os.pathsep + previous if previous else "")
    with tempfile.TemporaryDirectory(prefix="wsc-upstream-sync-") as temporary:
        scratch = Path(temporary)
        git(scratch, "init", "--bare", "--quiet")
        print("Fetching upstream objects into isolated temporary storage...", flush=True)
        git(scratch, "fetch", "--no-tags", "--no-write-fetch-head", "--", source_url,
            "refs/heads/*:refs/heads/*", "refs/tags/*:refs/tags/*", env=env)
        fetched = git(scratch, "for-each-ref", "--format=%(objectname) %(refname)", "refs/heads", "refs/tags", env=env)
        snapshot = {ref: oid for oid, ref in (line.split() for line in fetched.splitlines())}
        if snapshot != upstream:
            raise SyncError("Upstream changed during fetch. Nothing pushed; preview and retry.")
        check_tags(wanted, read_refs(scratch, destination_url, env=env))
        # Keep the plan off the command line: hundreds of explicit leases and
        # refspecs exceed Windows' process argument limit. The private remote's
        # tracking refs supply the leases and are never refreshed after this fetch.
        remote = scratch.name
        tracking = "refs/wsc-sync-expected/"
        refspecs = [f"{oid}:{ref}" for ref, oid in sorted(changed.items())]
        refspecs.extend(f":{ref}" for ref in deleted)
        # Git config uses the same quoting for these strings as JSON (without
        # ASCII escaping). URLs/refnames cannot contain unescaped config syntax.
        quote = lambda value: json.dumps(value, ensure_ascii=False)
        with (scratch / "config").open("a", encoding="utf-8") as config:
            config.write(f"\n[remote {quote(remote)}]\n")
            config.write(f"\turl = {quote(destination_url)}\n")
            config.write(f"\tfetch = refs/heads/upstream/*:{tracking}*\n")
            for refspec in refspecs:
                config.write(f"\tpush = {quote(refspec)}\n")
        git(scratch, "fetch", "--no-tags", "--no-write-fetch-head", "--", remote, env=env)
        expected_refs = git(scratch, "for-each-ref", "--format=%(objectname) %(refname)", tracking, env=env)
        expected = {"refs/heads/upstream/" + ref.removeprefix(tracking): oid
                    for oid, ref in (line.split() for line in expected_refs.splitlines())}
        if expected != {ref: oid for ref, oid in existing.items() if ref.startswith("refs/heads/upstream/")}:
            raise SyncError("Destination changed during fetch. Nothing pushed; preview and retry.")
        # Unqualified --force-with-lease is safe here because the tracking refs
        # live only in this temporary repo. Tags have no tracking mapping, so a
        # planned new tag must still be absent; existing tags are never pushed.
        # Request atomic publication, but do not assume a failing server has
        # rolled back: some Git receive policies can reject refs individually.
        print("Publishing upstream branch changes and missing tags atomically...", flush=True)
        try:
            print(git(scratch, "push", "--atomic", "--porcelain", "--no-follow-tags",
                      "--force-with-lease", "--no-force-if-includes", "--", remote, env=env))
        except SyncError as error:
            raise SyncError(f"{error}\nInspect a fresh preview before retrying: the server may have "
                            "accepted some refs. No automatic rollback was attempted.") from error
        actual = read_refs(scratch, destination_url, env=env)
        if (any(actual.get(ref) != oid for ref, oid in wanted.items())
                or any(ref in actual for ref in deleted)):
            raise SyncError("Push completed but verification differs. Check concurrent writers and rerun preview.")
    print("Synchronization verified. WSC branches/channel refs and destination-only tags were not changed.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2],
                        help="Checkout whose named remotes/objects to use (default: this script's repository)")
    parser.add_argument("--source", default="upstream", help="Named upstream fetch remote")
    parser.add_argument("--destination", default="origin", help="Named fork push remote")
    parser.add_argument("--apply", action="store_true", help="Push changes; default is read-only preview")
    parser.add_argument("--prune", action="store_true",
                        help="Delete destination upstream/* branches absent from source; never delete tags")
    args = parser.parse_args()
    try:
        sync(args.repo, args.source, args.destination, apply=args.apply, prune=args.prune)
    except (SyncError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
