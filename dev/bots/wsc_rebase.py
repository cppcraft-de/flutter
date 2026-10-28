#!/usr/bin/env python3
"""Rebase the fork in the current worktree. See docs/wsc/updating.md.

Rebase fetches upstream history and creates a local update branch. It never
pushes, moves release tags, builds, or cleans workspaces. Git owns rebase state.
Verification does not repair files or approve a release.
"""

from __future__ import annotations

import argparse
from bisect import bisect_left
from contextlib import contextmanager
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

from engine_identity import head_content_hash
import wsc_dependency_patches as dependency_patches


class WorkflowError(Exception):
    pass


def run(command, cwd, *, env=None, input=None):
    result = subprocess.run(
        [str(part) for part in command], cwd=cwd, env=env, input=input,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode:
        detail = (result.stdout + result.stderr).decode("utf-8", errors="replace")
        raise WorkflowError(f"Command failed ({result.returncode}): {' '.join(map(str, command))}\n{detail}")
    return result.stdout.decode("utf-8", errors="replace").strip()


def git(repo, *args, **kwargs):
    return run(["git", "-C", repo, *args], repo, **kwargs)


def root(path):
    return Path(git(path, "rev-parse", "--show-toplevel")).resolve()


def resolve(repo, ref):
    return git(repo, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}")


def require_no_git_operation(repo):
    for state in ("CHERRY_PICK_HEAD", "MERGE_HEAD", "REVERT_HEAD", "sequencer", "rebase-merge", "rebase-apply"):
        state_path = Path(git(repo, "rev-parse", "--git-path", state))
        if not state_path.is_absolute():
            state_path = repo / state_path
        if state_path.exists():
            raise WorkflowError(f"Finish or abort the existing Git operation first: {state}")


def require_clean(repo):
    if git(repo, "rev-parse", "--is-shallow-repository") != "false":
        raise WorkflowError("Full Git history is required; this checkout is shallow.")
    require_no_git_operation(repo)
    status = git(repo, "status", "--porcelain", "--untracked-files=normal")
    if status:
        raise WorkflowError(f"Checkout must be clean, including untracked files. Nothing was stashed or removed.\n{status}")


def linear_tail(repo, base, tip):
    git(repo, "merge-base", "--is-ancestor", base, tip)
    commits = git(repo, "rev-list", "--reverse", f"{base}..{tip}").splitlines()
    if not commits:
        raise WorkflowError("Selected fork commit range is empty.")
    previous = base
    for commit in commits:
        parents = git(repo, "show", "-s", "--format=%P", commit).split()
        if parents != [previous]:
            raise WorkflowError("Range must be a linear tail directly on the selected base (no merges).")
        previous = commit
    return commits


@contextmanager
def upstream_snapshot(repo, remote):
    """Fetch only the named remote's heads/tags into a private, temporary namespace.

    Local tags and stale remote-tracking refs are not evidence of upstream
    membership. Do not overwrite either, including FETCH_HEAD. UUID isolation
    also keeps simultaneous runs in other worktrees from sharing snapshots.
    """
    if remote not in git(repo, "remote").splitlines():
        raise WorkflowError(f"Configure remote {remote!r} for official Flutter first; see the update guide.")
    namespace = f"refs/wsc-rebase-upstream/{uuid.uuid4().hex}"
    try:
        print(f"Fetching official Flutter history from {remote}...", flush=True)
        git(repo, "fetch", "--atomic", "--no-tags", "--no-prune", "--no-prune-tags",
            "--no-write-fetch-head", "--refmap=",
            "--no-recurse-submodules", remote,
            f"+refs/heads/*:{namespace}/heads/*", f"+refs/tags/*:{namespace}/tags/*")
        refs = git(repo, "for-each-ref", "--format=%(refname)", namespace + "/").splitlines()
        if not refs:
            raise WorkflowError(f"Remote {remote!r} has no branches or tags.")
        yield namespace, refs
    finally:
        refs = git(repo, "for-each-ref", "--format=%(refname)", namespace + "/").splitlines()
        if refs:
            git(repo, "update-ref", "--stdin",
                input="".join(f"delete {ref}\n" for ref in refs).encode())


def outside_upstream(repo, tip, refs, *, first_only=False):
    # stdin avoids Windows command-line limits with thousands of upstream tags.
    revisions = "\n".join([tip, *("^" + ref for ref in refs)]) + "\n"
    options = ["--max-count=1"] if first_only else []
    return git(repo, "rev-list", *options, "--stdin", input=revisions.encode()).splitlines()


def upstream_target(repo, name, remote, namespace, refs):
    if name.startswith("refs/tags/"):
        candidates = [namespace + "/tags/" + name.removeprefix("refs/tags/")]
    elif name.startswith("refs/heads/"):
        candidates = [namespace + "/heads/" + name.removeprefix("refs/heads/")]
    elif name.startswith(f"refs/remotes/{remote}/"):
        candidates = [namespace + "/heads/" + name.removeprefix(f"refs/remotes/{remote}/")]
    elif name.startswith(remote + "/"):
        candidates = [namespace + "/heads/" + name.removeprefix(remote + "/")]
    else:
        candidates = [namespace + "/tags/" + name, namespace + "/heads/" + name]
    matches = [ref for ref in candidates if ref in refs]
    if len(matches) > 1:
        raise WorkflowError(f"Upstream has both a tag and branch named {name!r}; use refs/tags/ or refs/heads/.")
    if matches:
        return resolve(repo, matches[0])
    if not re.fullmatch(r"[0-9a-fA-F]{7,40}", name):
        raise WorkflowError(f"No upstream branch or tag named {name!r}. Supply an upstream name or commit SHA.")
    commit = resolve(repo, name)
    if outside_upstream(repo, commit, refs, first_only=True):
        raise WorkflowError(f"Target {name!r} is not in the fetched upstream history.")
    return commit


def find_old_base(repo, tip, refs):
    remaining = set(outside_upstream(repo, tip, refs))
    if not remaining:
        raise WorkflowError("The fork tip is already upstream; there are no fork patches to rebase.")
    commit = tip
    while commit in remaining:
        parents = git(repo, "show", "-s", "--format=%P", commit).split()
        if not parents:
            raise WorkflowError("Cannot find the fork's base in the fetched upstream history.")
        if len(parents) != 1:
            raise WorkflowError("Fork patches must be a linear tail (no merges).")
        commit = parents[0]
    return commit


def update_branch(repo, requested, new, target_name):
    if requested:
        git(repo, "check-ref-format", "--branch", requested)
        if requested.startswith("-") or requested == "HEAD":
            raise WorkflowError("Use an ordinary new branch name.")
        if git(repo, "branch", "--list", requested):
            raise WorkflowError(f"Update branch already exists: {requested}")
        return requested
    label = target_name.removeprefix("refs/tags/")
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-.a-zA-Z0-9]+)?", label):
        label = new[:12]
    stem = f"flutter-update-{label}"
    branch, number = stem, 2
    while git(repo, "branch", "--list", branch):
        branch, number = f"{stem}-{number}", number + 1
    return branch


