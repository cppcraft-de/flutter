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
        ('skia', 'modules/canvaskit/paragraph.js'): 'registerTypeface = function(typeface, family)',
        ('skia', 'modules/skparagraph/include/FontCollection.h'): 'clearFontLookupCaches',
        ('skia', 'modules/skshaper/src/SkShaper_harfbuzz.cpp'): 'skhb_qt_style_script',
        ('skia', 'src/ports/SkFontHost_FreeType.cpp'): 'FT_Size_Metrics& sizeMetrics',
        ('harfbuzz', 'src/hb-ot-shape.cc'): 'plan.apply_fallback_kern = true;',
    },
    'diagnostics': {
        ('skia', 'modules/skparagraph/src/ParagraphImpl.cpp'): ('getLegacyPairKerningX'),
        ('skia', 'modules/skparagraph/include/Paragraph.h'): 'fRawShapePosition',
        ('skia', 'modules/canvaskit/paragraph_bindings.cpp'): 'getGlyphDiagnostics',
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

STALE_GCLIENT_ENTRIES = ("'engine/src/flutter/third_party/freetype2':",)

LEGACY_WSC_PATCH_PATHS = {
    'skia': {
        'src/ports/SkScalerContext_mac_ct.cpp',
        'src/ports/SkScalerContext_win_dw.cpp',
        'src/ports/SkTypeface_mac_ct.cpp',
        'src/ports/SkTypeface_mac_ct.h',
        'src/ports/SkTypeface_win_dw.cpp',
        'src/ports/SkTypeface_win_dw.h',
    },
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


def patch_group_already_applied(repo_dirs, group):
  for (repo_name, relative_path), marker in GROUP_MARKERS[group].items():
    marker_path = repo_dirs[repo_name] / relative_path
    if not marker_path.exists():
      return False
    contents = marker_path.read_text(encoding='utf-8')
    if marker not in contents:
      return False
  return True


def patch_groups_already_applied(repo_dirs, groups):
  return all(patch_group_already_applied(repo_dirs, group) for group in groups)


def unapplied_groups(repo_dirs, groups):
  remaining = []
  for group in groups:
    if patch_group_already_applied(repo_dirs, group):
      print(f'{group} WSC font-rendering patches are already applied.')
    else:
      remaining.append(group)
  return remaining


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


def patch_touched_paths(patch_file):
  paths = set()
  for line in patch_file.read_text(encoding='utf-8').splitlines():
    if not line.startswith('diff --git a/'):
      continue
    parts = line.split()
    if len(parts) < 4:
      continue
    for path in parts[2:4]:
      if path.startswith('a/') or path.startswith('b/'):
        paths.add(path[2:])
  return paths


def dirty_paths(repo_dir):
  result = run_git(repo_dir, ['diff', '--name-only'], capture_output=True)
  return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def ensure_repos_available(repo_dirs, repo_names, *, reverse):
  for repo_name in sorted(repo_names):
    repo_dir = repo_dirs[repo_name]
    if not (repo_dir / '.git').exists():
      if reverse:
        print(f'{repo_name} checkout not found, nothing to unapply: {repo_dir}')
        continue
      print(f'{repo_name} checkout not found: {repo_dir}')
      return False

    if reverse:
      continue

    head = run_git(repo_dir, ['rev-parse', 'HEAD'], capture_output=True).stdout.strip()
    expected_revision = EXPECTED_REVISIONS[repo_name]
    if head != expected_revision:
      print(
          f'{repo_name} checkout is at {head}, expected {expected_revision}.',
          file=sys.stderr,
      )
      return False
  return True


def apply_selected_patches(repo_dirs, patch_dir, patch_files):
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
    return False
  return True


def reset_patch_owned_repos(repo_dirs, patch_files, *, strict_unknown_dirty):
  allowed_paths_by_repo = {}
  for repo_name, patch_file in patch_files:
    allowed_paths_by_repo.setdefault(repo_name, set()).update(patch_touched_paths(patch_file))
  for repo_name, legacy_paths in LEGACY_WSC_PATCH_PATHS.items():
    allowed_paths_by_repo.setdefault(repo_name, set()).update(legacy_paths)

  for repo_name, allowed_paths in sorted(allowed_paths_by_repo.items()):
    repo_dir = repo_dirs[repo_name]
    if not (repo_dir / '.git').exists():
      continue

    dirty = dirty_paths(repo_dir)
    if not dirty:
      print(f'{repo_name} checkout is clean.')
      continue

    unknown = sorted(dirty - allowed_paths)
    if unknown:
      print(f'{repo_name} checkout has non-WSC changes:', file=sys.stderr)
      for path in unknown:
        print(f'  {path}', file=sys.stderr)
      if strict_unknown_dirty:
        print('Resolve those nested checkout changes before running gclient sync.', file=sys.stderr)
        return False

      print(
          'Leaving this checkout dirty so gclient can report the managed-dependency '
          'state normally.',
          file=sys.stderr,
      )
      continue

    print(f'Resetting {repo_name} WSC patch-owned changes before sync.')
    run_git(repo_dir, ['reset', '--hard', 'HEAD'])
  return True


def remove_stale_gclient_entries(flutter_dir):
  gclient_root = Path.cwd()
  if not (gclient_root / '.gclient_entries').exists():
    gclient_root = flutter_dir.parents[2]
  gclient_entries = gclient_root / '.gclient_entries'
  if not gclient_entries.exists():
    return

  lines = gclient_entries.read_text(encoding='utf-8').splitlines(keepends=True)
  filtered_lines = [
      line for line in lines if not any(entry in line for entry in STALE_GCLIENT_ENTRIES)
  ]
  if filtered_lines == lines:
    return

  gclient_entries.write_text(''.join(filtered_lines), encoding='utf-8')
  print('Removed stale freetype2 entry from .gclient_entries.')


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
      '--reverse',
      action='store_true',
      help='Reset WSC patch-owned nested checkout changes before gclient sync.',
  )
  parser.add_argument(
      '--gclient-pre-deps-hook',
      action='store_true',
      help='Run in best-effort mode for gclient pre_deps_hooks.',
  )
  parser.add_argument(
      '--groups',
      nargs='+',
      default=['all'],
      metavar='GROUP',
      help=(
          'Patch groups to apply: all, text_layout, diagnostics, pdf. '
          'Diagnostics includes text_layout.'
      ),
  )
  args = parser.parse_args(argv[1:])

  repo_dirs = {
      'skia': args.skia_dir.resolve(),
      'harfbuzz': args.harfbuzz_dir.resolve(),
  }
  patch_dir = Path(__file__).resolve().parent
  groups = expand_groups(args.groups)
  if args.reverse:
    groups_to_process = groups
  else:
    groups_to_process = unapplied_groups(repo_dirs, groups)

  if not groups_to_process:
    print('Selected WSC font-rendering patches are already applied.')
    return 0

  patch_files = selected_patch_files(patch_dir, groups_to_process)

  if not patch_files:
    print('No WSC font-rendering patch files found.')
    return 0

  if args.reverse:
    remove_stale_gclient_entries(default_flutter_dir)

  needed_repos = {repo_name for repo_name, _ in patch_files}
  if not ensure_repos_available(repo_dirs, needed_repos, reverse=args.reverse):
    return 1

  if not args.reverse and patch_groups_already_applied(repo_dirs, groups):
    print('Selected WSC font-rendering patches are already applied.')
    return 0

  if args.reverse:
    if not reset_patch_owned_repos(
        repo_dirs,
        patch_files,
        strict_unknown_dirty=not args.gclient_pre_deps_hook,
    ):
      return 1
    print('Selected WSC font-rendering patches are reset for sync.')
  else:
    if not apply_selected_patches(repo_dirs, patch_dir, patch_files):
      return 1
    print('Selected WSC font-rendering patches are applied.')

  return 0


if __name__ == '__main__':
  sys.exit(main(sys.argv))
