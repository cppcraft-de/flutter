#!/usr/bin/env python3
# Copyright 2013 The Flutter Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Replay the real legacy patch stack in disposable, minimal Git checkouts."""

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import apply_patches


class PatchReplayTest(unittest.TestCase):

  def setUp(self):
    self.temp = tempfile.TemporaryDirectory()
    self.addCleanup(self.temp.cleanup)
    self.patch_dir = Path(__file__).resolve().parent
    third_party = self.patch_dir.parents[1] / 'third_party'
    self.repos = {}
    self.revisions = {}
    patch_files = apply_patches.selected_patch_files(
        self.patch_dir, list(apply_patches.PATCH_GROUP_ORDER)
    )
    for name, revision in apply_patches.EXPECTED_REVISIONS.items():
      source = third_party / name
      if not (source / '.git').exists():
        self.skipTest(f'Needs the pinned local {name} checkout')
      paths = set()
      for repo, patch in patch_files:
        if repo == name:
          paths.update(
              line.split()[2][2:]
              for line in patch.read_text(encoding='utf-8').splitlines()
              if line.startswith('diff --git a/')
          )
      target = Path(self.temp.name) / name
      target.mkdir()
      for path in sorted(paths):
        result = subprocess.run(
            ['git', '-C', str(source), 'show', f'{revision}:{path}'],
            capture_output=True,
        )
        if result.returncode:
          # FontDiagnostics.h is created by the runtime patch.
          self.assertEqual(path, 'modules/skparagraph/include/FontDiagnostics.h')
          continue
        dest = target / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(result.stdout)
      self.git(target, 'init', '-q')
      self.git(target, 'config', 'core.autocrlf', 'false')
      self.git(target, 'add', '.')
      self.git(
          target, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
          'commit', '-qm', 'Pinned dependency fixture'
      )
      self.repos[name] = target
      self.revisions[name] = self.git(target, 'rev-parse', 'HEAD').stdout.strip()

  def git(self, repo, *args):
    return apply_patches.run_git(repo, list(args), capture_output=True)

  def apply(self):
    args = ['apply_patches.py']
    for name, path in self.repos.items():
      args.extend([f'--{name}-dir', str(path)])
    with mock.patch.dict(apply_patches.EXPECTED_REVISIONS, self.revisions):
      self.assertEqual(apply_patches.main(args), 0)

  def snapshot(self):
    return {
        (name, str(path.relative_to(repo))): path.read_bytes()
        for name, repo in self.repos.items()
        for path in repo.rglob('*')
        if path.is_file() and '.git' not in path.relative_to(repo).parts
    }

  def test_clean_replay_and_idempotence(self):
    self.apply()
    before = self.snapshot()
    self.apply()
    self.assertEqual(self.snapshot(), before)
    self.assertTrue(
        apply_patches.patch_groups_already_applied(
            self.repos, list(apply_patches.PATCH_GROUP_ORDER)
        )
    )

  def test_upgrade_legacy_diagnostics(self):
    for name, patch in apply_patches.selected_patch_files(
        self.patch_dir, list(apply_patches.PATCH_GROUP_ORDER)
    ):
      if patch.name in {upgrade[0] for upgrade in apply_patches.GROUP_UPGRADES.values()}:
        continue
      apply_patches.apply_patch(self.repos[name], patch)
    self.apply()
    before = self.snapshot()
    self.apply()
    self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
  unittest.main()
