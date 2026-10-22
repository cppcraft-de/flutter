#!/usr/bin/env python3
"""Prepare and source-check WSC update candidates. See docs/wsc/updating.md.

No network, pushes, tags, builds, cleanup, or release approval. Git owns replay
state. Preparation only writes when --apply is supplied; verification does not
repair files. Optional dependency checks use disposable Git indexes/objects.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from engine_identity import head_content_hash


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


def require_clean(repo):
    if git(repo, "rev-parse", "--is-shallow-repository") != "false":
        raise WorkflowError("Full Git history is required; this checkout is shallow.")
    for state in ("CHERRY_PICK_HEAD", "MERGE_HEAD", "REVERT_HEAD", "sequencer", "rebase-merge", "rebase-apply"):
        state_path = Path(git(repo, "rev-parse", "--git-path", state))
        if not state_path.is_absolute():
            state_path = repo / state_path
        if state_path.exists():
            raise WorkflowError(f"Finish or abort the existing Git operation first: {state}")
    status = git(repo, "status", "--porcelain", "--untracked-files=normal")
    if status:
        raise WorkflowError(f"Checkout must be clean, including untracked files. Nothing was stashed or removed.\n{status}")


def linear_tail(repo, base, tip):
    # Structural check only: a human must confirm these commits are WSC changes.
    git(repo, "merge-base", "--is-ancestor", base, tip)
    commits = git(repo, "rev-list", "--reverse", f"{base}..{tip}").splitlines()
    if not commits:
        raise WorkflowError("Selected WSC commit range is empty.")
    previous = base
    for commit in commits:
        parents = git(repo, "show", "-s", "--format=%P", commit).split()
        if parents != [previous]:
            raise WorkflowError("Range must be a linear tail directly on the selected base (no merges).")
        previous = commit
    return commits


def prepare(args):
    repo = root(args.repo)
    require_clean(repo)
    old, tip, new = (resolve(repo, ref) for ref in (args.old_base, args.tip, args.new_base))
    commits = linear_tail(repo, old, tip)
    if old == new:
        raise WorkflowError("Old and new upstream bases are identical.")
    git(repo, "check-ref-format", "--branch", args.branch)
    if args.branch.startswith("-") or args.branch == "HEAD":
        raise WorkflowError("Use an ordinary new candidate branch name.")
    if git(repo, "branch", "--list", args.branch):
        raise WorkflowError(f"Candidate branch already exists: {args.branch}")
    destination = args.worktree.absolute()
    if destination.exists() or destination.is_symlink():
        raise WorkflowError(f"Worktree destination must not exist: {destination}")
    destination = destination.resolve()
    if destination == repo or repo in destination.parents:
        raise WorkflowError("Create the candidate outside the source checkout, not inside a build/workspace tree.")

    print(f"Old upstream: {old}\nWSC tip:      {tip}\nNew upstream: {new}")
    print(f"Candidate: {args.branch}\nWorktree:  {destination}\nReplay:")
    for commit in commits:
        print("  " + git(repo, "show", "-s", "--format=%h %s", commit))
    print("Review this range: Git cannot determine whether every commit is an intended WSC change.")
    if not args.apply:
        print("PREVIEW ONLY. Re-run with --apply after approving the range and destination.")
        return

    git(repo, "worktree", "add", "-b", args.branch, str(destination), new)
    try:
        # Feed the immutable, explicitly reviewed sequence without a command-line
        # length limit. Do not auto-skip empty commits or resolve conflicts.
        git(destination, "cherry-pick", "--stdin", input=("\n".join(commits) + "\n").encode())
    except WorkflowError:
        print(f"Replay stopped. Candidate preserved at {destination}.", file=sys.stderr)
        print("Inspect git status there; resolve and git cherry-pick --continue, or --abort.", file=sys.stderr)
        print("Do not rerun prepare or blindly skip commits. See docs/wsc/updating.md.", file=sys.stderr)
        raise
    print("Replay completed. Inspect git range-diff, then follow the dependency/pin/check steps in the guide.")
    print("No dependencies synchronized, engine compiled, refs published, or release approved.")


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


def check_dependency_patches(repo, skia, freetype):
    """Apply ordered patches to pristine committed trees, never nested worktrees.

    Reuse the candidate patch inventory rather than maintain a second list. A
    temporary bare repo reads existing objects but writes new blobs/indexes only
    to its own directory. Dirty nested files and their mtimes are not touched.
    """
    script = repo / "engine/src/flutter/tools/wsc_font_rendering_patches/apply_patches.py"
    spec = importlib.util.spec_from_file_location("wsc_candidate_patches", script)
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    patch_files = module.selected_patch_files(script.parent, list(module.PATCH_GROUP_ORDER))
    if not patch_files:
        raise WorkflowError("Candidate patch inventory is empty.")
    if {name for name, _ in patch_files} != {"skia", "freetype"}:
        raise WorkflowError("Dependency inventory changed; update this checker instead of skipping repositories.")
    for name, dependency in (("skia", skia), ("freetype", freetype)):
        dependency = dependency.resolve()
        if root(dependency) != dependency:
            raise WorkflowError(f"Not a separate {name} Git checkout: {dependency}")
        revision = resolve(dependency, "HEAD")
        if revision != module.EXPECTED_REVISIONS[name]:
            raise WorkflowError(f"{name} HEAD {revision} differs from candidate EXPECTED_REVISIONS; review DEPS and sync/port explicitly.")
        selected = [path for owner, path in patch_files if owner == name]
        if not selected:
            raise WorkflowError(f"No candidate patches for {name}.")
        objects = Path(git(dependency, "rev-parse", "--git-path", "objects"))
        if not objects.is_absolute():
            objects = dependency / objects
        with tempfile.TemporaryDirectory(prefix="wsc-patch-check-") as temporary:
            scratch = Path(temporary)
            git(scratch, "init", "--bare", "--quiet")
            environment = os.environ.copy()
            environment["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = str(objects.resolve())
            environment["GIT_INDEX_FILE"] = str(scratch / "check.index")
            git(scratch, "read-tree", revision, env=environment)
            for patch in selected:
                # Patch files checked out on Windows can contain CRLF; the Git
                # object trees have canonical LF content.
                data = patch.read_bytes().replace(b"\r\n", b"\n")
                git(scratch, "apply", "--cached", "--whitespace=nowarn", "-", env=environment, input=data)
            print(f"PASS {name}: {len(selected)} ordered patches on pristine {revision}")
    print("Patch applicability only: does not verify DEPS resolution, the existing nested working files, hook idempotence, or rendering.")


def verify(args):
    repo = root(args.repo)
    require_clean(repo)
    base, tip = resolve(repo, args.new_base), resolve(repo, "HEAD")
    commits = linear_tail(repo, base, tip)
    print(f"Candidate: {tip}\nUpstream:  {base}\nWSC tail:  {len(commits)} commits")
    git(repo, "diff", "--check", f"{base}..{tip}")
    print("PASS Git structure and diff whitespace")
    check_pin(repo)
    validator = repo / "dev/bots/validate_sdk_identity.py"
    print(run([sys.executable, "-B", validator, "--revision", tip], repo))
    for filename in ("test_engine_identity.py", "test_collect_engine_artifacts.py", "test_verify_maven_artifacts.py", "test_validate_sdk_identity.py", "test_artifact_publishing.py", "test_wsc_rebase.py"):
        if not (repo / "dev/bots" / filename).is_file():
            raise WorkflowError(f"Missing expected test file: {filename}")
        print(run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "dev/bots", "-p", filename], repo))
        print(f"PASS {filename}")
    if args.skia_dir:
        check_dependency_patches(repo, args.skia_dir, args.freetype_dir)
    else:
        print("PENDING dependency patch applicability: supply --skia-dir and --freetype-dir after reviewing DEPS.")
    require_clean(repo)
    print("SOURCE CHECKS PASSED, NOT RELEASE APPROVAL.")
    print("PENDING Dart/Flutter tests, dependency sync/hook checks, engine/SDK builds and extracted-SDK smoke tests.")
    print("PENDING rendering equivalence: review FRT results from Jenkins or a developer run; see docs/wsc/rendering-regression.md.")
    print("PENDING diagnostics-disabled overhead and release approval. See docs/wsc/updating.md.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    preparation = commands.add_parser("prepare", help="Preview a replay; --apply creates an isolated candidate")
    preparation.add_argument("--repo", type=Path, default=Path.cwd())
    preparation.add_argument("--old-base", required=True)
    preparation.add_argument("--tip", required=True)
    preparation.add_argument("--new-base", required=True)
    preparation.add_argument("--branch", required=True)
    preparation.add_argument("--worktree", type=Path, required=True)
    preparation.add_argument("--apply", action="store_true")
    preparation.set_defaults(handler=prepare)
    verification = commands.add_parser("verify", help="Check committed candidate sources, not release readiness")
    verification.add_argument("--repo", type=Path, default=Path.cwd())
    verification.add_argument("--new-base", required=True)
    verification.add_argument("--skia-dir", type=Path)
    verification.add_argument("--freetype-dir", type=Path)
    verification.set_defaults(handler=verify)
    args = parser.parse_args(argv)
    if args.operation == "verify" and bool(args.skia_dir) != bool(args.freetype_dir):
        parser.error("Supply both --skia-dir and --freetype-dir, or neither.")
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
    except (WorkflowError, OSError, AttributeError, KeyError, ImportError, SyntaxError) as error:
        parser.exit(1, f"WSC workflow stopped: {error}\n")


if __name__ == "__main__":
    main()
