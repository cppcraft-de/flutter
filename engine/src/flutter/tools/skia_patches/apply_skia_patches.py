#!/usr/bin/env python3
# Copyright 2013 The Flutter Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Applies local Flutter text patches to the DEPS-managed Skia checkout."""

import argparse
import os
from pathlib import Path
import subprocess
import sys

EXPECTED_SKIA_REVISION = 'e9ed4fc9f1544c58d8a9347c1fc9471d8dd7c465'


def run_git(skia_dir, args, *, check=True, capture_output=False):
  command = [
      'git',
      '-c',
      f'safe.directory={skia_dir.as_posix()}',
      *args,
  ]
  return subprocess.run(
      command,
      cwd=skia_dir,
      check=check,
      capture_output=capture_output,
      text=True,
  )


def patch_stack_already_applied(skia_dir):
  required_markers = {
      'modules/skparagraph/src/ParagraphImpl.cpp': 'ParagraphImpl::getGlyphDiagnostics',
      'modules/skparagraph/src/Run.h': 'kUseQtLikeIntegerMetricsByDefault',
      'modules/skparagraph/src/TextLine.cpp': 'fNextLineBaselinePitch',
      'modules/canvaskit/paragraph_bindings.cpp': 'getGlyphDiagnostics',
      'src/ports/SkFontHost_FreeType.cpp': 'FT_Size_Metrics& sizeMetrics',
      'src/ports/SkScalerContext_win_dw.cpp': 'qtLineHeight',
      'src/ports/SkScalerContext_mac_ct.cpp': 'SkOTTableHorizontalHeader',
      'modules/canvaskit/canvaskit_bindings.cpp': 'MakePdf(JSArray pictures',
      'modules/canvaskit/compile.sh': 'skia_enable_pdf=true',
  }
  for relative_path, marker in required_markers.items():
    contents = (skia_dir / relative_path).read_text(encoding='utf-8')
    if marker not in contents:
      return False
  return True


def patch_check(skia_dir, patch_file, reverse=False):
  args = ['apply', '--check']
  if reverse:
    args.append('--reverse')
  args.append(str(patch_file))
  result = run_git(skia_dir, args, check=False)
  return result.returncode == 0


def apply_patch(skia_dir, patch_file):
  run_git(skia_dir, ['apply', '--whitespace=nowarn', str(patch_file)])


def main(argv):
  parser = argparse.ArgumentParser()
  default_flutter_dir = Path(__file__).resolve().parents[2]
  parser.add_argument(
      '--skia-dir',
      type=Path,
      default=default_flutter_dir / 'third_party' / 'skia',
      help='Path to the Skia checkout to patch.',
  )
  args = parser.parse_args(argv[1:])

  skia_dir = args.skia_dir.resolve()
  patch_dir = Path(__file__).resolve().parent
  patch_files = sorted(patch_dir.glob('*.patch'))

  if not patch_files:
    print('No Skia patch files found.')
    return 0

  if not (skia_dir / '.git').exists():
    print(f'Skia checkout not found: {skia_dir}')
    return 1

  head = run_git(
      skia_dir,
      ['rev-parse', 'HEAD'],
      capture_output=True,
  ).stdout.strip()
  if head != EXPECTED_SKIA_REVISION:
    print(
        f'Skia checkout is at {head}, expected {EXPECTED_SKIA_REVISION}.',
        file=sys.stderr,
    )
    return 1

  if patch_stack_already_applied(skia_dir):
    print('Local Skia text patches are already applied.')
    return 0

  for patch_file in patch_files:
    if patch_check(skia_dir, patch_file):
      print(f'Applying {patch_file.name}')
      apply_patch(skia_dir, patch_file)
      continue

    if patch_check(skia_dir, patch_file, reverse=True):
      print(f'{patch_file.name} is already applied.')
      continue

    print(f'Failed to apply {patch_file.name}.', file=sys.stderr)
    print('Resolve the Skia checkout state or update the patch stack.', file=sys.stderr)
    return 1

  return 0


if __name__ == '__main__':
  sys.exit(main(sys.argv))
