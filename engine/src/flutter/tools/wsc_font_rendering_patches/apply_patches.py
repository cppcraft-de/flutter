#!/usr/bin/env python3
# Copyright 2013 The Flutter Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Applies local WSC font-rendering patches to DEPS-managed checkouts."""

import argparse
from pathlib import Path
import subprocess
import sys

EXPECTED_SKIA_REVISION = 'e9ed4fc9f1544c58d8a9347c1fc9471d8dd7c465'
EXPECTED_HARFBUZZ_REVISION = '6f4c5cec306d31e6822303f5ba248a14293d588e'

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
        ('skia', 'modules/skparagraph/src/TextStyle.cpp'): 'fSubpixel == that.fSubpixel',
        ('skia', 'modules/skparagraph/src/Run.h'): 'environmentVariableDisabled',
        ('skia', 'modules/skparagraph/src/Run.cpp'): 'Run::commit()',
        ('skia', 'modules/skparagraph/src/TextLine.cpp'): 'fNextLineBaselinePitch',
        ('skia', 'modules/skparagraph/include/TextStyle.h'):
            ('SkFontHinting fHinting = SkFontHinting::kFull'),
        ('skia', 'include/core/SkTypeface.h'): 'getQtLikeGlyphAdvance',
        ('skia', 'modules/skshaper/src/SkShaper_harfbuzz.cpp'): 'skhb_qt_style_script',
        ('skia', 'src/ports/SkFontHost_FreeType.cpp'): 'FT_Size_Metrics& sizeMetrics',
        ('skia', 'src/ports/SkScalerContext_win_dw.cpp'): 'qtLineHeight',
        ('skia', 'src/ports/SkScalerContext_mac_ct.cpp'): 'SkOTTableHorizontalHeader',
        ('harfbuzz', 'src/hb-ot-shape.cc'): 'plan.apply_fallback_kern = true;',
    },
    'diagnostics': {
        ('skia', 'modules/skparagraph/src/ParagraphImpl.cpp'):
            ('diagnosticTableChecksum'),
        ('skia', 'modules/skparagraph/include/Paragraph.h'): 'fAdvanceProbeBackend',
        ('skia', 'modules/canvaskit/paragraph_bindings.cpp'): 'fPlatformGdiCompatibleAdvance',
        ('skia', 'include/core/SkTypeface.h'): 'fGdiCompatibleAdvance',
    },
    'pdf': {
        ('skia', 'modules/canvaskit/canvaskit_bindings.cpp'): 'MakePdf(JSArray pictures',
        ('skia', 'modules/canvaskit/compile.sh'): 'skia_enable_pdf=true',
        ('skia', 'modules/canvaskit/BUILD.gn'): 'SK_SUPPORT_PDF',
    },
}

PATCH_SUBDIRS = {
    'skia': '{group}',
    'harfbuzz': '{group}_harfbuzz',
}

EXPECTED_REVISIONS = {
    'skia': EXPECTED_SKIA_REVISION,
    'harfbuzz': EXPECTED_HARFBUZZ_REVISION,
}


def run_git(repo_dir, args, *, check=True, capture_output=False):
  command = [
      'git',
      '-c',
      f'safe.directory={repo_dir.as_posix()}',
      *args,
  ]
  return subprocess.run(
      command,
      cwd=repo_dir,
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


def patch_groups_already_applied(repo_dirs, groups):
  for group in groups:
    for (repo_name, relative_path), marker in GROUP_MARKERS[group].items():
      contents = (repo_dirs[repo_name] / relative_path).read_text(encoding='utf-8')
      if marker not in contents:
        return False
  return True


def patch_check(repo_dir, patch_file, reverse=False):
  args = ['apply', '--check']
  if reverse:
    args.append('--reverse')
  args.append(str(patch_file))
  result = run_git(repo_dir, args, check=False)
  return result.returncode == 0


def apply_patch(repo_dir, patch_file):
  run_git(repo_dir, ['apply', '--whitespace=nowarn', str(patch_file)])


def selected_patch_files(patch_dir, groups):
  patch_files = []
  for group in groups:
    for repo_name, subdir_template in PATCH_SUBDIRS.items():
      subdir = patch_dir / subdir_template.format(group=group)
      patch_files.extend((repo_name, patch_file) for patch_file in sorted(subdir.glob('*.patch')))
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
      '--harfbuzz-dir',
      type=Path,
      default=default_flutter_dir / 'third_party' / 'harfbuzz',
      help='Path to the HarfBuzz checkout to patch.',
  )
  parser.add_argument(
      '--groups',
      nargs='+',
      default=['all'],
      metavar='GROUP',
      help='Patch groups to apply: all, text_layout, diagnostics, pdf. Diagnostics includes text_layout.',
  )
  args = parser.parse_args(argv[1:])

  repo_dirs = {
      'skia': args.skia_dir.resolve(),
      'harfbuzz': args.harfbuzz_dir.resolve(),
  }
  patch_dir = Path(__file__).resolve().parent
  groups = expand_groups(args.groups)
  patch_files = selected_patch_files(patch_dir, groups)

  if not patch_files:
    print('No WSC font-rendering patch files found.')
    return 0

  needed_repos = {repo_name for repo_name, _ in patch_files}
  for repo_name in sorted(needed_repos):
    repo_dir = repo_dirs[repo_name]
    if not (repo_dir / '.git').exists():
      print(f'{repo_name} checkout not found: {repo_dir}')
      return 1

    head = run_git(repo_dir, ['rev-parse', 'HEAD'], capture_output=True).stdout.strip()
    expected_revision = EXPECTED_REVISIONS[repo_name]
    if head != expected_revision:
      print(
          f'{repo_name} checkout is at {head}, expected {expected_revision}.',
          file=sys.stderr,
      )
      return 1

  if patch_groups_already_applied(repo_dirs, groups):
    print('Selected WSC font-rendering patches are already applied.')
    return 0

  for repo_name, patch_file in patch_files:
    repo_dir = repo_dirs[repo_name]
    if patch_check(repo_dir, patch_file):
      print(f'Applying {patch_file.relative_to(patch_dir)}')
      apply_patch(repo_dir, patch_file)
      continue

    if patch_check(repo_dir, patch_file, reverse=True):
      print(f'{patch_file.relative_to(patch_dir)} is already applied.')
      continue

    print(f'Failed to apply {patch_file.relative_to(patch_dir)}.', file=sys.stderr)
    print('Resolve the Skia checkout state or update the patch stack.', file=sys.stderr)
    return 1

  return 0


if __name__ == '__main__':
  sys.exit(main(sys.argv))
