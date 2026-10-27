# Update to a new Flutter version

Use this guide to take the fork's patches to a newer **stable** or **beta**
release, or to a chosen commit on Flutter's **main** branch. The aim is to keep
our rendering behavior while picking up Flutter's changes. You can skip
intermediate releases.

Most of the Git work is handled by [wsc_rebase.py](../../dev/bots/wsc_rebase.py).
You give it the fork version and the old and new Flutter versions. It creates
an update branch in a new folder and applies the fork's commits there. If a
patch conflicts with the new Flutter code, it stops so you can fix that conflict.

The script does not complete the whole update: you still need to check the
Skia and FreeType patches, update the engine version, and build and test the SDK.
The steps below take you through that process.

1. [Choose the versions to use](#1-choose-the-versions-to-use).
2. [Apply the patches in a new folder](#2-apply-the-patches-in-a-new-folder).
3. [Check Skia and FreeType patches](#3-check-skia-and-freetype-patches).
4. [Update the engine version used for downloads](#4-update-the-engine-version-used-for-downloads).
5. [Run the checks and tests](#5-run-the-checks-and-tests).
6. [Build and test the updated SDKs](#6-build-and-test-the-updated-sdks).
7. [Release the tested version](#7-release-the-tested-version).

## Before you start

You need Git, Python 3.10 or newer, and a checkout of this fork with full Git
history. The examples below use ordinary commands that work in PowerShell and
Bash. Run each command from the repository root unless a step says to change
folders.

### Start from a clean folder

**The folder you run the helper from must already be clean.** The helper checks
it, but does not save, stash, or delete files. The new folder it creates later
is where it applies the patches; creating that folder does not bypass this check.

Check your current folder:

```sh
git status --short
```

If there is no output and no merge, rebase, or cherry-pick is in progress,
continue to step 1. If you have changes, commit them if they belong in the fork.
To leave unfinished work and local files where they are, create a separate clean
folder from your current commit instead:

```sh
git worktree add --detach ../flutter-update-tools HEAD
cd ../flutter-update-tools
```

Choose an unused folder name. This is a Git *worktree*: another working folder
that shares the same repository history. Your uncommitted edits stay in the
original folder and are not included. Run the remaining commands from this
clean folder. In step 2, the helper creates a second folder for the updated
Flutter code. Neither step removes your existing build outputs.

You do not need engine dependencies yet. Step 3 explains when to download them.

## 1. Choose the versions to use

Start with the **latest fork release** and choose the official Flutter version
you want to update to. If you need fixes committed since that fork release,
use the branch or commit containing those fixes instead.

Also choose the **previous fork release to compare rendering against**. Its
built SDK will be the comparison baseline. Keep that baseline fixed while
investigating differences. Jenkins has a configured baseline; check that it is
the one you intend to use when you reach step 6.

### Fetch the Git history

Check the repository addresses:

```sh
git remote -v
```

`origin` should be this fork on Bitbucket. `upstream` should be the official
Flutter repository. If `upstream` is missing, add it:

```sh
git remote add upstream https://github.com/flutter/flutter.git
```

Fetch both repositories:

```sh
git fetch origin --tags
git fetch upstream --tags
```

### Find where the fork's patches start

The commands below use an illustrative update from fork release
`wsc-3.44.3-r1` to official Flutter `3.44.4`. Replace these example names with
the releases you selected; they are not a list of available releases.

The helper currently requires `--old-base`: the official Flutter commit just
before the fork's patches. It reapplies every commit after that point up to
the selected fork version. It does not calculate this starting point itself.

For the usual update, where the new Flutter version continues the old version's
history, find that point with:

```sh
git merge-base --all wsc-3.44.3-r1 3.44.4
```

For a fork with a straight sequence of patches on top of Flutter, this returns
the Flutter commit it was based on. To see any release tag on that commit, replace
`BASE_COMMIT` with the returned commit ID:

```sh
git tag --points-at BASE_COMMIT
```

In this example, the official tag is `3.44.3`. Use that tag as `--old-base`, or
use the commit ID directly if there is no tag. Check the commits after it:

```sh
git log --reverse --oneline 3.44.3..wsc-3.44.3-r1
```

The list should contain the fork's patches, including its build and packaging
changes. If it includes official Flutter changes, or the common-ancestor
command returned more than one commit, inspect the history before proceeding:

```sh
git log --first-parent --decorate --oneline wsc-3.44.3-r1
```

Walking back through that history can identify the original Flutter commit.
When switching channels, the target may have branched off before that commit;
in that case their common ancestor is too old to use as the patch starting
point. Use the actual starting commit from the fork's history. The helper
requires a straight sequence of patches and rejects merge commits in that range.

### For beta or main

The same procedure applies. For beta, replace the target `3.44.4` with your chosen
official beta tag. For main, obtain the current official commit:

```sh
git rev-parse upstream/main
```

Use that full commit ID as the target in the common-ancestor command and the
steps below, so a later fetch
cannot change which version you are updating to. If you selected a fork branch
instead of a release tag, use `git rev-parse BRANCH_NAME` to fix that selection
to a commit too. Choose an update branch and folder name that describes your
update, for example `flutter-update-main-2026-10-27`.

You do not need the fork's mirrored `upstream/*` branches for this procedure.
See [how the mirrored branches are named](upstream-sync.md#understand-the-branch-names)
if you encounter names such as `origin/upstream/stable`.

## 2. Apply the patches in a new folder

Preview the update with one command. Substitute your versions and choose unused
branch and folder names:

```sh
python dev/bots/wsc_rebase.py prepare --old-base 3.44.3 --tip wsc-3.44.3-r1 --new-base 3.44.4 --branch flutter-update-3.44.4 --worktree ../flutter-update-3.44.4
```

Here is what the options mean:

| Option | What to supply |
| --- | --- |
| `--old-base` | The official Flutter commit or tag just before the fork's patches. |
| `--tip` | The fork release, branch, or commit containing the patches to carry forward. |
| `--new-base` | The official Flutter release tag or commit you are updating to. |
| `--branch` | A new local branch name for the update. |
| `--worktree` | A new folder for the updated code, outside the folder you are running from. The helper creates it. |

The preview changes nothing. It prints the resolved commit IDs, the patches to
apply, and the destination. Check that these match your choices. Then run the
same command with `--apply`:

```sh
python dev/bots/wsc_rebase.py prepare --old-base 3.44.3 --tip wsc-3.44.3-r1 --new-base 3.44.4 --branch flutter-update-3.44.4 --worktree ../flutter-update-3.44.4 --apply
```

This creates the branch and folder, then runs `git cherry-pick` to apply the
commits in order. It does not ask interactive questions. Git may stop for a
conflict, as explained below.

Read the result before changing folders:

- `Replay completed`: the commits applied. Continue in the new folder.
- `Replay stopped. Candidate preserved at ...`: a commit needs attention.
  Here, "candidate" means your update branch. Enter the printed folder and
  resolve the conflict as described below.
- If preparation failed before creating the folder, stay where you are and fix
  the reported problem.

For example, running from `D:\flutter` or `D:\flutter-update-tools` creates
`D:\flutter-update-3.44.4`. Once the folder exists, enter it:

```sh
cd ../flutter-update-3.44.4
```

### Resolve conflicts

If a cherry-pick stopped, inspect the conflicting files and the commit being
applied:

```sh
git status
git diff
git show CHERRY_PICK_HEAD
```

Edit the conflicting files, review the result, and continue:

```sh
git add PATH_TO_RESOLVED_FILE
git cherry-pick --continue
```

If Flutter already includes a patch's change, the cherry-pick may be empty.
Check that the change really is present before using `git cherry-pick --skip`.
To abandon the attempt, run `git cherry-pick --abort` in the new folder. The
branch and folder remain, so use new names for another attempt. Do not rerun
`prepare` while a cherry-pick is stopped.

### Review the applied patches

Use the same versions you chose in step 1:

```sh
git range-diff 3.44.3..wsc-3.44.3-r1 3.44.4..HEAD
git diff --stat 3.44.4..HEAD
git diff 3.44.4..HEAD
```

`range-diff` compares the old and new patch sequences. Check whether Flutter
has replaced any workarounds, and review changes to the engine build, startup
scripts, packaging, and dependency patches. A patch can apply without conflicts
and still need changes to work correctly.

Resolve any conflict in `bin/internal/engine.version` during this step; you
will calculate its final value in step 4.

## 3. Check Skia and FreeType patches

Flutter downloads the Skia and FreeType libraries during engine dependency
setup. Our changes to those libraries are stored as patch files in this
repository. Step 2 carries those patch files into the update branch, but does
not download the libraries or check whether the patches still apply to them.

Follow [Port Skia and FreeType patches](dependency-patches.md) to check those
versions, fix patches that no longer apply, and test the scripts that apply
them during dependency setup. Commit the resulting files in the update branch.

You can run the checks in step 5 before downloading dependencies, but record
the dependency checks as pending. After changing dependencies or patch files,
do not use `SYNC_ENGINE_DEPS=false` to skip their setup.

## 4. Update the engine version used for downloads

The SDK reads `bin/internal/engine.version` to choose which compiled engine
files to download. This value is the **engine pin**. It must match the engine
code and dependency patches you are about to build.

Commit those changes first, then follow [update the engine pin](releases.md#engine-identity).
The procedure calculates the engine ID with `dev/bots/engine_identity.py`,
writes it to `bin/internal/engine.version`, and validates the committed result.

If the new Flutter version ignores that file and it is not yet tracked, use
`git add -f bin/internal/engine.version`. Recheck the pin after any later engine
or dependency-patch change. Changes only to the Flutter framework, or to the
pin itself, do not change the calculated engine ID.

This step prepares an SDK for distribution. When working on the engine locally
without distributing an SDK, follow [local engine development](engine-identity.md#local-engine-development)
instead; that workflow keeps an available engine version for starting the tools.

## 5. Run the checks and tests

Once the changes are committed and the update folder is clean, run the helper's
checks. Replace `3.44.4` with the target version or commit you chose in step 1:

```sh
python dev/bots/wsc_rebase.py verify --new-base 3.44.4
```

If you have prepared the Skia and FreeType repositories, include their paths:

```sh
python dev/bots/wsc_rebase.py verify --new-base 3.44.4 --skia-dir PATH_TO_SKIA --freetype-dir PATH_TO_FREETYPE
```

The helper checks the Git history, whitespace, engine pin, SDK version settings,
and focused Python tests. With the dependency paths, it also checks that the
patches apply to their recorded revisions, without editing those working folders.
It prints `SOURCE CHECKS PASSED, NOT RELEASE APPROVAL` on success. This means
the code checks passed; the helper has not built an engine or tested rendering.

Next, run the packaging and Flutter version tests with a compatible SDK:

```sh
dart pub get --directory dev/bots
dart test dev/bots/test/prepare_package_test.dart
cd packages/flutter_tools
flutter test test/general.shard/version_test.dart
cd ../..
```

**If Flutter cannot start because an engine download is missing:** the new pin
may not have been built and uploaded yet. Use an available compatible SDK for
these tests, or record them as pending until Jenkins publishes the new engine.
Keep the new pin. Once it is available, select the build's download server using
[mirror selection](artifacts.md#packaging-and-mirror-selection); a checkout does
not automatically use Jenkins' download URL.

Run tests for any rendering or diagnostic code you changed, and work through
the [update checklist](releases.md#rebase-audit-checklist).

## 6. Build and test the updated SDKs

Run the [engine and SDK identity check](releases.md#engine-identity) on the final
committed update. Before pushing, check Jenkins' polling and branch-discovery
settings: pushing may start a build. Follow your team's usual review process and
[Run the integration build](../../DEPLOYMENT.MD#4-run-the-integration-build).

Select the Jenkins job for your update branch. Set `RELEASE_BRANCH` to the
channel you are preparing: `stable`, `beta`, or `main`.

For example, building `flutter-update-3.44.4` with `RELEASE_BRANCH=stable` builds
your update branch and labels the packaged SDK as stable. It does not build
official Flutter stable or move the fork's stable branch. The fork must already
have a branch named `stable`, because the packager clones it before checking out
the chosen build commit.

Before building, check that the [configured rendering baseline](rendering-regression.md#configure-once-then-version-the-defaults)
is the previous fork release you chose in step 1. Use a separate build workspace
for the updated version and keep the previous version's outputs. Build the
required Windows and macOS SDKs, then follow
[test the extracted SDKs](../../DEPLOYMENT.MD#5-accept-the-sdks-before-distribution).

Jenkins currently compares rendering on Windows and Web. Review those results;
disabled or failed comparisons do not establish that rendering is correct.
macOS, Android, and iOS need separate testing. See [rendering results and coverage](rendering-regression.md#outcomes-evidence-and-acceptance).
For running the font rendering tester yourself, use the
[FRT README](https://bitbucket.org/schoolcraftteam/font_rendering_tester/src/master/README.md).
If you changed diagnostics, check them both enabled and disabled, including the
performance cost when disabled.

Record the fork commit, engine ID, previous and new Flutter commits, test results,
build and SDK links, rendering comparisons, and any remaining issues in the update PR.
Make clear which stages actually passed: code checks, compilation, packaging,
uploads, and application/rendering tests.

## 7. Release the tested version

Follow [release the SDK](releases.md#release-procedure) to tag the accepted commit,
build and test the release SDKs, and share the approved downloads. Then follow
[update a release channel](releases.md#update-a-release-channel) to move the
fork's main, beta, or stable branch. Neither the helper nor a passing Jenkins
build updates those branches for you.

## Test the update helper itself

If you change the helper, run its tests:

```sh
python -B -m unittest discover -s dev/bots -p test_wsc_rebase.py
```

They use temporary Git repositories to check patch replay, conflict handling,
input validation, and dependency-patch checks. They do not build Flutter.
The `verify` command runs scripts and tests from the selected checkout, so use
a checkout you trust.
