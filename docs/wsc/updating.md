# Update to a new Flutter version

Use this guide to carry the fork's patches to a newer Flutter **stable** or
**beta** release, or to **main**. You can skip intermediate releases.

The Git part of an update is one command. For example, to take the patches from
your current branch to Flutter 3.44.9:

```sh
python dev/bots/wsc_rebase.py rebase --tip HEAD --new-base 3.44.9
```

The helper finds the old Flutter base, creates an update branch, and rebases the
patches **in your current folder**. It leaves the original branch and release
tags in place. If Git needs help with a patch, it stops for you to resolve it.

After rebasing, you still need to check the dependency patches, build the SDK,
and test rendering. Follow these steps:

1. [Prepare your checkout](#1-prepare-your-checkout).
2. [Rebase the patches](#2-rebase-the-patches).
3. [Check Skia and FreeType patches](#3-check-skia-and-freetype-patches).
4. [Update the engine version used for downloads](#4-update-the-engine-version-used-for-downloads).
5. [Run the checks and tests](#5-run-the-checks-and-tests).
6. [Build and test the updated SDKs](#6-build-and-test-the-updated-sdks).
7. [Release the tested version](#7-release-the-tested-version).

## 1. Prepare your checkout

Use Git 2.45 or newer, Python 3.10 or newer, and a checkout with full Git history.
Run the commands from the repository root. They work in PowerShell and Bash.

Start on the fork branch containing the patches and fixes you want to keep.
Check where you are and whether you have unfinished work:

```sh
git branch --show-current
git status
```

The helper refuses to start with uncommitted changes, untracked files, or an
unfinished merge, rebase, or cherry-pick. Commit changes you want to include,
or save unfinished work elsewhere. It does not stash or delete files for you.
If you want to leave your current folder as it is, use the
[optional separate folder](#use-a-separate-folder-if-you-want-one) below.

Check your remotes:

```sh
git remote -v
```

`origin` should be this fork. `upstream` must be the official Flutter repository.
If `upstream` is missing, add it once:

```sh
git remote add upstream https://github.com/flutter/flutter.git
```

The helper fetches official Flutter history itself. If you want to start from
a fork branch or release you do not have locally yet, fetch the fork too:

```sh
git fetch origin --tags
```

Fetching does not update your current branch. Choose the fork tip explicitly
in the next step if the changes you need are on another branch.

## 2. Rebase the patches

For an update from your current fork branch to stable Flutter 3.44.9, run:

```sh
python dev/bots/wsc_rebase.py rebase --tip HEAD --new-base 3.44.9
```

`HEAD` means your current commit. This includes fixes made since the last fork
release, as long as they are committed on this branch.

You can also select a particular fork release or branch. For example:

```sh
python dev/bots/wsc_rebase.py rebase --tip wsc-3.44.4-r1 --new-base 3.44.9
python dev/bots/wsc_rebase.py rebase --tip origin/wsc-main-3.44.4 --new-base 3.44.9
```

These are alternatives: run **one** command using the fork tip you want to keep.
Choosing an older release also brings its older helper scripts and build setup;
use the current fork branch when you need the tooling fixes made since that release.

For the latest official beta or main commit, use:

```sh
python dev/bots/wsc_rebase.py rebase --tip HEAD --new-base upstream/beta
python dev/bots/wsc_rebase.py rebase --tip HEAD --new-base upstream/main
```

Again, choose one. A beta release tag works too. Both inputs accept full commit
IDs; `--tip` also accepts local tags and branch names, while `--new-base` names
are looked up in the official upstream repository. The helper fixes both inputs
to commit IDs before starting, so the update uses the versions it prints.

The helper:

1. Fetches official upstream branches and tags.
2. Walks back from the fork tip to the first commit in official upstream history.
   Everything after that is the fork's patch sequence. No old-base argument is needed.
3. Creates and switches to a new local branch, such as `flutter-update-3.44.9`.
   If that name exists, it adds a number. For branch or commit targets, the name
   includes the target commit ID instead of a version.
4. Runs Git rebase in the current folder. It does not download engine dependencies
   or clean build outputs.

When it prints `Rebase completed`, stay in this folder and review the result.
The output includes a `git range-diff` command with the exact old and new commit
IDs. Run that command to compare the original patches with the rebased patches.
Check any changes made while resolving conflicts, and whether Flutter has
replaced any of our workarounds.

### If Git stops for a conflict

Inspect the files and the patch Git is applying:

```sh
git status
git diff
git rebase --show-current-patch
```

Edit each conflicting file to keep the intended behavior. Stage the files you
resolved and continue. For example, if the conflict was in `DEPS`:

```sh
git add DEPS
git rebase --continue
```

Use the actual filenames shown by `git status`. Repeat if another patch conflicts.
If Git opens an editor for the commit message, save and close it to continue.

If a patch becomes empty because Flutter already includes the change, inspect
it before skipping it:

```sh
git rebase --show-current-patch
git rebase --skip
```

To abandon the rebase:

```sh
git rebase --abort
```

This returns the update branch to the original fork tip. Your original branch
and tags are still unchanged. Do not rerun the helper while a rebase is paused;
use Git's continue, skip, or abort commands first.

## 3. Check Skia and FreeType patches

Flutter downloads the Skia and FreeType libraries during engine dependency
setup. Our changes to those libraries are stored as patch files in this
repository. Rebasing carries those files forward, but does not apply or test
them against the new library versions.

Prepare and check them with one command:

```sh
python dev/bots/wsc_rebase.py dependencies
```

This reads the library versions and paths from `DEPS`, checks all patches,
updates their recorded revisions, and runs `gclient sync`. Add `--web` to include
the Web engine toolchain. You need depot_tools and the
[engine development prerequisites](../engine/contributing/Setting-up-the-Engine-development-environment.md).

If a patch conflicts, the helper prints a repair folder and instructions for
saving the fix. Follow [fix a dependency patch](dependency-patches.md#if-a-patch-fails),
then rerun the same command. Existing library edits that do not match the
recorded patches are preserved and stop setup.

When it prints `DEPENDENCIES READY`, review and commit any resulting changes:

```sh
git diff -- engine/src/flutter/tools/wsc_font_rendering_patches
git add -A engine/src/flutter/tools/wsc_font_rendering_patches
git commit -m "Port rendering patches to Flutter 3.44.9"
```

Skip the commit if no files changed. The [dependency guide](dependency-patches.md)
explains the checks and how to handle existing library edits.

## 4. Update the engine version used for downloads

`bin/internal/engine.version` tells the SDK which compiled engine files to
download. This value is the **engine pin**. It must match the engine code and
dependency patches you will build.

After committing your changes, run:

```sh
python dev/bots/engine_identity.py
```

Replace the contents of `bin/internal/engine.version` with the printed hash,
then commit the file if it changed:

```sh
git add bin/internal/engine.version
git commit -m "Update engine pin for Flutter 3.44.9"
```

If Git says the file is ignored, use `git add -f bin/internal/engine.version`.
Recheck the pin after any further engine or dependency-patch changes. The
[engine-pin reference](releases.md#engine-identity) explains validation before CI.

## 5. Run the checks and tests

Once your changes are committed and `git status` is clean, run:

```sh
python dev/bots/wsc_rebase.py verify
```

The helper remembers the new base for the update branch. It checks the patch
history, whitespace, engine pin, SDK version settings, and focused Python tests.
It also finds Skia and FreeType automatically, checks their versions against
`DEPS`, and tests the patch files. Missing or stale libraries fail the check
and tell you to run `dependencies`; no directory arguments are needed.

A successful check prints `SOURCE CHECKS PASSED, NOT RELEASE APPROVAL`. This does
not mean an engine was built or rendering was tested.

Run the packaging and Flutter version tests with a compatible SDK:

```sh
dart pub get --directory dev/bots
dart test dev/bots/test/prepare_package_test.dart
cd packages/flutter_tools
flutter test test/general.shard/version_test.dart
cd ../..
```

If Flutter cannot start because the new engine download does not exist yet,
use an available compatible SDK for these tests, or record them as pending
until Jenkins publishes the new engine. Keep the new pin. See
[mirror selection](artifacts.md#packaging-and-mirror-selection) to use the
build's download server afterward.

Run tests for rendering or diagnostic code you changed, and use the
[update checklist](releases.md#rebase-audit-checklist) to review the affected areas.

## 6. Build and test the updated SDKs

Before pushing the update branch, run the
[engine and SDK identity check](releases.md#engine-identity). Check Jenkins'
polling settings too: pushing may start a build. Follow your team's usual
review process and [run the integration build](../../DEPLOYMENT.MD#4-run-the-integration-build).

Select the Jenkins job for your update branch and set `RELEASE_BRANCH` to
`stable`, `beta`, or `main`. For example, the `flutter-update-3.44.9` job with
`RELEASE_BRANCH=stable` builds your update and labels the packaged SDK as stable.
It does not move the fork's stable branch. That branch must already exist,
because the packager clones it before selecting the build commit.

Check that the [configured rendering baseline](rendering-regression.md#configure-once-then-version-the-defaults)
is the previous fork release you want to compare against. Keep it fixed while
investigating differences. Keep the previous version's build workspace and SDKs
available while testing the update.

Build the required SDKs and [test the extracted SDKs](../../DEPLOYMENT.MD#5-accept-the-sdks-before-distribution).
Jenkins compares rendering on Windows and Web; macOS, Android, and iOS need
separate testing. Disabled or failed comparisons do not establish rendering
correctness. For local rendering comparisons, follow the
[FRT README](https://bitbucket.org/schoolcraftteam/font_rendering_tester/src/master/README.md).
If you changed diagnostics, check them enabled and disabled, including the
performance cost when disabled.

Record the commits printed by the helper, engine ID, test results, build and SDK
links, and rendering comparisons in the update PR. Distinguish completed checks
from checks still pending.

## 7. Release the tested version

Follow [release the SDK](releases.md#release-procedure) to tag and build the
release, for example `wsc-3.44.9-r1`. Then
[update the release channel](releases.md#update-a-release-channel) to point
`stable`, `beta`, or `main` at the tested release. The helper does not publish
anything or move these channel branches.

The update branch is temporary. Once the release tag and channel point to the
accepted commit and no build still needs the update branch, it can be deleted.
The release tag preserves the release; you do not need a permanent branch for
every Flutter patch version. Follow the [branch cleanup commands](releases.md#remove-the-temporary-update-branch).

## Optional helper settings

- Add `--dry-run` to fetch upstream history and print the plan without changing
  working files or creating an update branch.
- Add `--branch flutter-update-3.44.9-test` to choose the update branch name.
- Add `--upstream flutter-official` if your official remote has that name instead
  of `upstream`.
- On an update branch created elsewhere, `verify` has no locally saved base. Use
  `verify --new-base` followed by the new upstream commit ID from the update record.

For example, preview an update:

```sh
python dev/bots/wsc_rebase.py rebase --tip HEAD --new-base 3.44.9 --dry-run
```

### Use a separate folder if you want one

To keep your current working files and outputs in place, create another Git
worktree yourself. Choose an unused folder name:

```sh
git worktree add --detach ../flutter-update HEAD
cd ../flutter-update
python dev/bots/wsc_rebase.py rebase --tip HEAD --new-base 3.44.9
```

The new folder starts from your current **committed** code. Uncommitted work
stays in the original folder. The helper uses this new folder directly.

### Test the helper itself

If you change the helper, run:

```sh
python -B -m unittest discover -s dev/bots -p "test_wsc*.py"
python -B -m unittest discover -s dev/bots -p test_sync_engine_deps.py
```

The tests use temporary repositories with a local simulated upstream. They
check base detection, rebasing, conflicts, file preservation, and verification.
They do not build Flutter. The `verify` command runs code from its checkout,
so use a checkout you trust.
