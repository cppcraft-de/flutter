# Prepare Skia and FreeType after a Flutter update

After rebasing the fork, run this from the Flutter checkout:

```sh
python dev/bots/wsc_rebase.py dependencies
```

The helper finds Skia and FreeType automatically. It reads their URLs and exact
versions from `DEPS`; you do not need to supply paths, copy revision hashes,
or clone the libraries by hand.

You need depot_tools with `gclient` on PATH and the platform's
[engine development prerequisites](../engine/contributing/Setting-up-the-Engine-development-environment.md).
The first setup downloads engine dependencies and toolchains and can take time.
To include the Web engine toolchain, use:

```sh
python dev/bots/wsc_rebase.py dependencies --web
```

An existing standard Web configuration stays enabled on later runs, even without
`--web`. The helper refuses to overwrite a custom `.gclient` configuration.

## What the command does

1. Reads the new Skia and FreeType versions from `DEPS`.
2. Uses existing Git objects where possible, or fetches the required versions
   into temporary storage. It tests every patch in the build's patch order.
3. If a patch fails, prepares a separate repair checkout and stops **before
   syncing dependencies or updating expected revisions**.
4. Checks existing library edits. It can undo exact copies of the current
   patches or the old patches recorded by the rebase helper. Extra edits or
   staged work stop setup and remain untouched.
5. Updates the expected revision values in `apply_patches.py` after both
   libraries pass the patch checks.
6. Runs `gclient sync` through the existing sync helper. This downloads the
   engine dependencies and runs the hooks that apply our patches.
7. Checks that the library versions match `DEPS` and their files contain exactly
   the expected patches. A successful sync alone is not enough.

When it prints `DEPENDENCIES READY`, inspect and commit any patch or helper
changes, then return to [update the engine pin](updating.md#4-update-the-engine-version-used-for-downloads).
There is no engine compilation or rendering test in this command.

```sh
git diff -- engine/src/flutter/tools/wsc_font_rendering_patches
git add -A engine/src/flutter/tools/wsc_font_rendering_patches
git commit -m "Port rendering patches to Flutter 3.44.9"
```

If nothing changed, there is nothing to commit. Replace the version in the
commit message with the version you are updating to.

## If a patch fails

The helper prints the failing patch, the repair folder, and the exact command
for saving your fix. For example, it might create:

```text
D:\flutter-skia-patch-a1b2c3
```

This folder contains the new library version plus the earlier patches already
committed. The failing patch's applicable hunks are applied; rejected hunks are
listed in `.rej` files. A failure that is not a hunk conflict may instead leave
an error message without a `.rej` file. Read the printed error in either case.

1. Open the printed repair folder and inspect the changes:

   ```sh
   cd D:/flutter-skia-patch-a1b2c3
   git status
   git diff
   ```

2. Edit the code to preserve the intended rendering behavior. Use the `.rej`
   files and original patch to see what could not be applied. Delete the `.rej`
   files after incorporating the fixes.

3. Stage only the files belonging to that patch, then review the staged diff.
   For example:

   ```sh
   git add modules/skparagraph/src/Run.cpp
   git diff --cached
   ```

   Include any new files needed by the patch. Do not stage `.rej` files.

4. Run the **save command printed by the helper**. It writes the staged diff
   back to the failing patch file in the Flutter checkout. For example:

   ```sh
   git diff --cached --binary --output="D:/flutter/engine/src/flutter/tools/wsc_font_rendering_patches/text_layout/0002-skparagraph-qt-like-line-and-glyph-layout.patch"
   ```

   Use the printed patch path, not this example if a different patch failed.
   `--output` preserves the patch bytes without shell redirection changing the
   encoding on Windows. Earlier patches are already committed in this folder,
   so they are not included in the diff you save.

5. Return to your Flutter checkout and rerun setup:

   ```sh
   cd D:/flutter
   python dev/bots/wsc_rebase.py dependencies
   ```

   Keep `--web` if you requested it before setup reached the sync step. The
   helper checks the whole patch sequence again and stops at the next failure,
   if any. It keeps repair folders so you can refer to your work afterward.

If upstream now supplies a patch's behavior, remove the obsolete patch from the
Flutter checkout and rerun setup. Check the intended behavior rather than
removing a patch just because it conflicts. Added and deleted patch files are
picked up even before staging; commit them once the checks pass.

## If existing library edits block setup

The helper prints the library path. Inspect that checkout, for example:

```sh
git -C engine/src/flutter/third_party/skia status
git -C engine/src/flutter/third_party/skia diff
```

Save intentional changes as patch files before retrying. The helper compares
file contents, so a manual edit to a file that our patches also change is still
protected. It does not discard those edits merely because it recognizes the
filename. Staged edits also block setup.

If you need to leave the existing library checkout alone, use a
[separate Flutter worktree](updating.md#use-a-separate-folder-if-you-want-one).
The helper records the old fork tip when rebasing, so it can recognize the old
patches after you have edited the new ones. Updates prepared without that
record may need a fresh worktree if their old patches cannot be identified.

## Verify after committing

After committing the changes and updating the engine pin, run:

```sh
python dev/bots/wsc_rebase.py verify
```

This automatically finds both library checkouts, checks their revisions and the
patch helper's expected revisions against `DEPS`, and tests patch application
using temporary Git data. Missing or stale dependencies fail the check with a
command to fix them; they are not silently skipped.

Verification does not fetch, sync, or change the library working files. It tests
whether the committed patches apply, while `dependencies` also checks the files
actually produced by setup. You still need engine builds and rendering tests.
