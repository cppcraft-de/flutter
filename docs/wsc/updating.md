# Update to a new Flutter version

Use this guide to take the fork's patches to a newer **stable** or **beta**
release, or to a chosen commit on Flutter's **main** branch. The aim is to keep
our rendering behavior while picking up Flutter's changes. You can skip
intermediate releases.

The update helper creates a branch and a separate working folder, called a Git
*worktree*. It applies the fork's commits to the chosen Flutter version using
`git cherry-pick`. This is the patch replay used here to rebase the fork. Your
existing folder and build outputs stay in place.

The new branch is a **candidate**: an updated version to build and test before
releasing it. Applying the patches successfully is only the first part of the
update; you still need to check that the SDK builds and renders correctly.

1. [Choose the versions to use](#1-choose-the-versions-to-use).
2. [Apply the patches in a new folder](#2-apply-the-patches-in-a-new-folder).
3. [Check Skia and FreeType patches](#3-check-skia-and-freetype-patches).
4. [Update the engine version used for downloads](#4-update-the-engine-version-used-for-downloads).
5. [Run the checks and tests](#5-run-the-checks-and-tests).
6. [Build and test the updated SDKs](#6-build-and-test-the-updated-sdks).
7. [Release the tested version](#7-release-the-tested-version).

## Before you start

Use a checkout with full Git history and Python 3.10 or newer. The helper
requires a clean working folder, including no untracked files. Commit or save
unfinished work elsewhere, and finish any pending merge or cherry-pick first.
Do not remove local work or build outputs just to satisfy this check.

You do not need to download or build the engine to apply the commits. The later
dependency and build steps need the [engine development setup](../engine/contributing/Setting-up-the-Engine-development-environment.md)
and enough disk space for another build folder.

Agree with the release reviewer which maintained version to start from, which
Flutter version to use, and which SDK to compare rendering against. Keep that
comparison baseline fixed while investigating differences.

## 1. Choose the versions to use

Run these commands in your existing checkout. Check the repository addresses:

- `origin` should be this fork on Bitbucket.
- `upstream` should be the official repository, `https://github.com/flutter/flutter.git`.

```sh
git remote -v
```

If `upstream` is missing, add it:

```sh
git remote add upstream https://github.com/flutter/flutter.git
```

Fetch both repositories so their branches and tags are available locally:

```sh
git fetch origin --tags
git fetch upstream --tags
```

You need three commits to describe the update:

| Choice | Meaning | Example |
| --- | --- | --- |
| Previous Flutter version | The official Flutter commit that the current patches were built on. Find it in the last update PR or release record. | Tag `3.44.3` |
| Fork version to carry forward | The branch or tag containing the patches and fixes you want to keep. Use the maintained branch if it has fixes made after the last release. | Tag `wsc-3.44.3-r1` |
| New Flutter version | The official Flutter commit to apply those patches to. | Tag `3.44.4` |

For a stable or beta update, choose the corresponding Flutter release tag.
For main, choose a commit on `upstream/main`, your local copy of the official
main branch. When moving between channels for the first time, choose the
maintained fork branch that has the fixes you need. An older experimental branch
may be missing later fixes.

If the previous Flutter version was not recorded, establish it from the Git
history with a maintainer before continuing. Git's common-ancestor calculation
alone does not tell you which commits were intended as the fork's patches.

### Example: update stable

The example below takes the patches in `wsc-3.44.3-r1`, based on Flutter
`3.44.3`, and applies them to Flutter `3.44.4`. These are example version names;
replace them with the versions you chose.

The commands use PowerShell. Each `rev-parse` resolves a tag to its full commit
ID, so the selection stays fixed even if a branch moves later. Stop if one of
these commands fails.

```powershell
$oldBase = git rev-parse 'refs/tags/3.44.3^{commit}'
$forkTip = git rev-parse 'refs/tags/wsc-3.44.3-r1^{commit}'
$newBase = git rev-parse 'refs/tags/3.44.4^{commit}'
$updateBranch = 'flutter-update-3.44.4'
$updateFolder = '../flutter-update-3.44.4'
```

Here, `$oldBase` and `$newBase` are the previous and new Flutter commits.
`$forkTip` is the selected fork commit; *tip* means the end of a branch or commit
sequence. The helper's `--tip` option takes this value.

The branch and folder names must be unused. If your current checkout is
`D:\flutter`, the example creates `D:\flutter-update-3.44.4`. The helper creates
this folder for you.

For beta, replace the new tag with your chosen beta tag, such as
`3.45.0-0.1.pre`. For main, use:

```powershell
$newBase = git rev-parse 'refs/remotes/upstream/main^{commit}'
```

Choose a branch and folder name that identifies that update, for example by
including the date. `$oldBase` always describes the fork version you are taking
patches from, whichever channel you are updating to.

If you use Bash, assign commit IDs with `oldBase=$(git rev-parse 'REF^{commit}')`
and names with `updateBranch='NAME'`. Use the same variable names as above for
the remaining commands.

Review what you are carrying forward:

```sh
git log --reverse --oneline "$oldBase..$forkTip"
git diff --stat "$oldBase..$forkTip"
git diff "$oldBase..$forkTip"
```

This range should contain the fork's patches after the previous Flutter commit,
including its build and packaging changes. The helper requires a nonempty,
linear sequence of commits and rejects merge commits. It cannot tell whether
you selected unrelated Flutter history by mistake. Resolve an unsuitable range
before continuing; do not rewrite published history just to pass the check.
Record all three commit IDs in the update PR.

You do not need the fork's mirrored `upstream/*` branches for this procedure.
Those are copies of official Flutter branches stored on Bitbucket. See
[how the mirrored branches are named](upstream-sync.md#understand-the-branch-names)
if you encounter names such as `origin/upstream/stable`.

## 2. Apply the patches in a new folder

First ask the helper to show what it would do. This command changes nothing:

```sh
python dev/bots/wsc_rebase.py prepare --old-base "$oldBase" --tip "$forkTip" --new-base "$newBase" --branch "$updateBranch" --worktree "$updateFolder"
```

Check the listed commits, branch name, and destination folder. Once the plan is
reviewed, run it with `--apply`:

```sh
python dev/bots/wsc_rebase.py prepare --old-base "$oldBase" --tip "$forkTip" --new-base "$newBase" --branch "$updateBranch" --worktree "$updateFolder" --apply
```

Read the result before changing folders:

- `Replay completed`: the commits applied. Continue in the new folder.
- `Replay stopped. Candidate preserved at ...`: a commit needs attention.
  Enter the printed folder and resolve the conflict as described below.
- If preparation failed before creating the folder, stay in your original
  checkout and fix the reported problem.

After confirming that the new folder exists:

```sh
cd "$updateFolder"
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

```sh
git range-diff "$oldBase..$forkTip" "$newBase..HEAD"
git diff --stat "$newBase..HEAD"
git diff "$newBase..HEAD"
```

`range-diff` compares the old and new patch sequences. Check whether Flutter
has replaced any workarounds, and review changes to the engine build, startup
scripts, packaging, and dependency patches. A patch can apply without conflicts
and still need changes to work correctly.

Resolve any conflict in `bin/internal/engine.version` during this step; you
will calculate its final value in step 4.

## 3. Check Skia and FreeType patches

Some rendering changes are stored as patch files for Skia and FreeType, which
Flutter downloads separately. Applying the fork's commits copies these files;
it does not apply or test them against the new dependency versions.

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

Once the changes are committed and the update folder is clean, run:

```sh
python dev/bots/wsc_rebase.py verify --new-base "$newBase"
```

If you have prepared the Skia and FreeType repositories, include their paths:

```sh
python dev/bots/wsc_rebase.py verify --new-base "$newBase" --skia-dir PATH_TO_SKIA --freetype-dir PATH_TO_FREETYPE
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
settings: pushing may start a build. Get approval to push and build, then follow
[Run the integration build](../../DEPLOYMENT.MD#4-run-the-integration-build).

Select the Jenkins job for your update branch. Set `RELEASE_BRANCH` to the
channel you are preparing: `stable`, `beta`, or `main`.

For example, building `flutter-update-3.44.4` with `RELEASE_BRANCH=stable` builds
your update branch and labels the packaged SDK as stable. It does not build
official Flutter stable or move the fork's stable branch. The fork must already
have a branch named `stable`, because the packager clones it before checking out
the chosen build commit.

Use a separate build workspace for the updated version and keep the previous
version's outputs. Build the required Windows and macOS SDKs, then follow
[test the extracted SDKs](../../DEPLOYMENT.MD#5-accept-the-sdks-before-distribution).

Jenkins currently compares rendering on Windows and Web. Review those results;
disabled or failed comparisons do not establish that rendering is correct.
macOS, Android, and iOS need separate testing. See [rendering results and coverage](rendering-regression.md#outcomes-evidence-and-acceptance).
For running the font rendering tester yourself, use the
[FRT README](https://bitbucket.org/schoolcraftteam/font_rendering_tester/src/master/README.md).
If you changed diagnostics, check them both enabled and disabled, including the
performance cost when disabled.

Record the fork commit, engine ID, previous and new Flutter commits, test results,
build and SDK links, rendering comparisons, and review decision in the update PR.
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
