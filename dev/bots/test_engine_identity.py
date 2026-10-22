"""Offline identity checks, including the unmodified upstream hash helper."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from engine_identity import build_identity, head_content_hash


class EngineIdentityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.git("init", "-b", "main")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        self.git("config", "core.autocrlf", "false")
        self.write("DEPS", "deps\n")
        self.write("engine/patch", "patch\n")
        self.write("bin/internal/release-candidate-branch.version", "release\n")
        self.commit()

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args], stderr=subprocess.PIPE).decode().strip()

    def write(self, name, value):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, newline="\n")

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-m", "fixture")

    def test_framework_changes_keep_identity_engine_changes_invalidate_it(self):
        initial = head_content_hash(self.repo)
        self.write("framework.dart", "framework\n")
        self.commit()
        self.assertEqual(head_content_hash(self.repo), initial)
        for path in ("engine/patch", "DEPS", "bin/internal/release-candidate-branch.version"):
            previous = head_content_hash(self.repo)
            self.write(path, "changed\n")
            self.commit()
            self.assertNotEqual(head_content_hash(self.repo), previous)

    def test_identical_trees_across_history_changes_keep_identity(self):
        initial = head_content_hash(self.repo)
        self.git("commit", "--amend", "-m", "different history")
        self.assertEqual(head_content_hash(self.repo), initial)

    def test_apple_git_workaround_is_scoped_to_ls_tree(self):
        expected = head_content_hash(self.repo)
        config = self.git("config", "--local", "--list")
        real_check_output = subprocess.check_output
        for version in ("git version 2.50.1 (Apple Git-155)", "git version 2.53.0"):
            commands = []
            def run(command, **kwargs):
                commands.append(command)
                if command == ["git", "--version"]:
                    return version
                return real_check_output(command, **kwargs)
            with self.subTest(version=version), patch("engine_identity.subprocess.check_output", side_effect=run):
                self.assertEqual(head_content_hash(self.repo), expected)
            tree_command = next(cmd for cmd in commands if "ls-tree" in cmd)
            self.assertEqual("core.multiPackIndex=false" in tree_command, "Apple Git" in version)
            if "Apple Git" in version:
                self.assertEqual(tree_command[:3], ["git", "-c", "core.multiPackIndex=false"])
            hash_command = next(cmd for cmd in commands if "hash-object" in cmd)
            self.assertNotIn("core.multiPackIndex=false", hash_command)
            self.assertEqual(self.git("config", "--local", "--list"), config)

    def test_missing_hash_input_fails(self):
        self.git("rm", "DEPS")
        self.commit()
        with self.assertRaisesRegex(ValueError, "Missing committed"):
            head_content_hash(self.repo)

    def test_ci_branch_matches_upstream_helper_and_avoids_merge_base(self):
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.git("checkout", "-b", "wsc-development")
        self.write("engine/patch", "fork change\n")
        self.commit()
        suffix = "ps1" if os.name == "nt" else "sh"
        source = Path(__file__).resolve().parents[2] / f"bin/internal/content_aware_hash.{suffix}"
        script = self.repo / f"bin/internal/content_aware_hash.{suffix}"
        shutil.copyfile(source, script)
        command = (["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)]
                   if os.name == "nt" else ["bash", str(script)])
        def upstream():
            return subprocess.check_output(command, cwd=self.repo, stderr=subprocess.PIPE).decode().strip()
        self.assertNotEqual(upstream(), head_content_hash(self.repo))
        self.git("checkout", "-b", "flutter-wsc-candidate.ci")
        self.assertEqual(upstream(), head_content_hash(self.repo))

    def test_gn_output_must_match_source_and_hash(self):
        revision, identity = "a" * 40, "b" * 40
        self.write("args.gn", f'engine_version = "{revision}"\ncontent_hash = "{identity}"\n')
        build_identity(self.repo, identity, revision)
        for expected_hash, expected_revision in (("c" * 40, revision), (identity, "d" * 40)):
            with self.assertRaises(ValueError):
                build_identity(self.repo, expected_hash, expected_revision)


if __name__ == "__main__":
    unittest.main()
