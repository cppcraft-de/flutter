# Port Skia and FreeType patches

Use this when an upstream update changes Skia or FreeType, or a WSC patch no
longer applies. Work in the isolated candidate from
[Updating the WSC fork](updating.md). Keep existing development and CI dependency
trees intact.

The files under
[wsc_font_rendering_patches](../../engine/src/flutter/tools/wsc_font_rendering_patches/)
are the source of truth. Changes made only inside a nested dependency checkout
will not be included in a release.

## 1. Check the new dependency revisions

Compare the candidate's [DEPS](../../DEPS) with
[apply_patches.py](../../engine/src/flutter/tools/wsc_font_rendering_patches/apply_patches.py):

- Skia: `skia_revision` in `DEPS` and `EXPECTED_SKIA_REVISION` in the helper.
- FreeType: the revision of `engine/src/flutter/third_party/freetype2` in
  `DEPS` and `EXPECTED_FREETYPE_REVISION` in the helper.

Use the new upstream dependency revisions. Port and check the patches before
updating the helper's expected revisions. Do not restore old dependency pins
just to make the patch check pass.

## 2. Fix a patch in a separate checkout

For each changed dependency, create a scratch checkout outside the candidate.
Use its repository URL and revision from the candidate's `DEPS`. For example,
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

1. Commit the successfully applied earlier patches in the **scratch repository**.
   This gives you the exact starting state for the failing patch.
2. Read the failing patch and the changed upstream code. Implement the intended
   WSC behavior on the new source, or remove the patch if upstream now supplies
   that behavior. Review that decision with the maintainer.
3. Stage only the files belonging to this patch, including any new files. Review
   the staged diff, then write it to the corresponding patch file in the candidate:

   ```sh
   git -C ../wsc-skia-port add PATH_TO_CHANGED_FILE
   git -C ../wsc-skia-port diff --cached
   git -C ../wsc-skia-port diff --cached --binary --output=ABSOLUTE_PATH_TO_CANDIDATE_PATCH
   ```

4. Commit this patch's changes in the scratch repository before porting the next
   one. Keep each patch's diff separate; do not include the accumulated stack.
5. Once the stack works, update the helper's expected revisions in the candidate.
   Check `GROUP_MARKERS` if the patched code moved or changed. Those markers let
   the hook recognize an applied group; they do not prove rendering correctness.

Use `--output` to write patch bytes directly. Shell redirection can change the
encoding on Windows. Keep the resulting patch files and helper edits in the
candidate; scratch commits are not release inputs.

## 3. Check the real dependency hooks

From the candidate root, inspect any existing nested changes before syncing:

```sh
git -C engine/src/flutter/third_party/skia status --short
git -C engine/src/flutter/third_party/freetype2 status --short
```

Skip these status commands if the dependencies have not been downloaded yet.
An outer `git status` does not show all nested edits. Save intentional edits as
patches first: the pre-sync hook resets WSC patch-owned changes.

With depot_tools and the platform's
[engine prerequisites](../engine/contributing/Setting-up-the-Engine-development-environment.md)
available, run:

```sh
python dev/bots/sync_engine_deps.py --mode true
git -C engine/src/flutter/third_party/skia rev-parse HEAD
git -C engine/src/flutter/third_party/freetype2 rev-parse HEAD
python engine/src/flutter/tools/wsc_font_rendering_patches/apply_patches.py
```

The sync helper writes the standard `.gclient` configuration and runs the DEPS
hooks. Use `--web` as well when preparing a Web build. Run this only in the
isolated candidate/build workspace, not a workspace with custom dependency
settings or unrelated edits. Windows Git needs long-path support, as described
in the [agent setup](../../DEPLOYMENT.MD#1-prepare-the-agents).

Check that both HEADs match `DEPS` and the expected revisions. The final helper
invocation should report that the selected patches are already applied.
If sync failed at a hook, fix the patch and rerun sync; a partial sync is not a
completed check.

## 4. Commit and verify the candidate

Commit the patch files and helper edits in the outer candidate repository, then
update its engine pin. Return to the
[source checks](updating.md#5-run-source-checks) and supply both dependency paths.
Use the synced checkouts, whose HEADs are the pinned dependency revisions, not
the scratch repositories containing your temporary porting commits.

The object-based patch check, real hook checks, engine compilation, and rendering
comparison are separate checks. Complete all of them before accepting the port.
