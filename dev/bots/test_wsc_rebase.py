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
        self.args = argparse.Namespace(
            repo=self.repo, old_base=self.old, tip=self.tip, new_base=self.new,
            branch="candidate", worktree=self.directory / "candidate", apply=False,
        )

    def init_repo(self, repo):
        repo.mkdir()
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

    def prepare(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            workflow.prepare(self.args)

    def test_preview_does_not_create_branch_or_directory(self):
        self.prepare()
        self.assertFalse(self.args.worktree.exists())
        self.assertEqual(workflow.git(self.repo, "branch", "--list", "candidate"), "")
        self.assertEqual(workflow.resolve(self.repo, "HEAD"), self.tip)

    def test_success_replays_only_tail_and_preserves_source(self):
        self.args.apply = True
        self.prepare()
        self.assertEqual(workflow.resolve(self.repo, "HEAD"), self.tip)
        self.assertEqual(workflow.git(self.repo, "status", "--porcelain"), "")
        candidate = self.args.worktree
        self.assertEqual((candidate / "wsc.txt").read_text(), "feature\n")
        self.assertEqual((candidate / "upstream.txt").read_text(), "new upstream\n")
        self.assertEqual(len(workflow.linear_tail(self.repo, self.new, "candidate")), 1)

    def conflicting_tip(self):
        self.write(self.repo, "shared.txt", "WSC change\n")
        self.args.tip = self.commit(self.repo, "WSC conflicting edit")
        workflow.git(self.repo, "checkout", "upstream-next")
        self.write(self.repo, "shared.txt", "Upstream change\n")
        self.args.new_base = self.commit(self.repo, "Upstream conflicting edit")
        workflow.git(self.repo, "checkout", "wsc")
        self.args.apply = True

    def test_conflict_can_be_resolved_with_normal_git_continue(self):
        self.conflicting_tip()
        with self.assertRaises(workflow.WorkflowError):
            self.prepare()
        candidate = self.args.worktree
        self.assertIn("UU shared.txt", workflow.git(candidate, "status", "--porcelain"))
        self.assertEqual(workflow.resolve(self.repo, "HEAD"), self.args.tip)
        self.write(candidate, "shared.txt", "Reviewed combined change\n")
        workflow.git(candidate, "add", "shared.txt")
        workflow.git(candidate, "-c", "core.editor=true", "cherry-pick", "--continue")
        self.assertEqual(len(workflow.linear_tail(candidate, self.args.new_base, "HEAD")), 2)
        workflow.require_clean(candidate)

    def test_abort_preserves_source_and_candidate_directory(self):
        self.conflicting_tip()
        with self.assertRaises(workflow.WorkflowError):
            self.prepare()
        workflow.git(self.args.worktree, "cherry-pick", "--abort")
        self.assertEqual(workflow.resolve(self.args.worktree, "HEAD"), self.args.new_base)
        self.assertEqual(workflow.resolve(self.repo, "HEAD"), self.args.tip)
        self.assertTrue(self.args.worktree.exists())

    def test_empty_replay_commit_is_not_silently_skipped(self):
        workflow.git(self.repo, "checkout", "upstream-next")
        self.write(self.repo, "wsc.txt", "feature\n")
        self.args.new_base = self.commit(self.repo, "Upstream now has feature")
        workflow.git(self.repo, "checkout", "wsc")
        self.args.apply = True
        with self.assertRaises(workflow.WorkflowError):
            self.prepare()
        with self.assertRaises(workflow.WorkflowError):
            workflow.require_clean(self.args.worktree)

    def test_dirty_and_untracked_files_are_preserved(self):
        for filename in ("wsc.txt", "personal.txt"):
            with self.subTest(filename=filename):
                self.write(self.repo, filename, "Do not remove\n")
                with self.assertRaisesRegex(workflow.WorkflowError, "clean"):
                    self.prepare()
                self.assertEqual((self.repo / filename).read_text(), "Do not remove\n")

    def test_merge_range_rejected(self):
        workflow.git(self.repo, "merge", "--no-ff", "upstream-next", "-m", "Merge upstream")
        self.args.tip = "HEAD"
        with self.assertRaisesRegex(workflow.WorkflowError, "linear tail"):
            self.prepare()

    def test_wrong_base_and_empty_tail_rejected(self):
        self.args.old_base = self.new
        with self.assertRaises(workflow.WorkflowError):
            self.prepare()
        self.args.old_base = self.tip
        with self.assertRaisesRegex(workflow.WorkflowError, "empty"):
            self.prepare()

    def test_identical_upstream_bases_rejected(self):
        self.args.new_base = self.old
        with self.assertRaisesRegex(workflow.WorkflowError, "identical"):
            self.prepare()

    def test_existing_branch_and_directory_rejected(self):
        self.args.branch = "wsc"
        with self.assertRaisesRegex(workflow.WorkflowError, "already exists"):
            self.prepare()
        self.args.branch = "candidate"
        self.args.worktree.mkdir()
        with self.assertRaisesRegex(workflow.WorkflowError, "must not exist"):
            self.prepare()

    def test_nested_destination_rejected(self):
        self.args.worktree = self.repo / "build" / "candidate"
        with self.assertRaisesRegex(workflow.WorkflowError, "outside"):
            self.prepare()

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
        for name in ("skia", "freetype"):
            dependency = self.directory / name
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
EXPECTED_REVISIONS = {revisions!r}
PATCH_GROUP_ORDER = ('test',)
def selected_patch_files(directory, groups):
    return [(name, directory / (name + '.patch')) for name in ('skia', 'freetype')]
""")
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
        with self.assertRaisesRegex(workflow.WorkflowError, "EXPECTED_REVISIONS"):
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

    def test_pair_of_dependency_arguments_required(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as result:
            workflow.main(["verify", "--new-base", self.new, "--skia-dir", str(self.repo)])
        self.assertEqual(result.exception.code, 2)

    def test_repository_environment_override_rejected(self):
        with patch.dict(os.environ, {"GIT_INDEX_FILE": "unrelated-index"}):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as result:
                workflow.main(["verify", "--new-base", self.old, "--repo", str(self.repo)])
        self.assertEqual(result.exception.code, 1)
        self.assertEqual(workflow.git(self.repo, "status", "--porcelain"), "")

    def verification_fixture(self):
        actual_repo = Path(__file__).resolve().parents[2]
        for name in (
            "bin/internal/last_engine_commit.ps1", "bin/internal/last_engine_commit.sh",
            "dev/bots/validate_sdk_identity.py",
        ):
            self.write(self.repo, name, (actual_repo / name).read_text(encoding="utf-8"))
        self.write(self.repo, "bin/internal/release-candidate-branch.version", "fixture\n")
        for filename in ("test_validate_sdk_identity.py", "test_artifact_publishing.py", "test_wsc_rebase.py"):
            # The verify orchestration is under test, not a recursive invocation
            # of this suite. The real focused suites are run separately.
            self.write(self.repo, f"dev/bots/{filename}",
                       "import unittest\nclass Smoke(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n")
        reference = self.commit(self.repo, "Candidate scripts")
        self.write(self.repo, "bin/internal/engine.version", reference + "\n")
        self.commit(self.repo, "Candidate pin")
        return argparse.Namespace(repo=self.repo, new_base=self.old, skia_dir=None, freetype_dir=None)

    def test_verify_runs_checks_and_reports_rendering_as_pending(self):
        args = self.verification_fixture()
        output = io.StringIO()
        with redirect_stdout(output):
            workflow.verify(args)
        self.assertIn("SOURCE CHECKS PASSED, NOT RELEASE APPROVAL", output.getvalue())
        self.assertIn("PENDING rendering equivalence", output.getvalue())
        self.assertIn("PENDING dependency patch applicability", output.getvalue())
        workflow.require_clean(self.repo)

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
