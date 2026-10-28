"""Offline workflow tests using disposable repositories, never real branches."""

import argparse
from contextlib import redirect_stdout, redirect_stderr
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import wsc_rebase as workflow


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wsc-replay-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.repo = self.directory / "source"
        self.init_repo(self.repo)
        self.write(self.repo, "shared.txt", "original\n")
        self.old = self.commit(self.repo, "Upstream base")
        workflow.git(self.repo, "checkout", "-b", "wsc")
        self.write(self.repo, "wsc.txt", "feature\n")
        self.tip = self.commit(self.repo, "WSC feature")
        workflow.git(self.repo, "checkout", "-b", "upstream-next", self.old)
        self.write(self.repo, "upstream.txt", "new upstream\n")
        self.new = self.commit(self.repo, "Upstream update")
        workflow.git(self.repo, "checkout", "wsc")
        self.upstream = self.directory / "official"
        workflow.git(self.directory, "clone", "--bare", str(self.repo), str(self.upstream))
        workflow.git(self.upstream, "update-ref", "refs/heads/main", self.new)
        workflow.git(self.upstream, "update-ref", "-d", "refs/heads/wsc")
        workflow.git(self.upstream, "update-ref", "-d", "refs/heads/upstream-next")
        workflow.git(self.upstream, "symbolic-ref", "HEAD", "refs/heads/main")
        workflow.git(self.repo, "remote", "add", "upstream", str(self.upstream))
        self.args = argparse.Namespace(
            repo=self.repo, tip=self.tip, new_base=self.new,
            upstream="upstream", branch="candidate", dry_run=False,
        )

    def init_repo(self, repo):
        repo.mkdir(parents=True)
        workflow.git(repo, "init", "--quiet")
        for key, value in {
            "user.name": "Workflow Fixture", "user.email": "fixture@example.invalid",
            "commit.gpgSign": "false", "core.autocrlf": "false",
            "core.hooksPath": str(self.directory / "no-hooks"),
        }.items():
            workflow.git(repo, "config", key, value)

    def write(self, repo, name, content):
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")

    def commit(self, repo, message):
        workflow.git(repo, "add", ".")
        workflow.git(repo, "commit", "-m", message, "--quiet")
        return workflow.resolve(repo, "HEAD")

    def rebase(self):
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(io.StringIO()):
            workflow.rebase(self.args)
        self.assertEqual(workflow.git(self.repo, "for-each-ref", "refs/wsc-rebase-upstream/"), "")
        return output.getvalue()

    def publish_new(self):
        workflow.git(self.upstream, "fetch", str(self.repo), "+refs/heads/upstream-next:refs/heads/main")

    def test_preview_fetches_without_changing_refs_or_working_files(self):
        self.args.dry_run = True
        refs = workflow.git(self.repo, "show-ref")
        output = self.rebase()
        self.assertIn("PREVIEW ONLY", output)
        self.assertEqual(workflow.git(self.repo, "show-ref"), refs)
        self.assertEqual(workflow.resolve(self.repo, "HEAD"), self.tip)
        self.assertEqual(workflow.git(self.repo, "status", "--porcelain"), "")

    def test_fetch_configuration_cannot_prune_local_tags_or_branches(self):
        workflow.git(self.repo, "tag", "fork-release", self.tip)
        workflow.git(self.repo, "update-ref", "refs/remotes/upstream/local-only", self.tip)
        workflow.git(self.repo, "config", "fetch.prune", "true")
        workflow.git(self.repo, "config", "fetch.pruneTags", "true")
        refs = workflow.git(self.repo, "show-ref")
        self.args.dry_run = True
        self.rebase()
        self.assertEqual(workflow.git(self.repo, "show-ref"), refs)

    def test_success_rebases_in_place_and_preserves_original_branch(self):
        output = self.rebase()
        self.assertIn("Rebase completed", output)
        self.assertEqual(workflow.resolve(self.repo, "wsc"), self.tip)
        self.assertEqual(workflow.git(self.repo, "branch", "--show-current"), "candidate")
        self.assertEqual((self.repo / "wsc.txt").read_text(), "feature\n")
        self.assertEqual((self.repo / "upstream.txt").read_text(), "new upstream\n")
        self.assertEqual(len(workflow.linear_tail(self.repo, self.new, "HEAD")), 1)
        self.assertEqual(workflow.git(self.repo, "config", "branch.candidate.wscRebaseBase"), self.new)
        workflow.require_clean(self.repo)

    def conflicting_tip(self):
        self.write(self.repo, "shared.txt", "WSC change\n")
        self.args.tip = self.commit(self.repo, "WSC conflicting edit")
        workflow.git(self.repo, "checkout", "upstream-next")
        self.write(self.repo, "shared.txt", "Upstream change\n")
        self.args.new_base = self.commit(self.repo, "Upstream conflicting edit")
        self.publish_new()
        workflow.git(self.repo, "checkout", "wsc")

    def test_conflict_can_be_resolved_with_normal_git_continue(self):
        self.conflicting_tip()
        with self.assertRaises(workflow.WorkflowError):
            self.rebase()
        self.assertIn("UU shared.txt", workflow.git(self.repo, "status", "--porcelain"))
        self.assertEqual(workflow.resolve(self.repo, "wsc"), self.args.tip)
        self.write(self.repo, "shared.txt", "Reviewed combined change\n")
        workflow.git(self.repo, "add", "shared.txt")
        workflow.git(self.repo, "-c", "core.editor=true", "rebase", "--continue")
        self.assertEqual(len(workflow.linear_tail(self.repo, self.args.new_base, "HEAD")), 2)
        self.assertEqual(workflow.git(self.repo, "branch", "--show-current"), "candidate")
        workflow.require_clean(self.repo)

    def test_abort_returns_update_branch_to_original_fork_tip(self):
        self.conflicting_tip()
        with self.assertRaises(workflow.WorkflowError):
            self.rebase()
        workflow.git(self.repo, "rebase", "--abort")
        self.assertEqual(workflow.resolve(self.repo, "HEAD"), self.args.tip)
        self.assertEqual(workflow.resolve(self.repo, "wsc"), self.args.tip)
        self.assertEqual(workflow.git(self.repo, "branch", "--show-current"), "candidate")
        workflow.require_clean(self.repo)

    def test_empty_patch_stops_and_can_be_skipped_explicitly(self):
        workflow.git(self.repo, "checkout", "upstream-next")
        self.write(self.repo, "wsc.txt", "feature\n")
        self.args.new_base = self.commit(self.repo, "Upstream now has feature")
        self.publish_new()
        workflow.git(self.repo, "checkout", "wsc")
        with self.assertRaises(workflow.WorkflowError):
            self.rebase()
        with self.assertRaises(workflow.WorkflowError):
            workflow.require_clean(self.repo)
        workflow.git(self.repo, "rebase", "--skip")
        self.assertEqual(workflow.resolve(self.repo, "HEAD"), self.args.new_base)
        self.assertEqual(workflow.resolve(self.repo, "wsc"), self.tip)

    def test_dirty_and_untracked_files_are_preserved_without_fetch(self):
        for filename in ("wsc.txt", "personal.txt"):
            with self.subTest(filename=filename):
                self.write(self.repo, filename, "Do not remove\n")
                with patch.object(workflow, "upstream_snapshot") as fetch:
                    with self.assertRaisesRegex(workflow.WorkflowError, "clean"):
                        self.rebase()
                    fetch.assert_not_called()
                self.assertEqual((self.repo / filename).read_text(), "Do not remove\n")

    def test_pending_operation_rejected_before_fetch(self):
        self.conflicting_tip()
        with self.assertRaises(workflow.WorkflowError):
            self.rebase()
        with patch.object(workflow, "upstream_snapshot") as fetch:
            with self.assertRaisesRegex(workflow.WorkflowError, "existing Git operation"):
                self.rebase()
            fetch.assert_not_called()

    def test_merge_range_rejected(self):
        workflow.git(self.repo, "merge", "--no-ff", "upstream-next", "-m", "Merge upstream")
        self.args.tip = "HEAD"
        with self.assertRaisesRegex(workflow.WorkflowError, "linear tail"):
            self.rebase()
        self.assertEqual(workflow.git(self.repo, "branch", "--list", "candidate"), "")

    def test_upstream_tip_has_no_fork_patches(self):
        self.args.tip = self.old
        with self.assertRaisesRegex(workflow.WorkflowError, "no fork patches"):
            self.rebase()

    def test_identical_upstream_bases_rejected(self):
        self.args.new_base = self.old
        with self.assertRaisesRegex(workflow.WorkflowError, "already based"):
            self.rebase()

    def test_existing_explicit_branch_rejected(self):
        self.args.branch = "wsc"
        with self.assertRaisesRegex(workflow.WorkflowError, "already exists"):
            self.rebase()
        self.assertEqual(workflow.resolve(self.repo, "HEAD"), self.tip)

    def test_generated_branch_avoids_existing_name(self):
        self.args.branch = None
        stem = f"flutter-update-{self.new[:12]}"
        workflow.git(self.repo, "branch", stem)
        self.rebase()
        self.assertEqual(workflow.git(self.repo, "branch", "--show-current"), stem + "-2")
        self.assertEqual(workflow.resolve(self.repo, stem), self.tip)

    def test_annotated_tags_and_two_input_cli(self):
        workflow.git(self.repo, "tag", "-a", "wsc-3.44.4-r1", "-m", "Fork release", self.tip)
        workflow.git(self.repo, "tag", "-a", "3.44.9", "-m", "Upstream release", self.new)
        workflow.git(self.upstream, "fetch", "--no-tags", str(self.repo), "refs/tags/3.44.9:refs/tags/3.44.9")
        # Conflicting local tag must neither override the official target nor move.
        workflow.git(self.repo, "tag", "-f", "3.44.9", self.tip)
        with redirect_stdout(io.StringIO()):
            workflow.main(["rebase", "--repo", str(self.repo),
                           "--tip", "wsc-3.44.4-r1", "--new-base", "3.44.9"])
        self.assertEqual(workflow.git(self.repo, "branch", "--show-current"), "flutter-update-3.44.9")
        self.assertEqual(len(workflow.linear_tail(self.repo, self.new, "HEAD")), 1)
        self.assertEqual(workflow.resolve(self.repo, "3.44.9"), self.tip)
        self.assertEqual(workflow.resolve(self.repo, "wsc-3.44.4-r1"), self.tip)

    def test_upstream_branch_target_uses_fetched_not_stale_history(self):
        workflow.git(self.repo, "update-ref", "refs/remotes/upstream/main", self.old)
        self.args.new_base = "upstream/main"
        self.args.tip = "wsc"
        self.rebase()
        self.assertEqual(len(workflow.linear_tail(self.repo, self.new, "HEAD")), 1)
        self.assertEqual(workflow.resolve(self.repo, "refs/remotes/upstream/main"), self.old)

    def test_cross_channel_detection_uses_all_upstream_history(self):
        workflow.git(self.repo, "checkout", "upstream-next")
        self.write(self.repo, "release.txt", "Official release fix\n")
        release_base = self.commit(self.repo, "Official release fix")
        workflow.git(self.upstream, "fetch", str(self.repo), "refs/heads/upstream-next:refs/heads/stable")
        workflow.git(self.repo, "checkout", "-b", "fork-on-release")
        self.write(self.repo, "wsc.txt", "feature\n")
        self.args.tip = self.commit(self.repo, "Fork patch")
        # The target is on the other line: its common ancestor is older than the base.
        self.args.new_base = "main"
        output = self.rebase()
        self.assertIn(f"Detected old base: {release_base}", output)
        self.assertEqual(len(workflow.linear_tail(self.repo, self.new, "HEAD")), 1)
        self.assertFalse((self.repo / "release.txt").exists())

    def test_untagged_base_detected_from_official_tag_history(self):
        workflow.git(self.upstream, "update-ref", "refs/tags/official-release", self.new)
        for ref in workflow.git(self.upstream, "for-each-ref", "--format=%(refname)", "refs/heads/").splitlines():
            workflow.git(self.upstream, "update-ref", "-d", ref)
        self.rebase()
        self.assertEqual(len(workflow.linear_tail(self.repo, self.new, "HEAD")), 1)

    def test_local_fork_tag_and_stale_remote_ref_are_not_upstream_evidence(self):
        workflow.git(self.repo, "tag", "made-up-upstream-tag", self.tip)
        workflow.git(self.repo, "update-ref", "refs/remotes/upstream/deleted", self.tip)
        self.rebase()
        self.assertEqual(len(workflow.linear_tail(self.repo, self.new, "HEAD")), 1)

    def test_fork_commit_rejected_as_new_base(self):
        self.args.new_base = self.tip
        with self.assertRaisesRegex(workflow.WorkflowError, "not in the fetched upstream history"):
            self.rebase()
        self.assertEqual(workflow.resolve(self.repo, "HEAD"), self.tip)

    def test_ambiguous_upstream_tag_and_branch_rejected(self):
        workflow.git(self.upstream, "update-ref", "refs/tags/main", self.old)
        self.args.new_base = "main"
        with self.assertRaisesRegex(workflow.WorkflowError, "both a tag and branch"):
            self.rebase()
        self.args.new_base = "refs/heads/main"
        self.rebase()

    def test_missing_remote_or_target_leaves_worktree_unchanged(self):
        self.args.upstream = "missing"
        with self.assertRaisesRegex(workflow.WorkflowError, "Configure remote"):
            self.rebase()
        self.args.upstream = "upstream"
        self.args.new_base = "nonexistent"
        with self.assertRaisesRegex(workflow.WorkflowError, "No upstream branch or tag"):
            self.rebase()
        self.assertEqual(workflow.resolve(self.repo, "HEAD"), self.tip)
        self.assertEqual(workflow.git(self.repo, "for-each-ref", "refs/wsc-rebase-upstream/"), "")

    def test_fetch_failure_leaves_worktree_and_refs_unchanged(self):
        workflow.git(self.repo, "remote", "set-url", "upstream", str(self.directory / "missing"))
        refs = workflow.git(self.repo, "show-ref")
        with self.assertRaises(workflow.WorkflowError):
            self.rebase()
        self.assertEqual(workflow.git(self.repo, "show-ref"), refs)
        self.assertEqual(workflow.resolve(self.repo, "HEAD"), self.tip)

    def test_unrelated_history_rejected(self):
        other = self.directory / "unrelated"
        self.init_repo(other)
        self.write(other, "other.txt", "unrelated\n")
        self.args.tip = self.commit(other, "Unrelated root")
        workflow.git(self.repo, "fetch", str(other), "HEAD")
        with self.assertRaisesRegex(workflow.WorkflowError, "Cannot find the fork's base"):
            self.rebase()

    def test_ignored_outputs_and_nested_edits_are_not_cleaned(self):
        exclude = Path(workflow.git(self.repo, "rev-parse", "--git-path", "info/exclude"))
        if not exclude.is_absolute():
            exclude = self.repo / exclude
        with exclude.open("a") as stream:
            stream.write("\nbuild/\nnested/\n")
        self.write(self.repo, "build/output.bin", "Keep build\n")
        nested = self.repo / "nested"
        self.init_repo(nested)
        self.write(nested, "library.txt", "original\n")
        self.commit(nested, "Library")
        self.write(nested, "library.txt", "Uncommitted nested edit\n")
        self.rebase()
        self.assertEqual((self.repo / "build/output.bin").read_text(), "Keep build\n")
        self.assertEqual((nested / "library.txt").read_text(), "Uncommitted nested edit\n")

    def test_rebase_refuses_to_overwrite_an_ignored_file(self):
        exclude = self.repo / ".git/info/exclude"
        with exclude.open("a") as stream:
            stream.write("\nupstream.txt\n")
        self.write(self.repo, "upstream.txt", "Keep this local file\n")
        with self.assertRaisesRegex(workflow.WorkflowError, "ignored"):
            self.rebase()
        self.assertEqual((self.repo / "upstream.txt").read_text(), "Keep this local file\n")
        self.assertEqual(workflow.resolve(self.repo, "HEAD"), self.tip)

    def test_ignored_directory_collision_is_rejected(self):
        workflow.git(self.repo, "checkout", "upstream-next")
        self.write(self.repo, "build/new.txt", "Upstream tracked file\n")
        self.args.new_base = self.commit(self.repo, "Add tracked build input")
        self.publish_new()
        workflow.git(self.repo, "checkout", "wsc")
        with (self.repo / ".git/info/exclude").open("a") as stream:
            stream.write("\nbuild/\n")
        self.write(self.repo, "build/output.bin", "Keep output\n")
        with self.assertRaisesRegex(workflow.WorkflowError, "ignored"):
            self.rebase()
        self.assertEqual((self.repo / "build/output.bin").read_text(), "Keep output\n")

    def test_intermediate_patch_path_cannot_overwrite_ignored_file(self):
        self.write(self.repo, "temporary.txt", "Patch file\n")
        self.commit(self.repo, "Add temporary patch file")
        workflow.git(self.repo, "rm", "temporary.txt")
        self.args.tip = self.commit(self.repo, "Remove temporary patch file")
        with (self.repo / ".git/info/exclude").open("a") as stream:
            stream.write("\ntemporary.txt\n")
        self.write(self.repo, "temporary.txt", "Keep local file\n")
        with self.assertRaisesRegex(workflow.WorkflowError, "ignored"):
            self.rebase()
        self.assertEqual((self.repo / "temporary.txt").read_text(), "Keep local file\n")

    def test_rebase_in_existing_linked_worktree_leaves_other_worktree_alone(self):
        linked = self.directory / "linked"
        workflow.git(self.repo, "worktree", "add", "--detach", str(linked), self.tip)
        self.write(self.repo, "wsc.txt", "Unfinished original work\n")
        self.args.repo = linked
        self.rebase()
        self.assertEqual(workflow.git(linked, "branch", "--show-current"), "candidate")
        self.assertEqual(len(workflow.linear_tail(linked, self.new, "HEAD")), 1)
        self.assertEqual(workflow.resolve(self.repo, "HEAD"), self.tip)
        self.assertEqual((self.repo / "wsc.txt").read_text(), "Unfinished original work\n")

    def test_old_git_is_rejected_before_fetch_or_switch(self):
        real_git = workflow.git
        def older_git(repo, *args, **kwargs):
            if args == ("--version",):
                return "git version 2.44.0"
            return real_git(repo, *args, **kwargs)
        with patch.object(workflow, "git", side_effect=older_git):
            with patch.object(workflow, "upstream_snapshot") as fetch:
                with self.assertRaisesRegex(workflow.WorkflowError, "Git 2.45"):
                    self.rebase()
                fetch.assert_not_called()

    def test_update_refs_configuration_does_not_move_original_branches(self):
        workflow.git(self.repo, "config", "rebase.updateRefs", "true")
        workflow.git(self.repo, "config", "rebase.autoSquash", "true")
        workflow.git(self.repo, "config", "rebase.backend", "apply")
        workflow.git(self.repo, "branch", "another-fork-tip", self.tip)
        self.rebase()
        self.assertEqual(workflow.resolve(self.repo, "wsc"), self.tip)
        self.assertEqual(workflow.resolve(self.repo, "another-fork-tip"), self.tip)

    def test_shallow_repository_rejected(self):
        shallow = self.directory / "shallow"
        workflow.git(self.repo, "clone", "--depth=1", self.repo.as_uri(), str(shallow))
        with self.assertRaisesRegex(workflow.WorkflowError, "shallow"):
            workflow.require_clean(shallow)

    def test_pin_check_uses_existing_identity_script_and_requires_tracking(self):
        self.write(self.repo, "bin/internal/engine.version", self.tip + "\n")
        with patch.object(workflow, "expected_engine", return_value=self.tip):
            with self.assertRaises(workflow.WorkflowError):
                workflow.check_pin(self.repo)
            self.commit(self.repo, "Pin engine")
            with redirect_stdout(io.StringIO()):
                workflow.check_pin(self.repo)
            self.write(self.repo, "bin/internal/engine.version", self.old + "\n")
            with self.assertRaisesRegex(workflow.WorkflowError, "expected"):
                workflow.check_pin(self.repo)

    def dependency_fixture(self):
        dependencies = {}
        revisions = {}
        patch_root = "engine/src/flutter/tools/wsc_font_rendering_patches"
        with (self.repo / ".git/info/exclude").open("a") as stream:
            stream.write("\nengine/src/flutter/third_party/\n")
        for name in ("skia", "freetype"):
            dependency = self.repo / workflow.dependency_patches.DEPENDENCY_PATHS[name]
            self.init_repo(dependency)
            self.write(dependency, "sample.txt", "base\n")
            revisions[name] = self.commit(dependency, "Dependency base")
            self.write(dependency, "sample.txt", "patched\n")
            data = workflow.git(dependency, "diff") + "\n"
            self.write(self.repo, f"{patch_root}/{name}.patch", data)
            # A dirty nested file must be ignored by the applicability check.
            self.write(dependency, "sample.txt", "unrelated local edits\n")
            dependencies[name] = dependency
        self.write(self.repo, f"{patch_root}/apply_patches.py", f"""
EXPECTED_SKIA_REVISION = {revisions['skia']!r}
EXPECTED_FREETYPE_REVISION = {revisions['freetype']!r}
EXPECTED_REVISIONS = {{'skia': EXPECTED_SKIA_REVISION, 'freetype': EXPECTED_FREETYPE_REVISION}}
PATCH_GROUP_ORDER = ('test',)
def selected_patch_files(directory, groups):
    return [(name, directory / (name + '.patch')) for name in ('skia', 'freetype')]
""")
        values = {workflow.dependency_patches.DEPENDENCY_PATHS[name]:
                  dep.as_posix() + '@' + revisions[name] for name, dep in dependencies.items()}
        self.write(self.repo, "DEPS", f"vars = {{}}\ndeps = {values!r}\n")
        return dependencies

    def test_patch_check_uses_pristine_objects_and_does_not_touch_dependencies(self):
        dependencies = self.dependency_fixture()
        before = {}
        for name, dependency in dependencies.items():
            before[name] = (
                (dependency / "sample.txt").stat().st_mtime_ns,
                (dependency / ".git/index").read_bytes(),
                sorted(str(p.relative_to(dependency)) for p in (dependency / ".git/objects").rglob("*")),
            )
        with redirect_stdout(io.StringIO()):
            workflow.check_dependency_patches(self.repo, dependencies["skia"], dependencies["freetype"])
        for name, dependency in dependencies.items():
            self.assertEqual((dependency / "sample.txt").read_text(), "unrelated local edits\n")
            self.assertEqual(before[name], (
                (dependency / "sample.txt").stat().st_mtime_ns,
                (dependency / ".git/index").read_bytes(),
                sorted(str(p.relative_to(dependency)) for p in (dependency / ".git/objects").rglob("*")),
            ))

    def test_patch_check_rejects_broken_patch(self):
        dependencies = self.dependency_fixture()
        path = self.repo / "engine/src/flutter/tools/wsc_font_rendering_patches/skia.patch"
        path.write_text(path.read_text().replace("-base", "-not-the-base"))
        with self.assertRaises(workflow.WorkflowError):
            workflow.check_dependency_patches(self.repo, dependencies["skia"], dependencies["freetype"])

    def test_patch_check_rejects_wrong_dependency_head(self):
        dependencies = self.dependency_fixture()
        self.commit(dependencies["skia"], "Different dependency")
        with self.assertRaisesRegex(workflow.WorkflowError, "differs from DEPS"):
            workflow.check_dependency_patches(self.repo, dependencies["skia"], dependencies["freetype"])

    def test_patch_check_preserves_inventory_order_and_accepts_crlf_patch_files(self):
        dependencies = self.dependency_fixture()
        patch_root = self.repo / "engine/src/flutter/tools/wsc_font_rendering_patches"
        second = (
            "diff --git a/sample.txt b/sample.txt\n"
            "--- a/sample.txt\n+++ b/sample.txt\n@@ -1 +1 @@\n-patched\n+second patch\n"
        )
        (patch_root / "second.patch").write_bytes(second.replace("\n", "\r\n").encode())
        inventory = patch_root / "apply_patches.py"
        inventory.write_text(inventory.read_text() +
                             "\noriginal_inventory = selected_patch_files\n"
                             "def selected_patch_files(directory, groups):\n"
                             "    return original_inventory(directory, groups) + [('skia', directory / 'second.patch')]\n")
        with redirect_stdout(io.StringIO()):
            workflow.check_dependency_patches(self.repo, dependencies["skia"], dependencies["freetype"])

    def test_patch_check_does_not_silently_skip_new_dependency_types(self):
        dependencies = self.dependency_fixture()
        inventory = self.repo / "engine/src/flutter/tools/wsc_font_rendering_patches/apply_patches.py"
        inventory.write_text(inventory.read_text().replace("('skia', 'freetype')", "('skia', 'freetype', 'new_dependency')"))
        with self.assertRaisesRegex(workflow.WorkflowError, "inventory changed"):
            workflow.check_dependency_patches(self.repo, dependencies["skia"], dependencies["freetype"])

    def test_dependency_paths_are_inferred_and_overrides_are_independent(self):
        dependencies = self.dependency_fixture()
        with redirect_stdout(io.StringIO()):
            workflow.check_dependency_patches(self.repo)
            workflow.check_dependency_patches(self.repo, dependencies['skia'])
        with self.assertRaisesRegex(workflow.WorkflowError, "Missing skia checkout"):
            workflow.check_dependency_patches(self.repo, self.directory / "missing")

    def test_repository_environment_override_rejected(self):
        with patch.dict(os.environ, {"GIT_INDEX_FILE": "unrelated-index"}):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as result:
                workflow.main(["verify", "--new-base", self.old, "--repo", str(self.repo)])
        self.assertEqual(result.exception.code, 1)
        self.assertEqual(workflow.git(self.repo, "status", "--porcelain"), "")

    def verification_fixture(self):
        actual_repo = Path(__file__).resolve().parents[2]
        for name in (
            "dev/bots/engine_identity.py",
            "dev/bots/validate_sdk_identity.py",
        ):
            self.write(self.repo, name, (actual_repo / name).read_text(encoding="utf-8"))
        self.write(self.repo, "bin/internal/release-candidate-branch.version", "fixture\n")
        for filename in ("test_engine_identity.py", "test_collect_engine_artifacts.py", "test_verify_maven_artifacts.py", "test_validate_sdk_identity.py", "test_artifact_publishing.py", "test_wsc_rebase.py", "test_wsc_dependency_patches.py", "test_sync_engine_deps.py"):
            # The verify orchestration is under test, not a recursive invocation
            # of this suite. The real focused suites are run separately.
            self.write(self.repo, f"dev/bots/{filename}",
                       "import unittest\nclass Smoke(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n")
        self.dependency_fixture()
        self.write(self.repo, "engine/fixture", "fixture engine\n")
        self.commit(self.repo, "Candidate scripts")
        self.write(self.repo, "bin/internal/engine.version", workflow.expected_engine(self.repo) + "\n")
        self.commit(self.repo, "Candidate pin")
        return argparse.Namespace(repo=self.repo, new_base=self.old, skia_dir=None, freetype_dir=None)

    def test_verify_runs_checks_and_reports_rendering_as_pending(self):
        args = self.verification_fixture()
        output = io.StringIO()
        with redirect_stdout(output):
            workflow.verify(args)
        self.assertIn("SOURCE CHECKS PASSED, NOT RELEASE APPROVAL", output.getvalue())
        self.assertIn("PENDING rendering equivalence", output.getvalue())
        self.assertIn("PASS skia", output.getvalue())
        workflow.require_clean(self.repo)

    def test_verify_uses_base_saved_for_current_branch(self):
        args = self.verification_fixture()
        workflow.git(self.repo, "config", "branch.wsc.wscRebaseBase", args.new_base)
        args.new_base = None
        with redirect_stdout(io.StringIO()):
            workflow.verify(args)

    def test_verify_without_saved_base_explains_explicit_option(self):
        args = argparse.Namespace(repo=self.repo, new_base=None, skia_dir=None, freetype_dir=None)
        with self.assertRaisesRegex(workflow.WorkflowError, "verify --new-base"):
            workflow.verify(args)

    def test_verify_fails_on_failing_test(self):
        args = self.verification_fixture()
        path = self.repo / "dev/bots/test_validate_sdk_identity.py"
        path.write_text(path.read_text().replace("assertTrue(True)", "assertTrue(False)"), newline="\n")
        self.commit(self.repo, "Broken focused test")
        with redirect_stdout(io.StringIO()), self.assertRaisesRegex(workflow.WorkflowError, "FAILED"):
            workflow.verify(args)

    def test_verify_fails_on_missing_test_file(self):
        args = self.verification_fixture()
        workflow.git(self.repo, "rm", "dev/bots/test_wsc_rebase.py")
        self.commit(self.repo, "Missing focused test")
        with redirect_stdout(io.StringIO()), self.assertRaisesRegex(workflow.WorkflowError, "Missing expected test"):
            workflow.verify(args)


if __name__ == "__main__":
    unittest.main()
