#!/usr/bin/env python3
# Copyright 2013 The Flutter Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Applies local WSC font-rendering patches to the DEPS-managed Skia checkout."""

import argparse
from pathlib import Path
import subprocess
import sys

EXPECTED_SKIA_REVISION = 'e9ed4fc9f1544c58d8a9347c1fc9471d8dd7c465'

PATCH_GROUP_ORDER = (
    'text_layout',
    'diagnostics',
    'pdf',
)

GROUP_DEPENDENCIES = {
    'diagnostics': ('text_layout',),
}

GROUP_MARKERS = {
    'text_layout': {
        'modules/skparagraph/src/TextStyle.cpp': 'fSubpixel == that.fSubpixel',
        'modules/skparagraph/src/Run.h': 'environmentVariableDisabled',
        'modules/skparagraph/src/Run.cpp': 'Run::commit()',
        'modules/skparagraph/src/TextLine.cpp': 'fNextLineBaselinePitch',
        'modules/canvaskit/paragraph_bindings.cpp': 'ts.setFontHinting(s.fontHinting)',
        'src/ports/SkFontHost_FreeType.cpp': 'FT_Size_Metrics& sizeMetrics',
        'src/ports/SkScalerContext_win_dw.cpp': 'qtLineHeight',
        'src/ports/SkScalerContext_mac_ct.cpp': 'SkOTTableHorizontalHeader',
    },
    'diagnostics': {
        'modules/skparagraph/src/ParagraphImpl.cpp': 'ParagraphImpl::getGlyphDiagnostics',
        'modules/skparagraph/include/Paragraph.h': 'struct GlyphDiagnostic',
        'modules/canvaskit/paragraph_bindings.cpp': 'getGlyphDiagnostics',
    },
    'pdf': {
        'modules/canvaskit/canvaskit_bindings.cpp': 'MakePdf(JSArray pictures',
        'modules/canvaskit/compile.sh': 'skia_enable_pdf=true',
        'modules/canvaskit/BUILD.gn': 'SK_SUPPORT_PDF',
    },
}


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


def expand_groups(groups):
  if groups == ['all']:
    return list(PATCH_GROUP_ORDER)

  selected = []
  pending = list(groups)
  while pending:
    group = pending.pop(0)
    if group == 'all':
      return list(PATCH_GROUP_ORDER)
    if group not in PATCH_GROUP_ORDER:
      raise ValueError(f'Unknown patch group: {group}')
    for dependency in GROUP_DEPENDENCIES.get(group, ()):
      if dependency not in selected and dependency not in pending:
        pending.insert(0, dependency)
    if group not in selected:
      selected.append(group)
  return [group for group in PATCH_GROUP_ORDER if group in selected]


def patch_groups_already_applied(skia_dir, groups):
  for group in groups:
    for relative_path, marker in GROUP_MARKERS[group].items():
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


def selected_patch_files(patch_dir, groups):
  patch_files = []
  for group in groups:
    patch_files.extend(sorted((patch_dir / group).glob('*.patch')))
  return patch_files


def main(argv):
  parser = argparse.ArgumentParser()
  default_flutter_dir = Path(__file__).resolve().parents[2]
  parser.add_argument(
      '--skia-dir',
      type=Path,
      default=default_flutter_dir / 'third_party' / 'skia',
      help='Path to the Skia checkout to patch.',
  )
  parser.add_argument(
      '--groups',
      nargs='+',
      default=['all'],
      metavar='GROUP',
      help='Patch groups to apply: all, text_layout, diagnostics, pdf. Diagnostics includes text_layout.',
  )
  args = parser.parse_args(argv[1:])

  skia_dir = args.skia_dir.resolve()
  patch_dir = Path(__file__).resolve().parent
  groups = expand_groups(args.groups)
  patch_files = selected_patch_files(patch_dir, groups)

  if not patch_files:
    print('No WSC font-rendering patch files found.')
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

  if patch_groups_already_applied(skia_dir, groups):
    print('Selected WSC font-rendering patches are already applied.')
    return 0

  for patch_file in patch_files:
    if patch_check(skia_dir, patch_file):
      print(f'Applying {patch_file.relative_to(patch_dir)}')
      apply_patch(skia_dir, patch_file)
      continue

    if patch_check(skia_dir, patch_file, reverse=True):
      print(f'{patch_file.relative_to(patch_dir)} is already applied.')
      continue

    print(f'Failed to apply {patch_file.relative_to(patch_dir)}.', file=sys.stderr)
    print('Resolve the Skia checkout state or update the patch stack.', file=sys.stderr)
    return 1

  return 0


if __name__ == '__main__':
  sys.exit(main(sys.argv))
