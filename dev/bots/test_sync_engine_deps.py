"""Offline policy tests; gclient is mocked, only disposable Git repos are used."""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import sync_engine_deps as deps

ORIGINAL_RUN_GCLIENT = deps.run_gclient


class DependencySyncTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="wsc-sync-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        deps.git(self.root, "init", "--quiet")
        self.marker = self.root / ".git/wsc-deps-sync.sha256"
        self.write("DEPS", "initial dependency pins\n")
        self.write("engine/scripts/standard.gclient", 'solutions = []\n    # "custom_vars": {\n    #   "download_emsdk": True,\n    # },\n')
        self.write("engine/src/flutter/tools/wsc_font_rendering_patches/test.patch", "patch v1\n")
        self.write("engine/src/flutter/tools/hook.py", "hook v1\n")
        self.write("engine/src/flutter/pubspec.yaml", "pubspec v1\n")
        self.write("dev/bots/sync_engine_deps.py", "policy v1\n")
        self.write("README.md", "docs\n")
        self.write("engine/src/flutter/lib/ui/text.dart", "rendering\n")
        deps.git(self.root, "add", ".")
        self.dart = self.root / "engine/src/flutter/prebuilts/windows-x64/dart-sdk/bin/dart.exe"
        runner_patch = patch.object(deps, "run_gclient", side_effect=self.successful_sync)
        self.runner = runner_patch.start()
        self.addCleanup(runner_patch.stop)
        host_patch = patch.object(deps, "host_name", return_value="windows-x64")
        host_patch.start()
        self.addCleanup(host_patch.stop)

    def write(self, relative, contents):
        destination = self.root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(contents, encoding="utf-8")

    def successful_sync(self, root, web):
        self.assertFalse(self.marker.exists(), "Old success marker must be invalidated before gclient")
        self.write(str(self.dart.relative_to(self.root)), "Dart sentinel\n")
        for name in ("skia", "freetype2"):
            (self.root / f"engine/src/flutter/third_party/{name}/.git").mkdir(parents=True, exist_ok=True)

    def sync(self, mode="auto", web=False):
        with redirect_stdout(io.StringIO()):
            deps.sync(self.root, mode, web)

    def test_first_auto_sync_then_unchanged_skip_preserves_outputs_and_mtimes(self):
        self.write("engine/src/out/keep.obj", "expensive output")
        self.sync()
        marker_time = self.marker.stat().st_mtime_ns
        config_time = (self.root / ".gclient").stat().st_mtime_ns
        self.sync()
        self.runner.assert_called_once()
        self.assertEqual(self.marker.stat().st_mtime_ns, marker_time)
        self.assertEqual((self.root / ".gclient").stat().st_mtime_ns, config_time)
        self.assertEqual((self.root / "engine/src/out/keep.obj").read_text(), "expensive output")

    def test_existing_workspace_without_marker_syncs_once(self):
        self.write(".gclient", deps.configuration(self.root, False))
        self.successful_sync(self.root, False)
        self.sync()
        self.runner.assert_called_once()

    def test_changed_inputs_trigger_sync(self):
        self.sync()
        for relative in (
            "DEPS", "engine/src/flutter/tools/wsc_font_rendering_patches/test.patch",
            "engine/src/flutter/tools/hook.py", "engine/src/flutter/pubspec.yaml",
            "engine/scripts/standard.gclient", "dev/bots/sync_engine_deps.py",
        ):
            with self.subTest(relative=relative):
                self.runner.reset_mock()
                with (self.root / relative).open("a") as output:
                    output.write("# changed\n")
                self.sync()
                self.runner.assert_called_once()

    def test_added_and_removed_patches_and_nested_deps_trigger_sync(self):
        self.sync()
        for relative in ("engine/src/flutter/tools/wsc_font_rendering_patches/new.patch", "engine/local/DEPS"):
            self.write(relative, "new input")
            deps.git(self.root, "add", relative)
            self.runner.reset_mock()
            self.sync()
            self.runner.assert_called_once()
            deps.git(self.root, "rm", "-f", relative)
            self.runner.reset_mock()
            self.sync()
            self.runner.assert_called_once()

    def test_ordinary_source_docs_and_timestamps_do_not_trigger_sync(self):
        self.sync()
        self.write("README.md", "new docs")
        self.write("engine/src/flutter/lib/ui/text.dart", "new rendering code")
        os.utime(self.root / "DEPS", None)
        self.sync()
        self.runner.assert_called_once()

    def test_unstaged_patch_addition_and_deletion_trigger_sync(self):
        self.sync()
        relative = "engine/src/flutter/tools/wsc_font_rendering_patches/new.patch"
        self.write(relative, "new patch")
        self.runner.reset_mock()
        self.sync()
        self.runner.assert_called_once()
        (self.root / relative).unlink()
        self.runner.reset_mock()
        self.sync()
        self.runner.assert_called_once()
        tracked = self.root / "engine/src/flutter/tools/wsc_font_rendering_patches/test.patch"
        tracked.unlink()
        self.runner.reset_mock()
        self.sync()
        self.runner.assert_called_once()

    def test_web_and_effective_config_changes_trigger_sync(self):
        self.sync()
        self.sync(web=True)
        self.assertIn('"download_emsdk": True', (self.root / ".gclient").read_text())
        self.assertEqual(self.runner.call_count, 2)
        self.write(".gclient", "stale manual configuration")
        self.sync(web=True)
        self.assertEqual(self.runner.call_count, 3)
        self.sync(web=True)
        self.assertEqual(self.runner.call_count, 3)

    def test_true_always_syncs_false_skips_changes_but_bootstraps(self):
        self.sync("false")  # Empty workspace still bootstraps.
        self.write("DEPS", "changed")
        self.sync("false")
        self.runner.assert_called_once()
        self.sync("auto")  # false did not mark changed inputs as synchronized.
        self.sync("true")
        self.sync("true")
        self.assertEqual(self.runner.call_count, 4)

    def test_missing_dart_or_nested_repo_triggers_sync(self):
        self.sync()
        self.dart.unlink()
        self.sync()
        (self.root / "engine/src/flutter/third_party/skia/.git").rmdir()
        self.sync()
        self.assertEqual(self.runner.call_count, 3)

    def test_failure_and_interruption_invalidate_stamp_even_if_inputs_revert(self):
        original = (self.root / "DEPS").read_text()
        for failure in (subprocess.CalledProcessError(1, "gclient"), KeyboardInterrupt()):
            self.sync()
            self.write("DEPS", "different inputs")
            self.runner.side_effect = failure
            with self.assertRaises(type(failure)):
                self.sync()
            self.assertFalse(self.marker.exists())
            self.write("DEPS", original)
            self.runner.side_effect = self.successful_sync
            self.runner.reset_mock()
            self.sync()
            self.runner.assert_called_once()

    def test_forced_failure_and_corrupt_stamp_retry(self):
        self.sync()
        self.runner.side_effect = subprocess.CalledProcessError(1, "gclient")
        with self.assertRaises(subprocess.CalledProcessError):
            self.sync("true")
        self.assertFalse(self.marker.exists())
        self.runner.side_effect = self.successful_sync
        self.sync()
        self.marker.write_text("partial hash")
        self.sync()
        self.assertEqual(len(self.marker.read_text().strip()), 64)

    def test_success_without_dependencies_or_with_changed_inputs_is_not_stamped(self):
        self.runner.side_effect = None
        with self.assertRaisesRegex(RuntimeError, "sentinels"):
            self.sync()
        self.assertFalse(self.marker.exists())
        def changed_during_sync(root, web):
            self.successful_sync(root, web)
            self.write("DEPS", "changed during sync")
        self.runner.side_effect = changed_during_sync
        with self.assertRaisesRegex(RuntimeError, "changed during"):
            self.sync()
        self.assertFalse(self.marker.exists())

    def test_invalid_mode_and_web_template_fail_before_sync(self):
        with self.assertRaises(ValueError):
            self.sync("bogus")
        self.write("engine/scripts/standard.gclient", "unrecognized template")
        with self.assertRaises(ValueError):
            self.sync(web=True)
        self.runner.assert_not_called()

    def test_gclient_command_limits_sync_concurrency(self):
        # Call the real command wrapper with only process execution mocked.
        for web, jobs in ((False, "2"), (True, "1")):
            for os_name in ("nt", "posix"):
                with self.subTest(web=web, os_name=os_name):
                    with patch("sync_engine_deps.subprocess.run") as process, patch.object(deps.os, "name", os_name):
                        ORIGINAL_RUN_GCLIENT(self.root, web)
                        process.assert_called_once_with(
                            ["gclient", "sync", "-D", "-j", jobs],
                            cwd=self.root, check=True, shell=os_name == "nt",
                        )


if __name__ == "__main__":
    unittest.main()
