"""Prepare and check the fork's DEPS-managed rendering patches.

Only the dependencies command fetches/syncs or updates expected revisions.
Verification reads existing objects and uses disposable indexes. It never
changes dependency worktrees, indexes, or object stores.
"""

import ast
from contextlib import contextmanager
from dataclasses import dataclass
import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import sync_engine_deps


PATCH_ROOT = "engine/src/flutter/tools/wsc_font_rendering_patches"
DEPENDENCY_PATHS = {
    "skia": "engine/src/flutter/third_party/skia",
    "freetype": "engine/src/flutter/third_party/freetype2",
}


class DependencyError(RuntimeError):
    pass


def git(repo, *args, input=None, env=None, check=True):
    result = subprocess.run(["git", "--no-optional-locks", "-C", str(repo), *map(str, args)], input=input,
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and result.returncode:
        raise DependencyError((result.stdout + result.stderr).decode("utf-8", errors="replace"))
    return result


def output(repo, *args, **kwargs):
    return git(repo, *args, **kwargs).stdout.decode("utf-8").strip()


@dataclass(frozen=True)
class Dependency:
    name: str
    path: Path
    url: str
    revision: str


def read_dependencies(repo):
    """Read only literal dictionaries, string concatenation and Var() from DEPS.

    Do not execute DEPS or silently approximate a newly introduced expression.
    Unsupported formats fail before any fetch, pin update or sync.
    """
    tree = ast.parse((repo / "DEPS").read_text(encoding="utf-8"))
    assignments = {}
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            raise DependencyError("Unsupported DEPS statement; update the reader before dependency setup.")
        for target in statement.targets:
            if not isinstance(target, ast.Name):
                raise DependencyError("Unsupported DEPS mutation; update the reader.")
            if target.id in ("vars", "deps"):
                if target.id in assignments or not isinstance(statement.value, ast.Dict):
                    raise DependencyError(f"Unsupported DEPS assignment: {target.id}")
                assignments[target.id] = statement.value
    def entries(name):
        node = assignments.get(name)
        if node is None:
            raise DependencyError(f"DEPS has no literal {name} dictionary")
        return {key.value: value for key, value in zip(node.keys, node.values)
                if isinstance(key, ast.Constant) and isinstance(key.value, str)}
    variables, dependencies = entries("vars"), entries("deps")
    def evaluate(node, seen=()):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return evaluate(node.left, seen) + evaluate(node.right, seen)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "Var" and len(node.args) == 1 and not node.keywords):
            key = evaluate(node.args[0], seen)
            if key not in variables or key in seen:
                raise DependencyError(f"Unresolved DEPS variable: {key}")
            return evaluate(variables[key], (*seen, key))
        raise DependencyError("Unsupported rendering dependency expression in DEPS; update the reader.")
    result = {}
    for name, relative in DEPENDENCY_PATHS.items():
        if relative not in dependencies:
            raise DependencyError(f"DEPS no longer defines {relative}; update the helper.")
        value = evaluate(dependencies[relative])
        url, separator, revision = value.rpartition("@")
        if not separator or not url or url.startswith("-") or not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise DependencyError(f"DEPS must pin {name} to a full commit SHA.")
        result[name] = Dependency(name, repo / relative, url, revision)
    return result


def load_inventory(directory):
    script = directory / "apply_patches.py"
    spec = importlib.util.spec_from_file_location("update_patch_inventory", script)
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        # Read the current source even if an old same-size .pyc is present.
        exec(compile(script.read_bytes(), str(script), "exec"), module.__dict__)
    finally:
        sys.dont_write_bytecode = previous
    patches = module.selected_patch_files(directory, list(module.PATCH_GROUP_ORDER))
    if {name for name, _ in patches} != set(DEPENDENCY_PATHS):
        raise DependencyError("Dependency patch inventory changed or is empty; update the helper.")
    return module, patches


