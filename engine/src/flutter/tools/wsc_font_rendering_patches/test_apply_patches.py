#!/usr/bin/env python3
# Copyright 2013 The Flutter Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Exercises sync/reset preservation in disposable nested Git checkouts."""

from pathlib import Path
import tempfile
import unittest

import apply_patches


class PatchResetTest(unittest.TestCase):

  def setUp(self):
    self.temp_dir = tempfile.TemporaryDirectory()
    self.addCleanup(self.temp_dir.cleanup)
    self.repo = Path(self.temp_dir.name) / 'skia'
    self.repo.mkdir()
    self.git('init', '-q')
    self.git('config', 'core.autocrlf', 'false')
    self.source = self.repo / 'source.cc'
    self.source.write_text('original\n', encoding='utf-8', newline='\n')
    self.git('add', 'source.cc')
    self.git(
        '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'Fixture'
    )
    self.source.write_text('patched\n', encoding='utf-8', newline='\n')
    self.header = self.repo / 'FontDiagnostics.h'
    self.header.write_text('diagnostics\n', encoding='utf-8', newline='\n')
    self.git('add', '--intent-to-add', 'FontDiagnostics.h')
    self.patch = Path(self.temp_dir.name) / 'diagnostics.patch'
    self.patch.write_text(self.git('diff', '--binary').stdout, encoding='utf-8', newline='\n')
    self.git('reset', '-q', 'HEAD', '--', 'FontDiagnostics.h')
    self.patch_files = [('skia', self.patch)]

  def git(self, *args):
    return apply_patches.run_git(self.repo, list(args), capture_output=True)

  def reset(self):
    return apply_patches.reset_patch_owned_repos({'skia': self.repo},
                                                 self.patch_files,
                                                 strict_unknown_dirty=True)

  def test_reset_allows_reapply_and_preserves_unrelated_untracked_file(self):
    note = self.repo / 'unrelated.txt'
    note.write_text('keep me', encoding='utf-8', newline='\n')
    self.assertTrue(self.reset())
    self.assertEqual(self.source.read_text(encoding='utf-8'), 'original\n')
    self.assertFalse(self.header.exists())
    self.assertEqual(note.read_text(encoding='utf-8'), 'keep me')
    self.assertTrue(
        apply_patches.apply_selected_patches({'skia': self.repo}, self.patch.parent,
                                             self.patch_files)
    )
    self.assertEqual(self.header.read_text(encoding='utf-8'), 'diagnostics\n')
    self.assertEqual(self.source.read_text(encoding='utf-8'), 'patched\n')

  def test_modified_patch_created_file_blocks_reset_without_losing_edits(self):
    self.header.write_text('diagnostics\nunrelated edit\n', encoding='utf-8', newline='\n')
    before = self.git('diff', '--binary').stdout
    self.assertFalse(self.reset())
    self.assertEqual(self.git('diff', '--binary').stdout, before)
    self.assertEqual(self.header.read_text(encoding='utf-8'), 'diagnostics\nunrelated edit\n')

  def test_unrelated_tracked_changes_block_reset_without_losing_header(self):
    note = self.repo / 'unrelated.txt'
    note.write_text('original\n', encoding='utf-8', newline='\n')
    self.git('add', 'unrelated.txt')
    self.git(
        '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm',
        'Unrelated fixture file'
    )
    note.write_text('unrelated edit\n', encoding='utf-8', newline='\n')
    self.assertFalse(self.reset())
    self.assertTrue(self.header.exists())
    self.assertEqual(note.read_text(encoding='utf-8'), 'unrelated edit\n')
    self.assertEqual(self.source.read_text(encoding='utf-8'), 'patched\n')

  def test_reset_removes_unchanged_header_even_when_tracked_files_are_clean(self):
    self.git('restore', '--', 'source.cc')
    self.assertTrue(self.reset())
    self.assertFalse(self.header.exists())


if __name__ == '__main__':
  unittest.main()