def protect_ignored_files(repo, tip, new, commits):
    """Git rebase can overwrite ignored files; refuse collisions before switching.

    --directory keeps ignored build/dependency trees from being enumerated.
    Include intermediate patch paths, not just the final tree: a patch may add
    a file that a later patch deletes again.
    """
    ignored = git(repo, "ls-files", "--others", "--ignored", "--exclude-standard",
                  "--directory", "-z").split("\0")
    ignored = [path for path in ignored if path]
    if not ignored:
        return
    paths = []
    for revision in (tip, new):
        paths.extend(git(repo, "ls-tree", "-r", "--name-only", "-z", revision).split("\0"))
    paths.extend(git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "-z",
                     "--stdin", input=("\n".join(commits) + "\n").encode()).split("\0"))
    ignore_case = git(repo, "config", "--type=bool", "--default", "false", "--get", "core.ignorecase") == "true"
    def normalize(path):
        return path.casefold() if ignore_case or os.name == "nt" else path
    tracked = {normalize(path) for path in paths if path}
    ordered = sorted(tracked)
    for original in ignored:
        path = normalize(original).rstrip("/")
        prefix = path + "/"
        index = bisect_left(ordered, prefix)
        ancestors = ["/".join(path.split("/")[:i]) for i in range(1, len(path.split("/")) + 1)]
        if any(parent in tracked for parent in ancestors) or (
                index < len(ordered) and ordered[index].startswith(prefix)):
            raise WorkflowError(f"Rebase could overwrite ignored local files at {original!r}. "
                                "Save them elsewhere or use a separate clean worktree.")