@contextmanager
def object_workspace(dependency, *, fetch):
    with tempfile.TemporaryDirectory(prefix="flutter-patch-check-") as folder:
        scratch = Path(folder)
        output(scratch, "init", "--bare", "--quiet")
        env = os.environ.copy()
        if (dependency.path / ".git").exists():
            if Path(output(dependency.path, "rev-parse", "--show-toplevel")).resolve() != dependency.path.resolve():
                raise DependencyError(f"Not a separate library checkout: {dependency.path}")
            objects = Path(output(dependency.path, "rev-parse", "--git-path", "objects"))
            if not objects.is_absolute():
                objects = dependency.path / objects
            env["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = str(objects.resolve())
        present = git(scratch, "cat-file", "-e", dependency.revision + "^{commit}", env=env, check=False)
        if present.returncode:
            if not fetch:
                raise DependencyError(f"Missing {dependency.name} revision from DEPS. Run python dev/bots/wsc_rebase.py dependencies.")
            print(f"Fetching {dependency.name} revision {dependency.revision} from DEPS...", flush=True)
            output(scratch, "fetch", "--no-tags", "--no-recurse-submodules", "--depth=1",
                   dependency.url, dependency.revision, env=env)
        env["GIT_INDEX_FILE"] = str(scratch / "check.index")
        output(scratch, "read-tree", dependency.revision, env=env)
        yield scratch, env


def apply_index(scratch, env, patch):
    return git(scratch, "apply", "--cached", "--whitespace=nowarn", "-", env=env,
               input=patch.read_bytes().replace(b"\r\n", b"\n"), check=False)


def port_failure(repo, dependency, patch, scratch, env):
    """Keep earlier patches as a commit, then leave rejected hunks for editing."""
    tree = output(scratch, "write-tree", env=env)
    commit = output(scratch, "-c", "commit.gpgSign=false", "-c", "user.name=Flutter patch helper", "-c",
                    "user.email=patch-helper@localhost", "commit-tree", tree,
                    "-p", dependency.revision, "-m", "Base for repairing dependency patch", env=env)
    folder = Path(tempfile.mkdtemp(prefix=f"{repo.name}-{dependency.name}-patch-", dir=repo.parent))
    output(folder, "init", "--quiet")
    output(folder, "config", "core.autocrlf", "false")
    # Fetch rather than share alternates: the repair folder must survive the
    # temporary object workspace being removed and future dependency syncs.
    if env.get("GIT_ALTERNATE_OBJECT_DIRECTORIES"):
        (scratch / "objects/info/alternates").write_text(
            Path(env["GIT_ALTERNATE_OBJECT_DIRECTORIES"]).as_posix() + "\n", encoding="utf-8")
    output(folder, "fetch", "--no-tags", "--depth=1", str(scratch), commit)
    output(folder, "checkout", "--detach", "FETCH_HEAD")
    result = git(folder, "apply", "--reject", "--whitespace=nowarn", "-", check=False,
                 input=patch.read_bytes().replace(b"\r\n", b"\n"))
    detail = result.stderr.decode("utf-8", errors="replace").strip()
    raise DependencyError(
        f"{dependency.name} patch failed: {patch}\n{detail}\n"
        f"Repair checkout: {folder}\nEarlier patches are committed there; failing hunks are in .rej files.\n"
        f"Fix the files, remove .rej files, stage the patch changes, then save with:\n"
        f'  git -C "{folder}" diff --cached --binary --output="{patch}"\n'
        "Then rerun python dev/bots/wsc_rebase.py dependencies. No dependency sync was started.")


def check_patches(repo, *, fetch=False, repair=False, require_expected=True, paths=None):
    dependencies = read_dependencies(repo)
    if paths:
        dependencies = {name: Dependency(dep.name, paths[name], dep.url, dep.revision)
                        for name, dep in dependencies.items()}
    module, patches = load_inventory(repo / PATCH_ROOT)
    for name, dependency in dependencies.items():
        if require_expected and module.EXPECTED_REVISIONS[name] != dependency.revision:
            raise DependencyError(f"{name}: patch helper revision differs from DEPS. Run python dev/bots/wsc_rebase.py dependencies.")
        if not fetch:
            if not (dependency.path / ".git").exists():
                raise DependencyError(f"Missing {name} checkout. Run python dev/bots/wsc_rebase.py dependencies.")
            head = output(dependency.path, "rev-parse", "HEAD")
            if head != dependency.revision:
                raise DependencyError(f"{name} HEAD {head} differs from DEPS {dependency.revision}. Run python dev/bots/wsc_rebase.py dependencies.")
        with object_workspace(dependency, fetch=fetch) as (scratch, env):
            selected = [patch for owner, patch in patches if owner == name]
            for patch in selected:
                result = apply_index(scratch, env, patch)
                if result.returncode:
                    if repair:
                        port_failure(repo, dependency, patch, scratch, env)
                    raise DependencyError(f"{name} patch failed: {patch}\n" + result.stderr.decode("utf-8", errors="replace"))
            print(f"PASS {name}: {len(selected)} patches on DEPS revision {dependency.revision}", flush=True)
    return dependencies


def actual_tree(path, scratch, env, revision):
    """Hash worktree changes using a disposable index/object store, not its .git."""
    isolated = env.copy()
    objects = Path(output(path, "rev-parse", "--git-path", "objects"))
    if not objects.is_absolute():
        objects = path / objects
    isolated["GIT_OBJECT_DIRECTORY"] = str(scratch / "objects")
    isolated["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = str(objects.resolve())
    isolated["GIT_INDEX_FILE"] = str(scratch / "actual.index")
    changed = git(path, "diff", "HEAD", "--name-only", "-z").stdout
    untracked = git(path, "ls-files", "--others", "--exclude-standard", "-z").stdout
    names = b"".join(b":(literal)" + name + b"\0" for name in (changed + untracked).split(b"\0") if name)
    output(path, "read-tree", revision, env=isolated)
    if names:
        output(path, "add", "-A", "--pathspec-from-file=-", "--pathspec-file-nul", input=names, env=isolated)
    return output(path, "write-tree", env=isolated)


def undo_plan(dependency, inventories):
    path = dependency.path
    if not (path / ".git").exists():
        if path.exists() and any(path.iterdir()):
            raise DependencyError(f"{path} is not a Git checkout; preserve its files before dependency setup.")
        return []
    if git(path, "diff", "--cached", "--quiet", check=False).returncode:
        raise DependencyError(f"{path} has staged edits. Save them before dependency setup.")
    if not output(path, "status", "--porcelain", "--untracked-files=all"):
        return []
    head = output(path, "rev-parse", "HEAD")
    existing = Dependency(dependency.name, path, dependency.url, head)
    with object_workspace(existing, fetch=False) as (scratch, env):
        actual = actual_tree(path, scratch, env, head)
        for patches in inventories:
            selected = [patch for name, patch in patches if name == dependency.name]
            output(scratch, "read-tree", head, env=env)
            applied = []
            for patch in selected:
                if apply_index(scratch, env, patch).returncode:
                    break
                applied.append(patch)
                if output(scratch, "write-tree", env=env) == actual:
                    return list(reversed(applied))
    raise DependencyError(f"{path} contains edits that do not match the recorded patches. "
                          "Save those edits as patches or use a separate worktree; nothing was reset.")


@contextmanager
def previous_inventory(repo):
    branch = output(repo, "branch", "--show-current")
    revision = output(repo, "config", "--local", "--default", "", "--get",
                      f"branch.{branch}.wscRebaseTip") if branch else ""
    if not revision:
        yield []
        return
    with tempfile.TemporaryDirectory(prefix="flutter-previous-patches-") as folder:
        base = Path(folder)
        names = output(repo, "ls-tree", "-r", "--name-only", revision, "--", PATCH_ROOT).splitlines()
        for name in names:
            relative = Path(name).relative_to(PATCH_ROOT)
            destination = base / relative
            destination.resolve().relative_to(base.resolve())
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(git(repo, "show", f"{revision}:{name}").stdout)
        if not (base / "apply_patches.py").exists():
            yield []
        else:
            _, patches = load_inventory(base)
            yield patches


def update_expected(repo, dependencies):
    path = repo / PATCH_ROOT / "apply_patches.py"
    data = path.read_bytes()
    for name, dependency in dependencies.items():
        pattern = rb"(?m)^(EXPECTED_" + name.upper().encode() + rb"_REVISION\s*=\s*['\"])[0-9a-f]{40}(['\"])"
        data, count = re.subn(pattern, lambda m: m[1] + dependency.revision.encode() + m[2], data)
        if count != 1:
            raise DependencyError(f"Cannot update {name}'s expected revision; patch helper format changed.")
    if data != path.read_bytes():
        path.write_bytes(data)
        print("Updated the patch helper's expected revisions to the checked DEPS revisions.", flush=True)


def prepare_dependencies(repo, *, web=False):
    if shutil.which("gclient") is None:
        raise DependencyError("gclient was not found. Install depot_tools and put it on PATH before running dependencies.")
    for relative in DEPENDENCY_PATHS.values():
        try:
            (repo / relative).resolve().relative_to(repo.resolve())
        except ValueError as error:
            raise DependencyError(f"{relative} points outside this checkout; use a separate worktree for setup.") from error
    standard = sync_engine_deps.configuration(repo, False)
    web_config = sync_engine_deps.configuration(repo, True)
    config_path = repo / ".gclient"
    if config_path.exists():
        existing = config_path.read_text(encoding="utf-8")
        if existing not in (standard, web_config):
            raise DependencyError("This checkout has a custom .gclient. Preserve it and use a separate worktree for dependency setup.")
        web = web or existing == web_config
    dependencies = check_patches(repo, fetch=True, repair=True, require_expected=False)
    _, current = load_inventory(repo / PATCH_ROOT)
    with previous_inventory(repo) as previous:
        plans = {name: undo_plan(dep, [current, previous]) for name, dep in dependencies.items()}
        update_expected(repo, dependencies)
        # Check both libraries before changing either. Only exact, recognized
        # patch contents can be undone; unrelated edits and staged work block sync.
        for name, patches in plans.items():
            for patch in patches:
                output(dependencies[name].path, "apply", "--reverse", "--whitespace=nowarn", "-",
                       input=patch.read_bytes().replace(b"\r\n", b"\n"))
    sync_engine_deps.sync(repo, "true", web)
    check_patches(repo)
    # Ensure gclient actually applied every patch, rather than trusting markers.
    for dependency in dependencies.values():
        with object_workspace(dependency, fetch=False) as (scratch, env):
            for name, patch in current:
                if name == dependency.name and apply_index(scratch, env, patch).returncode:
                    raise DependencyError(f"Patch inputs changed during sync: {patch}")
            expected = output(scratch, "write-tree", env=env)
            if actual_tree(dependency.path, scratch, env, dependency.revision) != expected:
                raise DependencyError(f"{dependency.name}: checkout does not contain exactly the expected patches after sync.")
    print("DEPENDENCIES READY. Commit any updated patch files and expected revisions, then update the engine pin.")
