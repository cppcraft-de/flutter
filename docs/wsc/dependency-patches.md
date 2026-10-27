# Port Skia and FreeType patches

Flutter uses Skia and FreeType for rendering. Engine dependency setup downloads
these libraries, then applies our patch files from this repository to them.
A Flutter update can change the libraries enough that these patches need
adjusting.

Use this guide to make those adjustments in the separate update folder created
by [Update to a new Flutter version](updating.md). Keep your existing development
and Jenkins build folders intact.

The files under
[wsc_font_rendering_patches](../../engine/src/flutter/tools/wsc_font_rendering_patches/)
are what the build uses. If you edit Skia or FreeType directly, you must save
those edits back into these patch files for them to be included in a release.

## 1. Check the new dependency revisions

`DEPS` records which versions of Skia and FreeType Flutter uses. In the update
folder, compare [DEPS](../../DEPS) with
[apply_patches.py](../../engine/src/flutter/tools/wsc_font_rendering_patches/apply_patches.py):

- Skia: `skia_revision` in `DEPS` and `EXPECTED_SKIA_REVISION` in the helper.
- FreeType: the revision of `engine/src/flutter/third_party/freetype2` in
  `DEPS` and `EXPECTED_FREETYPE_REVISION` in the helper.

Use the new upstream dependency revisions. Port and check the patches before
updating the helper's expected revisions. Do not restore old dependency pins
just to make the patch check pass.

## 2. Fix a patch in a separate checkout

If the update folder already has patched Skia or FreeType checkouts, save any
edits you made there before replacing the patch files. Use the helper's
`--reverse` option with the old patch files to undo the old patches first. If
you no longer have those files or cannot determine what was applied, use a fresh
update folder for the dependency checks below. Preserve the existing checkout.

Make a separate checkout for each library you need to change. These are temporary
editing folders, separate from the Flutter update folder. Use the repository
URL and commit from the new `DEPS`. For example,
replace `SKIA_URL` and `NEW_SKIA_SHA` below:

```sh
git clone SKIA_URL ../wsc-skia-port
git -C ../wsc-skia-port checkout --detach NEW_SKIA_SHA
```

Use a separate directory for FreeType. These checkouts are for editing patches;
they do not need the full Flutter build dependencies.

Read `PATCH_GROUP_ORDER` and `PATCH_SUBDIRS` in `apply_patches.py`. Within each
group, patches apply in filename order. Apply them to the appropriate repository
in that order. Use absolute patch paths in the commands below.

```sh
git -C ../wsc-skia-port apply --check PATH_TO_PATCH
git -C ../wsc-skia-port apply PATH_TO_PATCH
```

When a patch fails:

1. In the **temporary library checkout**, commit the earlier patches that
   applied successfully. This gives you the starting state for the failing patch.
2. Read the failing patch and the changed upstream code. Implement the intended
   rendering behavior in the updated library, or remove the patch if upstream
   now supplies that behavior. Check that the resulting rendering still matches
   the intended behavior.
3. Stage only the files belonging to this patch, including any new files. Review
   the staged diff, then write it to the corresponding patch file in the Flutter
   update folder:

   ```sh
   git -C ../wsc-skia-port add PATH_TO_CHANGED_FILE
   git -C ../wsc-skia-port diff --cached
   git -C ../wsc-skia-port diff --cached --binary --output=ABSOLUTE_PATH_TO_PATCH_FILE
   ```

4. Commit this patch's changes in the temporary library checkout before porting
   the next one. Keep each patch's diff separate from the earlier patches.
5. Once all patches apply, update the helper's expected revisions in the Flutter
   update folder.
   Check `GROUP_MARKERS` if the patched code moved or changed. Those markers let
   the hook recognize an applied group; they do not prove rendering correctness.

Use `--output` to write patch bytes directly. Shell redirection can change the
encoding on Windows. Keep the resulting patch files and helper edits in the
Flutter update folder; the temporary commits are only for editing.

## 3. Check that dependency setup applies the patches

Stage the reviewed patch files and helper edits in the Flutter update branch
before syncing.
Use path-specific `git add` for additions/edits and `git rm` for removed patches.
An unstaged patch deletion makes the sync helper fail while reading tracked
inputs, before it reaches `gclient`.

From the Flutter update folder, check for edits inside the library checkouts:

```sh
git -C engine/src/flutter/third_party/skia status --short
git -C engine/src/flutter/third_party/freetype2 status --short
```

Skip these status commands if the dependencies have not been downloaded yet.
An outer `git status` does not show all nested edits. Save intentional edits as
patches first: dependency setup resets changes made by the fork's patches.

With depot_tools and the platform's
[engine prerequisites](../engine/contributing/Setting-up-the-Engine-development-environment.md)
available, run:

```sh
python dev/bots/sync_engine_deps.py --mode true
git -C engine/src/flutter/third_party/skia rev-parse HEAD
git -C engine/src/flutter/third_party/freetype2 rev-parse HEAD
python engine/src/flutter/tools/wsc_font_rendering_patches/apply_patches.py
```

The sync helper writes the standard `.gclient` configuration and runs the scripts
listed in `DEPS`, called hooks, that reset and apply the patches. Add `--web` when
preparing a Web build. Run this only in the separate update or build folder,
not a workspace with custom dependency
settings or unrelated edits. Windows Git needs long-path support, as described
in the [agent setup](../../DEPLOYMENT.MD#1-prepare-the-agents).

Check that both HEADs match `DEPS` and the expected revisions. The final helper
invocation should report that the selected patches are already applied.
Then repeat the same sync command, keeping `--web` if used, to check that setup
can undo and reapply the patches on an already patched checkout.

If a hook fails, inspect the nested state before retrying. In particular,
`Preserving modified patch-created file` can mean the existing file belongs to
an earlier version of a patch. Repeating sync with the new patch will not fix
that mismatch. Preserve edits and use the old-patch reset or fresh update folder
described in step 2. A partial sync is not a completed check.

## 4. Commit and check the updated patches

Commit the patch files and helper edits in the Flutter update branch, then
update its engine pin. Return to the
[checks and tests](updating.md#5-run-the-checks-and-tests) and supply both dependency paths.
Use the synced checkouts, whose HEADs are the pinned dependency revisions, not
the temporary library checkouts containing your temporary porting commits.

Before accepting the updated patches, check that they apply, that dependency
setup handles them correctly, that the engine builds, and that rendering still
matches the expected result.