def rebase(args):
    repo = root(args.repo)
    require_clean(repo)
    version = re.search(r"\b(\d+)\.(\d+)", git(repo, "--version"))
    if not version or tuple(map(int, version.groups())) < (2, 45):
        raise WorkflowError("Rebasing with this helper requires Git 2.45 or newer.")
    tip = resolve(repo, args.tip)
    with upstream_snapshot(repo, args.upstream) as (namespace, refs):
        new = upstream_target(repo, args.new_base, args.upstream, namespace, refs)
        old = find_old_base(repo, tip, refs)
        commits = linear_tail(repo, old, tip)
    if old == new:
        raise WorkflowError("The fork is already based on the requested upstream commit.")
    branch = update_branch(repo, args.branch, new, args.new_base)
    protect_ignored_files(repo, tip, new, commits)
    print(f"Fork tip: {tip}\nDetected old base: {old}\nNew base: {new}\nUpdate branch: {branch}")
    print(f"Rebasing {len(commits)} commits in {repo}:")
    for commit in commits:
        print("  " + git(repo, "show", "-s", "--format=%h %s", commit))
    print(f"After rebasing, compare patches with:\n  git range-diff {old}..{tip} {new}..HEAD", flush=True)
    if args.dry_run:
        print("PREVIEW ONLY. Upstream history was fetched; no branch or working files were changed.")
        return

    require_clean(repo)
    git(repo, "switch", "--no-overwrite-ignore", "-c", branch, tip)
    # Local convenience for `verify`; not release metadata or rebase-resume state.
    git(repo, "config", f"branch.{branch}.wscRebaseBase", new)
    git(repo, "config", f"branch.{branch}.wscRebaseTip", tip)
    try:
        git(repo, "rebase", "--merge", "--onto", new, "--no-fork-point", "--no-autostash",
            "--no-update-refs", "--no-autosquash", "--no-rebase-merges",
            "--no-rerere-autoupdate", "--reapply-cherry-picks", "--keep-empty",
            "--empty=stop", old)
    except WorkflowError:
        print(f"Rebase did not finish. Your update branch is {branch} in {repo}.", file=sys.stderr)
        print("Run git status. If paused, resolve and git rebase --continue, or git rebase --abort.", file=sys.stderr)
        print("Do not rerun the helper during a rebase. See docs/wsc/updating.md.", file=sys.stderr)
        raise
    print(f"Rebase completed on {branch}. Original branches and tags were not moved.")
    print("Next, prepare and check the dependency patches:")
    print("  python dev/bots/wsc_rebase.py dependencies")


def expected_engine(repo):
    try:
        return head_content_hash(repo)
    except (ValueError, subprocess.CalledProcessError) as error:
        raise WorkflowError(f"Cannot determine committed engine content hash: {error}") from error


def check_pin(repo):
    expected = expected_engine(repo)
    pin = repo / "bin/internal/engine.version"
    actual = pin.read_text().strip() if pin.is_file() else "<missing>"
    git(repo, "ls-files", "--error-unmatch", "bin/internal/engine.version")
    if actual != expected:
        raise WorkflowError(f"Engine pin is {actual}; expected {expected}. Update and commit the pin; see the guide.")
    print(f"PASS engine pin: {expected}")


def check_dependency_patches(repo, skia=None, freetype=None):
    paths = None
    if skia or freetype:
        paths = {
            "skia": (skia or repo / dependency_patches.DEPENDENCY_PATHS["skia"]).resolve(),
            "freetype": (freetype or repo / dependency_patches.DEPENDENCY_PATHS["freetype"]).resolve(),
        }
    try:
        dependency_patches.check_patches(repo, paths=paths)
    except dependency_patches.DependencyError as error:
        raise WorkflowError(str(error)) from error


def dependencies(args):
    repo = root(args.repo)
    # Patch edits are allowed here; an unfinished rebase is not.
    require_no_git_operation(repo)
    dependency_patches.prepare_dependencies(repo, web=args.web)


