"""Offline integration tests: only disposable local Git repositories are pushed."""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import sync_upstream as workflow


class SyncUpstreamTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wsc-sync-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.fork = self.root / "fork.git"
        self.repo = self.root / "working copy"
        for path in (self.source, self.fork, self.repo):
            path.mkdir()
        self.git(self.source, "init", "--quiet", "--initial-branch=main")
        self.git(self.fork, "init", "--quiet", "--bare")
        self.git(self.repo, "init", "--quiet", "--initial-branch=wsc-work")
        for path in (self.source, self.repo):
            self.git(path, "config", "user.name", "Sync Fixture")
            self.git(path, "config", "user.email", "sync@example.invalid")
            self.git(path, "config", "commit.gpgSign", "false")
            self.git(path, "config", "tag.gpgSign", "false")
            self.git(path, "config", "core.hooksPath", str(self.root / "no-hooks"))
        self.first = self.commit(self.source, "upstream one")
        self.git(self.source, "branch", "stable")
        self.git(self.source, "branch", "beta")
        self.git(self.source, "branch", "feature/nested")
        self.git(self.source, "tag", "3.44.4")
        self.git(self.source, "tag", "-a", "3.44.5", "-m", "Annotated upstream tag")
        self.wsc = self.commit(self.repo, "WSC work")
        self.git(self.repo, "tag", "wsc-3.44.4-r1")
        self.git(self.repo, "tag", "unpublished-local-tag")
        self.git(self.repo, "remote", "add", "upstream", str(self.source))
        self.git(self.repo, "remote", "add", "origin", str(self.fork))
        self.git(self.repo, "push", "origin", "HEAD:main", "HEAD:stable", "HEAD:beta",
                 "HEAD:wsc-feature", "refs/tags/wsc-3.44.4-r1")
        # Populate reusable objects without importing source tags into local tags.
        self.git(self.repo, "fetch", "--no-tags", "upstream")
        (self.repo / "untracked.txt").write_text("Do not touch\n")
        self.local_refs = self.git(self.repo, "show-ref")
        self.local_status = self.git(self.repo, "status", "--porcelain")

    @staticmethod
    def git(repo, *args):
        return workflow.git(repo, *args)

    def commit(self, repo, message):
        self.git(repo, "commit", "--allow-empty", "--quiet", "-m", message)
        return self.git(repo, "rev-parse", "HEAD")

    def refs(self):
        return workflow.read_refs(self.repo, str(self.fork))

    def sync(self, apply=True, prune=False):
        output = io.StringIO()
        with redirect_stdout(output):
            workflow.sync(self.repo, apply=apply, prune=prune)
        return output.getvalue()

    def test_preview_is_read_only(self):
        before = self.refs()
        self.assertIn("Preview only", self.sync(apply=False))
        self.assertEqual(self.refs(), before)
        self.assertEqual(self.git(self.repo, "show-ref"), self.local_refs)

    def test_sync_preserves_channels_local_refs_and_annotated_tags(self):
        before = self.refs()
        self.sync()
        after = self.refs()
        for ref, oid in before.items():
            self.assertEqual(after[ref], oid)
        for ref, oid in workflow.read_refs(self.repo, str(self.source)).items():
            destination = ref.replace("refs/heads/", "refs/heads/upstream/", 1)
            self.assertEqual(after[destination], oid)
        self.assertNotIn("refs/tags/unpublished-local-tag", after)
        self.assertEqual(self.git(self.repo, "show-ref"), self.local_refs)
        self.assertEqual(self.git(self.repo, "status", "--porcelain"), self.local_status)
        self.assertIn("Already synchronized", self.sync())
        self.assertEqual(self.refs(), after)

    def test_new_commits_and_tags_then_upstream_rewind(self):
        self.sync()
        second = self.commit(self.source, "upstream two")
        self.git(self.source, "tag", "3.44.6")
        self.sync()
        self.assertEqual(self.refs()["refs/heads/upstream/main"], second)
        self.assertEqual(self.refs()["refs/tags/3.44.6"], second)
        self.git(self.source, "update-ref", "refs/heads/main", self.first)
        self.sync()
        self.assertEqual(self.refs()["refs/heads/upstream/main"], self.first)
        self.assertEqual(self.refs()["refs/heads/main"], self.wsc)

    def test_missing_global_channels_are_not_created(self):
        for branch in ("main", "stable", "beta"):
            self.git(self.fork, "update-ref", "-d", f"refs/heads/{branch}")
        self.sync()
        for branch in ("main", "stable", "beta"):
            self.assertNotIn(f"refs/heads/{branch}", self.refs())
            self.assertIn(f"refs/heads/upstream/{branch}", self.refs())

    def test_deleted_source_refs_are_retained(self):
        self.sync()
        before = self.refs()
        self.git(self.source, "branch", "-D", "feature/nested")
        self.git(self.source, "tag", "-d", "3.44.4")
        self.assertIn("KEEP refs/heads/upstream/feature/nested", self.sync())
        self.assertEqual(self.refs(), before)

    def test_prune_preview_and_apply_only_remove_stale_upstream_branches(self):
        self.sync()
        before = self.refs()
        self.git(self.source, "branch", "-D", "feature/nested")
        self.git(self.source, "tag", "-d", "3.44.4")
        stale = "refs/heads/upstream/feature/nested"
        self.assertIn(f"DELETE {stale}", self.sync(apply=False, prune=True))
        self.assertEqual(self.refs(), before)
        self.assertIn(f"DELETE {stale}", self.sync(prune=True))
        self.assertEqual(self.refs(), {ref: oid for ref, oid in before.items() if ref != stale})
        self.assertIn("Already synchronized", self.sync(prune=True))

    def test_prune_can_publish_updates_and_deletions_together(self):
        self.sync()
        self.git(self.source, "branch", "-D", "feature/nested")
        second = self.commit(self.source, "upstream two")
        self.git(self.source, "tag", "3.44.6")
        self.sync(prune=True)
        self.assertNotIn("refs/heads/upstream/feature/nested", self.refs())
        self.assertEqual(self.refs()["refs/heads/upstream/main"], second)
        self.assertEqual(self.refs()["refs/tags/3.44.6"], second)

    def test_git_repository_environment_overrides_are_rejected_before_git(self):
        for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                     "GIT_OBJECT_DIRECTORY", "GIT_NAMESPACE", "GIT_SHALLOW_FILE"):
            with self.subTest(name=name), patch.dict(os.environ, {name: str(self.repo / ".git")}):
                with patch.object(workflow, "git") as git:
                    with self.assertRaisesRegex(workflow.SyncError, name):
                        self.sync()
                    git.assert_not_called()
        self.assertEqual(self.git(self.repo, "config", "core.bare"), "false")
        self.assertEqual(self.git(self.repo, "show-ref"), self.local_refs)

    def assert_branch_race_rejected(self, ref, *, prune=False):
        original = workflow.git

        def racing_branch(repo, *args, **kwargs):
            if args[0] == "push":
                original(self.fork, "update-ref", ref, self.wsc)
            return original(repo, *args, **kwargs)

        before = self.refs()
        with patch.object(workflow, "git", side_effect=racing_branch):
            with self.assertRaisesRegex(workflow.SyncError, "push failed"):
                self.sync(prune=prune)
        self.assertEqual(self.refs(), {**before, ref: self.wsc})

    def test_concurrent_branch_creation_is_not_overwritten(self):
        self.assert_branch_race_rejected("refs/heads/upstream/main")

    def test_concurrent_branch_update_is_not_overwritten(self):
        self.sync()
        self.commit(self.source, "upstream two")
        self.assert_branch_race_rejected("refs/heads/upstream/main")

    def test_concurrently_changed_stale_branch_is_not_deleted(self):
        self.sync()
        self.git(self.source, "branch", "-D", "feature/nested")
        self.assert_branch_race_rejected("refs/heads/upstream/feature/nested", prune=True)

    def test_branch_not_in_plan_is_not_overwritten(self):
        self.sync()
        self.git(self.source, "tag", "3.44.6")
        original = workflow.git

        def racing_branch(repo, *args, **kwargs):
            if args[0] == "push":
                original(self.fork, "update-ref", "refs/heads/upstream/main", self.wsc)
            return original(repo, *args, **kwargs)

        with patch.object(workflow, "git", side_effect=racing_branch):
            with self.assertRaisesRegex(workflow.SyncError, "verification differs"):
                self.sync()
        self.assertEqual(self.refs()["refs/heads/upstream/main"], self.wsc)
        self.assertEqual(self.refs()["refs/tags/3.44.6"], self.first)

    def test_large_sync_update_and_prune_keep_one_short_push(self):
        # Four fixture branches plus these 902 reproduce the real branch count.
        branches = [f"refs/heads/cached-upstream-branch-{i:04d}" for i in range(902)]
        tags = [f"refs/tags/bulk-tag-{i:04d}" for i in range(1200)]

        def update_refs(commands):
            result = subprocess.run(["git", "-C", str(self.source), "update-ref", "--stdin"],
                                    input=("\n".join(commands) + "\n").encode("utf-8"),
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))

        update_refs(f"create {ref} {self.first}" for ref in branches + tags)
        original = workflow.git
        pushes = []

        def bounded_git(repo, *args, **kwargs):
            command = ["git", "-C", str(repo), *args]
            # Assert before launching, so the regression also fails on Unix.
            self.assertLess(len(subprocess.list2cmdline(command)), 32767)
            if args[0] == "push":
                pushes.append(command)
            return original(repo, *args, **kwargs)

        with patch.object(workflow, "git", side_effect=bounded_git):
            self.sync()
            after = self.refs()
            self.assertEqual(sum(ref.startswith("refs/heads/upstream/") for ref in after), 906)
            for ref in tags:
                self.assertEqual(after[ref], self.first)
            second = self.commit(self.source, "bulk upstream update")
            update_refs(f"update {ref} {second}" for ref in branches)
            self.sync()
            after = self.refs()
            for ref in branches:
                self.assertEqual(after[ref.replace("refs/heads/", "refs/heads/upstream/", 1)], second)
            update_refs(f"delete {ref}" for ref in branches)
            self.sync(prune=True)
        self.assertEqual(len(pushes), 3)  # No splitting atomic publication into batches.
        after = self.refs()
        self.assertEqual(sum(ref.startswith("refs/heads/upstream/") for ref in after), 4)
        self.assertEqual(after["refs/heads/stable"], self.wsc)
        for ref in tags:
            self.assertEqual(after[ref], self.first)

    def test_destination_change_during_tracking_fetch_aborts(self):
        self.sync()
        self.commit(self.source, "upstream two")
        before = self.refs()
        original = workflow.git

        def moving_destination(repo, *args, **kwargs):
            if args[0] == "fetch" and args[-1].startswith("wsc-upstream-sync-"):
                original(self.fork, "update-ref", "refs/heads/upstream/main", self.wsc)
            self.assertNotEqual(args[0], "push")
            return original(repo, *args, **kwargs)

        with patch.object(workflow, "git", side_effect=moving_destination):
            with self.assertRaisesRegex(workflow.SyncError, "Destination changed during fetch"):
                self.sync()
        self.assertEqual(self.refs(), {**before, "refs/heads/upstream/main": self.wsc})

    def test_tag_conflict_blocks_all_updates_including_new_branches(self):
        self.git(self.repo, "push", "origin", "HEAD:refs/tags/3.44.4")
        before = self.refs()
        for apply in (False, True):
            with self.assertRaisesRegex(workflow.SyncError, "Conflicting upstream tags"):
                self.sync(apply=apply)
            self.assertEqual(self.refs(), before)

    def test_recreated_annotation_at_same_commit_is_a_conflict(self):
        self.sync()
        before = self.refs()
        self.git(self.source, "tag", "-f", "-a", "3.44.5", "-m", "Different annotation")
        with self.assertRaisesRegex(workflow.SyncError, "Conflicting upstream tags"):
            self.sync()
        self.assertEqual(self.refs(), before)

    def test_server_without_atomic_support_is_rejected_without_fallback(self):
        before = self.refs()
        self.git(self.fork, "config", "receive.advertiseAtomic", "false")
        with self.assertRaisesRegex(workflow.SyncError, "push failed"):
            self.sync()
        self.assertEqual(self.refs(), before)

    def test_server_policy_failure_is_explicit_and_retry_converges(self):
        before = self.refs()
        self.git(self.fork, "config", "receive.hideRefs", "refs/heads/upstream/stable")
        with self.assertRaisesRegex(workflow.SyncError, "Inspect a fresh preview"):
            self.sync()
        # Git versions/server policies may partially accept even --atomic.
        # Never roll back accepted objects or touch existing WSC refs.
        for ref, oid in before.items():
            self.assertEqual(self.refs()[ref], oid)
        self.git(self.fork, "config", "--unset", "receive.hideRefs")
        self.sync()
        self.assertIn("Already synchronized", self.sync())

    def test_tag_created_after_preflight_is_not_overwritten(self):
        original = workflow.git

        def racing_tag(repo, *args, **kwargs):
            if args[0] == "push":
                original(self.repo, "push", "origin", "HEAD:refs/tags/3.44.4")
            return original(repo, *args, **kwargs)

        with patch.object(workflow, "git", side_effect=racing_tag):
            with self.assertRaisesRegex(workflow.SyncError, "push failed"):
                self.sync()
        self.assertEqual(self.refs()["refs/tags/3.44.4"], self.wsc)
        self.assertNotIn("refs/heads/upstream/main", self.refs())

    def test_source_change_during_fetch_does_not_push(self):
        before = self.refs()
        original = workflow.git

        def moving_source(repo, *args, **kwargs):
            if args[0] == "fetch":
                self.commit(self.source, "concurrent upstream update")
            return original(repo, *args, **kwargs)

        with patch.object(workflow, "git", side_effect=moving_source):
            with self.assertRaisesRegex(workflow.SyncError, "Upstream changed"):
                self.sync()
        self.assertEqual(self.refs(), before)

    def test_destination_push_url_is_used(self):
        self.git(self.repo, "remote", "set-url", "origin", str(self.root / "not-a-repository"))
        self.git(self.repo, "remote", "set-url", "--push", "origin", str(self.fork))
        self.sync()
        self.assertEqual(self.refs()["refs/heads/upstream/main"], self.first)

    def test_multiple_push_urls_and_same_repository_are_rejected(self):
        self.git(self.repo, "remote", "set-url", "--add", "--push", "origin", str(self.fork))
        self.git(self.repo, "remote", "set-url", "--add", "--push", "origin", str(self.source))
        with self.assertRaisesRegex(workflow.SyncError, "exactly one push URL"):
            self.sync()
        with self.assertRaisesRegex(workflow.SyncError, "different repositories"):
            workflow.sync(self.repo, destination="upstream")


if __name__ == "__main__":
    unittest.main()
