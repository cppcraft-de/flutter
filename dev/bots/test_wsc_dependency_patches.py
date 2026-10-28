"""Dependency workflow integration tests with local Git remotes and mocked gclient."""

from contextlib import redirect_stdout
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import wsc_dependency_patches as workflow
import wsc_rebase


class DependencyWorkflowTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dependency-workflow-test-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name).resolve()
        self.repo = self.directory / "flutter"
        self.init(self.repo)
        self.sources, self.revisions = {}, {}
        for name in workflow.DEPENDENCY_PATHS:
            source = self.directory / ("remote-" + name)
            self.init(source)
            self.write(source / "sample.txt", "base\n")
            self.revisions[name] = self.commit(source, "Library base")
            self.sources[name] = source
            self.write(source / "sample.txt", "patched\n")
            data = workflow.git(source, "diff").stdout
            self.write(self.repo / workflow.PATCH_ROOT / (name + ".patch"), data)
            workflow.output(source, "restore", "sample.txt")
        self.write_deps()
        self.write_inventory()
        self.write(self.repo / "engine/scripts/standard.gclient", 'solutions = []\n    # "custom_vars": {\n    #   "download_emsdk": True,\n    # },\n')
        self.write(self.repo / ".gitignore", 'engine/src/flutter/third_party/\nengine/src/flutter/prebuilts/\n.gclient\n')
        self.original = self.commit(self.repo, "Fork patches")
        self.runner_patch = patch.object(workflow.sync_engine_deps, "run_gclient", side_effect=self.fake_gclient)
        self.runner = self.runner_patch.start()
        self.addCleanup(self.runner_patch.stop)
        host_patch = patch.object(workflow.sync_engine_deps, "host_name", return_value="windows-x64")
        host_patch.start()
        self.addCleanup(host_patch.stop)
        executable_patch = patch.object(workflow.shutil, "which", return_value="gclient")
        executable_patch.start()
        self.addCleanup(executable_patch.stop)

    def init(self, directory):
        directory.mkdir(parents=True)
        workflow.output(directory, "init", "-b", "main", "--quiet")
        for key, value in {"user.name": "Fixture", "user.email": "fixture@localhost", "commit.gpgSign": "false", "core.autocrlf": "false", "core.hooksPath": str(self.directory / "no-hooks")}.items():
            workflow.output(directory, "config", key, value)

    def write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode())

    def commit(self, repo, message):
        workflow.output(repo, "add", ".")
        workflow.output(repo, "commit", "-qm", message)
        return workflow.output(repo, "rev-parse", "HEAD")

    def write_deps(self):
        variables = {name + "_url": self.sources[name].as_posix() for name in self.sources}
        variables.update({name + "_revision": revision for name, revision in self.revisions.items()})
        values = ",\n".join(repr(relative) + f": Var('{name}_url') + '@' + Var('{name}_revision')" for name, relative in workflow.DEPENDENCY_PATHS.items())
        self.write(self.repo / "DEPS", f"vars = {variables!r}\ndeps = {{\n{values}\n}}\n")

    def write_inventory(self):
        self.write(self.repo / workflow.PATCH_ROOT / "apply_patches.py", f"""
EXPECTED_SKIA_REVISION = {self.revisions['skia']!r}
EXPECTED_FREETYPE_REVISION = {self.revisions['freetype']!r}
EXPECTED_REVISIONS = {{'skia': EXPECTED_SKIA_REVISION, 'freetype': EXPECTED_FREETYPE_REVISION}}
PATCH_GROUP_ORDER = ('all',)
def selected_patch_files(directory, groups):
    return [(name, directory / (name + '.patch')) for name in ('skia', 'freetype')]
""")

    def fake_gclient(self, repo, web):
        dependencies = workflow.read_dependencies(repo)
        _, patches = workflow.load_inventory(repo / workflow.PATCH_ROOT)
        for name, dep in dependencies.items():
            if not (dep.path / ".git").exists():
                dep.path.parent.mkdir(parents=True, exist_ok=True)
                workflow.output(repo, "clone", "-c", "core.autocrlf=false", "--quiet", dep.url, dep.path)
            self.assertEqual(workflow.output(dep.path, "status", "--porcelain"), "", "Prior patches must be safely undone before gclient")
            workflow.output(dep.path, "fetch", "--no-tags", dep.url, dep.revision)
            workflow.output(dep.path, "checkout", "--detach", dep.revision)
            for owner, file in patches:
                if owner == name:
                    workflow.output(dep.path, "apply", file)
        self.write(repo / "engine/src/flutter/prebuilts/windows-x64/dart-sdk/bin/dart.exe", "fixture")

    def prepare(self, **kwargs):
        with redirect_stdout(io.StringIO()):
            workflow.prepare_dependencies(self.repo, **kwargs)

    def roll(self):
        for name, source in self.sources.items():
            self.write(source / "version.txt", "next\n")
            self.revisions[name] = self.commit(source, "Next library revision")
        self.write_deps()

    def test_reads_paths_urls_and_revisions_from_deps(self):
        dependencies = workflow.read_dependencies(self.repo)
        for name, dep in dependencies.items():
            self.assertEqual(dep.path, self.repo / workflow.DEPENDENCY_PATHS[name])
            self.assertEqual(dep.url, self.sources[name].as_posix())
            self.assertEqual(dep.revision, self.revisions[name])

    def test_unsupported_deps_is_not_executed_or_guessed(self):
        with (self.repo / "DEPS").open("a") as stream:
            stream.write("deps.update({})\n")
        with self.assertRaisesRegex(workflow.DependencyError, "Unsupported DEPS statement"):
            self.prepare()
        self.runner.assert_not_called()

    def test_fresh_setup_fetches_checks_syncs_and_verifies_without_paths(self):
        with redirect_stdout(io.StringIO()):
            wsc_rebase.main(["dependencies", "--repo", str(self.repo), "--web"])
        self.runner.assert_called_once_with(self.repo, True)
        with redirect_stdout(io.StringIO()):
            workflow.check_patches(self.repo)
        for relative in workflow.DEPENDENCY_PATHS.values():
            self.assertEqual((self.repo / relative / "sample.txt").read_text(), "patched\n")

    def test_roll_updates_expected_revisions_after_patch_checks(self):
        self.prepare()
        self.roll()
        self.prepare()
        module, _ = workflow.load_inventory(self.repo / workflow.PATCH_ROOT)
        self.assertEqual(module.EXPECTED_REVISIONS, self.revisions)
        for name, dep in workflow.read_dependencies(self.repo).items():
            self.assertEqual(workflow.output(dep.path, "rev-parse", "HEAD"), self.revisions[name])

    def test_verify_rejects_old_checkouts_and_old_expected_revisions(self):
        self.prepare()
        self.roll()
        with self.assertRaisesRegex(workflow.DependencyError, "differs from DEPS"):
            workflow.check_patches(self.repo)
        self.write_inventory()
        with self.assertRaisesRegex(workflow.DependencyError, "HEAD .* differs from DEPS"):
            workflow.check_patches(self.repo)

    def test_verify_missing_dependency_is_an_error_not_a_skipped_check(self):
        with self.assertRaisesRegex(workflow.DependencyError, "Missing skia checkout"):
            workflow.check_patches(self.repo)

    def test_broken_patch_keeps_pins_and_leaves_self_contained_repair_checkout(self):
        self.roll()
        patch_file = self.repo / workflow.PATCH_ROOT / "freetype.patch"
        patch_file.write_bytes(patch_file.read_bytes().replace(b"-base", b"-different"))
        helper = self.repo / workflow.PATCH_ROOT / "apply_patches.py"
        before = helper.read_bytes()
        with self.assertRaisesRegex(workflow.DependencyError, "Repair checkout:"):
            self.prepare()
        self.runner.assert_not_called()
        self.assertEqual(helper.read_bytes(), before)
        folders = list(self.directory.glob("flutter-freetype-patch-*"))
        self.assertEqual(len(folders), 1)
        self.assertTrue((folders[0] / "sample.txt.rej").is_file())
        workflow.output(folders[0], "fsck", "--full")
        self.assertFalse((folders[0] / ".git/objects/info/alternates").exists())

    def test_previous_patch_version_is_undone_when_new_patch_changed(self):
        self.prepare()
        workflow.output(self.repo, "config", "branch.main.wscRebaseTip", self.original)
        file = self.repo / workflow.PATCH_ROOT / "skia.patch"
        file.write_bytes(file.read_bytes().replace(b"+patched", b"+new patched"))
        self.prepare()
        skia = self.repo / workflow.DEPENDENCY_PATHS['skia']
        self.assertEqual((skia / "sample.txt").read_text(), "new patched\n")

    def test_user_edit_to_patch_owned_file_blocks_all_resets_and_sync(self):
        self.prepare()
        self.runner.reset_mock()
        freetype = self.repo / workflow.DEPENDENCY_PATHS['freetype']
        self.write(freetype / "sample.txt", "User edit\n")
        skia = self.repo / workflow.DEPENDENCY_PATHS['skia']
        index = (skia / ".git/index").read_bytes()
        self.roll()
        helper = self.repo / workflow.PATCH_ROOT / "apply_patches.py"
        before = helper.read_bytes()
        with self.assertRaisesRegex(workflow.DependencyError, "do not match"):
            self.prepare()
        self.runner.assert_not_called()
        self.assertEqual(helper.read_bytes(), before)
        self.assertEqual((skia / "sample.txt").read_text(), "patched\n")
        self.assertEqual((skia / ".git/index").read_bytes(), index)
        self.assertEqual((freetype / "sample.txt").read_text(), "User edit\n")

    def test_untracked_and_staged_dependency_edits_are_preserved(self):
        self.prepare()
        skia = self.repo / workflow.DEPENDENCY_PATHS['skia']
        self.write(skia / "personal.txt", "Keep me\n")
        with self.assertRaisesRegex(workflow.DependencyError, "do not match"):
            self.prepare()
        self.assertEqual((skia / "personal.txt").read_text(), "Keep me\n")
        workflow.output(skia, "add", "personal.txt")
        with self.assertRaisesRegex(workflow.DependencyError, "staged edits"):
            self.prepare()
        self.assertIn("personal.txt", workflow.output(skia, "diff", "--cached", "--name-only"))

    def test_sync_success_without_applied_patches_is_rejected(self):
        real = self.fake_gclient
        def no_patches(repo, web):
            real(repo, web)
            for dep in workflow.read_dependencies(repo).values():
                workflow.output(dep.path, "restore", "sample.txt")
        self.runner.side_effect = no_patches
        with self.assertRaisesRegex(workflow.DependencyError, "does not contain exactly"):
            self.prepare()

    def test_sync_failure_does_not_report_readiness(self):
        self.runner.side_effect = subprocess.CalledProcessError(1, "gclient")
        with self.assertRaises(subprocess.CalledProcessError):
            self.prepare()
        self.assertFalse((self.repo / ".git/wsc-deps-sync.sha256").exists())

    def test_repeat_setup_and_web_configuration_are_preserved(self):
        self.prepare(web=True)
        self.prepare()
        self.assertEqual(self.runner.call_count, 2)
        self.runner.assert_called_with(self.repo, True)

    def test_custom_gclient_is_not_overwritten(self):
        self.write(self.repo / ".gclient", "my custom checkout\n")
        with self.assertRaisesRegex(workflow.DependencyError, "custom .gclient"):
            self.prepare()
        self.runner.assert_not_called()
        self.assertEqual((self.repo / ".gclient").read_text(), "my custom checkout\n")

    def test_missing_gclient_fails_before_fetching_or_editing(self):
        with patch.object(workflow.shutil, "which", return_value=None):
            with patch.object(workflow, "check_patches") as check:
                with self.assertRaisesRegex(workflow.DependencyError, "gclient was not found"):
                    self.prepare()
                check.assert_not_called()
        self.runner.assert_not_called()

    def test_partial_patch_setup_can_be_retried_and_preserves_ignored_outputs(self):
        header = self.repo / workflow.PATCH_ROOT / "header.patch"
        self.write(header, 'diff --git a/header.h b/header.h\nnew file mode 100644\n--- /dev/null\n+++ b/header.h\n@@ -0,0 +1 @@\n+generated header\n')
        inventory = self.repo / workflow.PATCH_ROOT / "apply_patches.py"
        with inventory.open("a") as stream:
            stream.write("\nprevious = selected_patch_files\ndef selected_patch_files(directory, groups):\n    return previous(directory, groups) + [('skia', directory / 'header.patch')]\n")
        self.prepare()
        skia = self.repo / workflow.DEPENDENCY_PATHS['skia']
        # Emulate sync interrupted after the earlier patch, before this addition.
        (skia / 'header.h').unlink()
        with (skia / '.git/info/exclude').open('a') as stream:
            stream.write('\nout/\n')
        self.write(skia / 'out/keep.bin', 'keep build output')
        self.prepare()
        self.assertEqual((skia / 'header.h').read_text(), 'generated header\n')
        self.assertEqual((skia / 'out/keep.bin').read_text(), 'keep build output')

    def test_repair_checkout_keeps_earlier_patches_out_of_saved_diff(self):
        broken = self.repo / workflow.PATCH_ROOT / "broken.patch"
        self.write(broken, 'diff --git a/sample.txt b/sample.txt\n--- a/sample.txt\n+++ b/sample.txt\n@@ -1 +1 @@\n-wrong content\n+final\n')
        inventory = self.repo / workflow.PATCH_ROOT / "apply_patches.py"
        with inventory.open('a') as stream:
            stream.write("\nprevious = selected_patch_files\ndef selected_patch_files(directory, groups):\n    return previous(directory, groups) + [('skia', directory / 'broken.patch')]\n")
        with self.assertRaisesRegex(workflow.DependencyError, 'Repair checkout:'):
            self.prepare()
        repair, = self.directory.glob('flutter-skia-patch-*')
        self.assertEqual(workflow.output(repair, 'show', 'HEAD:sample.txt'), 'patched')
        self.write(repair / 'sample.txt', 'final\n')
        workflow.output(repair, 'add', 'sample.txt')
        saved = workflow.output(repair, 'diff', '--cached')
        self.assertIn('-patched', saved)
        self.assertNotIn('-base', saved)
        workflow.output(repair, 'fsck', '--full')


if __name__ == '__main__':
    unittest.main()