def verify(args):
    repo = root(args.repo)
    require_clean(repo)
    base_name = args.new_base
    if not base_name:
        branch = git(repo, "branch", "--show-current")
        base_name = git(repo, "config", "--local", "--default", "", "--get",
                        f"branch.{branch}.wscRebaseBase") if branch else None
        if not base_name:
            raise WorkflowError("No saved update base on this branch. Supply verify --new-base with the upstream commit or tag.")
    base, tip = resolve(repo, base_name), resolve(repo, "HEAD")
    commits = linear_tail(repo, base, tip)
    print(f"Candidate: {tip}\nUpstream:  {base}\nWSC tail:  {len(commits)} commits")
    git(repo, "diff", "--check", f"{base}..{tip}")
    print("PASS Git structure and diff whitespace")
    check_pin(repo)
    validator = repo / "dev/bots/validate_sdk_identity.py"
    print(run([sys.executable, "-B", validator, "--revision", tip], repo))
    for filename in ("test_engine_identity.py", "test_collect_engine_artifacts.py", "test_verify_maven_artifacts.py", "test_validate_sdk_identity.py", "test_artifact_publishing.py", "test_wsc_rebase.py", "test_wsc_dependency_patches.py", "test_sync_engine_deps.py"):
        if not (repo / "dev/bots" / filename).is_file():
            raise WorkflowError(f"Missing expected test file: {filename}")
        print(run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "dev/bots", "-p", filename], repo))
        print(f"PASS {filename}")
    check_dependency_patches(repo, args.skia_dir, args.freetype_dir)
    require_clean(repo)
    print("SOURCE CHECKS PASSED, NOT RELEASE APPROVAL.")
    print("PENDING Dart/Flutter tests, dependency sync/hook checks, engine/SDK builds and extracted-SDK smoke tests.")
    print("PENDING rendering equivalence: review FRT results from Jenkins or a developer run; see docs/wsc/rendering-regression.md.")
    print("PENDING diagnostics-disabled overhead and release approval. See docs/wsc/updating.md.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    rebasing = commands.add_parser("rebase", help="Fetch upstream and rebase onto a new version in this worktree")
    rebasing.add_argument("--repo", type=Path, default=Path.cwd())
    rebasing.add_argument("--tip", required=True, help="Fork tag, branch, or commit to carry forward")
    rebasing.add_argument("--new-base", required=True, help="Official upstream tag, branch, or commit")
    rebasing.add_argument("--upstream", default="upstream", help="Official Flutter remote (default: upstream)")
    rebasing.add_argument("--branch", help="Name for the new update branch (default: generated)")
    rebasing.add_argument("--dry-run", action="store_true", help="Fetch and show the plan without switching or rebasing")
    rebasing.set_defaults(handler=rebase)
    setup = commands.add_parser("dependencies", help="Check DEPS patches, prepare repairs if needed, then sync dependencies")
    setup.add_argument("--repo", type=Path, default=Path.cwd())
    setup.add_argument("--web", action="store_true", help="Include the Web engine toolchain")
    setup.set_defaults(handler=dependencies)
    verification = commands.add_parser("verify", help="Check committed candidate sources, not release readiness")
    verification.add_argument("--repo", type=Path, default=Path.cwd())
    verification.add_argument("--new-base", help="Upstream commit or tag (default: base saved by rebase on this branch)")
    verification.add_argument("--skia-dir", type=Path, help="Override the standard Skia checkout path")
    verification.add_argument("--freetype-dir", type=Path, help="Override the standard FreeType checkout path")
    verification.set_defaults(handler=verify)
    args = parser.parse_args(argv)
    # Avoid inheriting alternate-index/repository settings from a parent Git
    # hook or shell and accidentally operating on a different checkout.
    overrides = [key for key in os.environ if key in {
        "GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    }]
    if overrides:
        parser.exit(1, f"Unset Git repository overrides before running: {', '.join(overrides)}\n")
    try:
        args.handler(args)
    except (WorkflowError, RuntimeError, ValueError, OSError, AttributeError, KeyError, ImportError, SyntaxError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"WSC workflow stopped: {error}\n")


if __name__ == "__main__":
    main()
