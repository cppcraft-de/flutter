# Updating the WSC fork

Use this guide to move the WSC changes onto a new upstream **stable**, **beta**,
or **main** base. You can skip intermediate releases.

The helper creates a new branch and worktree, then replays the WSC commits with
`git cherry-pick`. Your original branch and build outputs stay in place.
After the replay, check dependency patches, build SDKs, and review the results
before releasing anything.

1. [Choose the source and new base](#1-choose-the-source-and-new-base).
2. [Preview and replay the WSC changes](#2-preview-and-replay-the-wsc-changes).
3. [Check Skia and FreeType patches](#3-check-skia-and-freetype-patches).
4. [Commit the changes and update the engine pin](#4-commit-the-changes-and-update-the-engine-pin).
5. [Run source checks](#5-run-source-checks).
6. [Build and review the candidate](#6-build-and-review-the-candidate).
7. [Release the accepted candidate](#7-release-the-accepted-candidate).

## Before you start

You need Git, Python 3.10+, full repository history, and a clean source checkout,
including untracked files. Finish any pending Git operation first. Use `python3`
instead of `python` where needed. Tests also need PowerShell on Windows or Bash
on other hosts.

Choose a new sibling directory for the candidate. Replaying source needs no
engine dependencies, but a later dependency sync or build needs substantial disk
space. Keep existing engine workspaces and unrelated nested edits intact.

Agree on the source line, new upstream base, and rendering baseline with the
release reviewer. Review changes to rendering behavior or test expectations;
do not change baselines just to make a candidate pass. Agents use this same
procedure within the approvals given to them.

## 1. Choose the source and new base

Run these commands in the WSC source checkout. `origin` should point to the
client's fork; `upstream` should point to `https://github.com/flutter/flutter.git`.
If `upstream` is missing, add it with
`git remote add upstream https://github.com/flutter/flutter.git`.

```sh
git remote -v
git fetch origin --tags
git fetch upstream --tags
```

These fetches refresh your local history. To also copy vanilla upstream history
into the client's remote fork, use [Synchronizing upstream Git history](upstream-sync.md).
That is a separate task; it does not replay WSC patches.

The similar branch names mean different things:

| Local ref | What it represents |
| --- | --- |
| `upstream/stable` | Stable fetched directly from official Flutter |
| `origin/upstream/stable` | The fork's copy of vanilla upstream stable, after synchronization and a fetch |
| `origin/stable` | The fork's WSC stable branch; check its acceptance record before using it |

The same naming applies to beta and main.

Choose three inputs:

| Input | How to choose it |
| --- | --- |
| `OLD_BASE` | Read the exact upstream base from the source line's last update PR or release record. |
| `WSC_TIP` | Choose the committed WSC branch/tag containing the fixes you intend to carry forward. Include later fixes if the last release tag is no longer the desired source. |
| `NEW_BASE` | Choose an upstream release tag or a fixed main commit, as below. |

For an update within one channel, start from that channel's maintained WSC line.
For a first port to another channel, agree which maintained line supplies the
patches. An old forward-port branch may be missing newer fixes. If the previous
base was not recorded, establish it from the history with the maintainer before
continuing; do not assume a merge-base identifies the intended patch range.

| Task | Select `NEW_BASE` from | Later Jenkins setting |
| --- | --- | --- |
| Update stable | The chosen upstream release tag, for example `3.44.4` | `RELEASE_BRANCH=stable` |
| Update beta | The chosen upstream prerelease tag, for example `3.45.0-0.1.pre` | `RELEASE_BRANCH=beta` |
| Port to main | A reviewed commit on `upstream/main` | `RELEASE_BRANCH=main` |

The versions above illustrate the tag format; they are not a recommendation to
use those releases. Resolve each selected ref to a full commit SHA. This fixes
the inputs even if a branch moves during the update.

### Example: prepare a stable update

This PowerShell example assumes the previous base was `3.44.3`, the desired WSC
source is tagged `wsc-3.44.3-r1`, and the new base is `3.44.4`. Replace those refs
with your reviewed inputs. The candidate branch and directory must be new.
Stop if any command fails to resolve a ref.

```powershell
$oldBase = git rev-parse 'refs/tags/3.44.3^{commit}'
$wscTip = git rev-parse 'refs/tags/wsc-3.44.3-r1^{commit}'
$newBase = git rev-parse 'refs/tags/3.44.4^{commit}'
$candidate = 'wsc-candidate-3.44.4'
$candidatePath = '../wsc-candidate-3.44.4'
git log --reverse --oneline "$oldBase..$wscTip"
git diff --stat "$oldBase..$wscTip"
git diff "$oldBase..$wscTip"
```

For beta, resolve the selected beta tag instead. For main, use
`$newBase = git rev-parse 'refs/remotes/upstream/main^{commit}'` and choose a
candidate name that includes the date or short commit SHA. Keep `OLD_BASE` tied
to the WSC source you are replaying, regardless of the destination channel.

In Bash, assign refs with `oldBase=$(git rev-parse 'REF^{commit}')`, and likewise
for the other inputs. Assign names with `candidate='NAME'` and
`candidatePath='../NAME'`. The Git and Python commands below use the same variables.

Read the commit list and diff. The range must be a nonempty, linear sequence of
WSC changes directly after `OLD_BASE`. The helper rejects merges, but it cannot
tell whether you accidentally included upstream changes. Resolve an unsuitable
range before continuing; do not squash published history to bypass the check.
Record the three full SHAs in the update PR.

## 2. Preview and replay the WSC changes

From the source checkout, preview the example's selected range:

```sh
python dev/bots/wsc_rebase.py prepare --old-base "$oldBase" --tip "$wscTip" --new-base "$newBase" --branch "$candidate" --worktree "$candidatePath"
```

Check the printed commits, branch, and destination. Once the plan is approved,
run it with `--apply`:

```sh
python dev/bots/wsc_rebase.py prepare --old-base "$oldBase" --tip "$wscTip" --new-base "$newBase" --branch "$candidate" --worktree "$candidatePath" --apply
```

Read the result before changing directory. If it reports `Replay completed`,
enter the candidate and review the result below. If it reports `Replay stopped.
Candidate preserved at ...`, enter that directory to inspect the stopped replay,
even though the command exited nonzero. If preparation failed before creating
the worktree, stay in the source checkout and fix the reported error.

After confirming the candidate was created:

```sh
cd "$candidatePath"
```

If replay stops, stay in the candidate and inspect the conflict:

```sh
git status
git diff
git show CHERRY_PICK_HEAD
```

Resolve and review the conflicting files. Stage only those files, then continue:

```sh
git add PATH_TO_RESOLVED_FILE
git cherry-pick --continue
```

If a commit is empty because upstream already supplies the change, inspect it
before using `git cherry-pick --skip`. To abandon the replay, run
`git cherry-pick --abort` in the candidate. Its directory and branch remain;
a fresh attempt needs a new name/path. Do not rerun `prepare` over a stopped replay.

After replay, review the result:

```sh
git range-diff "$oldBase..$wscTip" "$newBase..HEAD"
git diff --stat "$newBase..HEAD"
git diff "$newBase..HEAD"
```

Look for workarounds upstream has replaced and changes to builder configuration,
bootstrap scripts, packaging, and patch hooks. A clean replay does not prove
that the changes still behave correctly. Resolve engine-pin conflicts during
replay, then derive the final pin in step 4.

## 3. Check Skia and FreeType patches

Replaying the outer repository copies patch files. It does not prove they apply
to the new dependency revisions.

Follow [Port dependency patches](dependency-patches.md) to compare the candidate's
`DEPS` pins, prepare isolated dependency checkouts, fix failed patches, and test
the sync hooks. Commit the patch files and expected revisions in the candidate.

If dependencies are not ready, you can run the source checks below without them,
but dependency validation remains pending. Do not use `SYNC_ENGINE_DEPS=false`
to bypass synchronization after changing dependency or patch inputs.

## 4. Commit the changes and update the engine pin

Commit all engine, dependency, and patch-file changes first. Then follow
[engine pin maintenance](releases.md#engine-identity): compute the hash with
`python dev/bots/engine_identity.py`, put it in `bin/internal/engine.version`,
commit the pin, and validate the full candidate SHA.

If the new upstream base ignores an untracked pin, stage it with
`git add -f bin/internal/engine.version`. Later engine-input changes require a
new pin check. Framework-only changes and the pin commit itself do not change
the engine hash.

This step prepares a distributable candidate. For ordinary local engine work,
keep the published bootstrap pin as described in
[local engine development](engine-identity.md#local-engine-development).

## 5. Run source checks

From the clean candidate checkout, using the same `$newBase` value:

```sh
python dev/bots/wsc_rebase.py verify --new-base "$newBase"
```

With prepared dependency repositories, supply both paths:

```sh
python dev/bots/wsc_rebase.py verify --new-base "$newBase" --skia-dir PATH_TO_SKIA --freetype-dir PATH_TO_FREETYPE
```

The helper checks ancestry, whitespace, the engine pin, source identity, and
focused Python tests. The optional dependency check applies patches to pristine
Git objects without changing the supplied working trees. Success ends with
`SOURCE CHECKS PASSED, NOT RELEASE APPROVAL` and lists remaining checks.

Before using the source checkout's Dart/Flutter commands, select a mirror that
contains its pinned artifacts; see [mirror selection](artifacts.md#packaging-and-mirror-selection).
The tracked source default and Jenkins' `ci-v2` default differ. After publication,
select the build's download root before retrying bootstrap; publication alone
does not change the source checkout's mirror.

Run the Dart/Flutter checks with a compatible SDK and resolved packages:

```sh
dart pub get --directory dev/bots
dart test dev/bots/test/prepare_package_test.dart
cd packages/flutter_tools
flutter test test/general.shard/version_test.dart
cd ../..
```

If the candidate cannot bootstrap until its engine artifacts are published,
use an available compatible SDK for source tests or record the checks as pending
until after the CI build. Do not revert the candidate pin to bypass that failure.
Also run tests for the rendering or diagnostic code you changed and work through
the [rebase audit checklist](releases.md#rebase-audit-checklist).

## 6. Build and review the candidate

Before pushing, run the [source identity check](releases.md#engine-identity) on
the final committed candidate and review Jenkins polling/indexing settings.
A push may start a build. Obtain approval to push and build, then follow
[Run the integration build](../../DEPLOYMENT.MD#4-run-the-integration-build).

Select the **candidate branch job** as the source and set `RELEASE_BRANCH` for
the intended channel. For example, building `wsc-candidate-3.44.4` with
`RELEASE_BRANCH=stable` packages that candidate as stable; the parameter does
not select upstream stable or move the fork's stable branch. The named channel
branch must already exist in the fork for packaging to clone it.

Use a separate persistent workspace for the new line. Keep the previous line's
outputs intact. Build the supported SDK matrix and run the
[extracted-SDK acceptance checks](../../DEPLOYMENT.MD#5-accept-the-sdks-before-distribution).

Jenkins has FRT comparisons for Windows, macOS, and Web. Review their results;
disabled or failed comparisons leave rendering acceptance incomplete. Android
and iOS are not covered by those stages. See
[rendering acceptance](rendering-regression.md#outcomes-evidence-and-acceptance)
for CI evidence and remaining agent acceptance work. To run FRT yourself, use
the [FRT README](https://bitbucket.org/schoolcraftteam/font_rendering_tester/src/master/README.md).
When porting diagnostics, also check enabled behavior and disabled overhead.

Record the source and engine IDs, old/new bases, test results, CI build and SDK
links, rendering baseline/results, and reviewer approval in the update PR.
Keep compilation, packaging, publication, and runtime results distinct.

## 7. Release the accepted candidate

Follow the [release procedure](releases.md#release-procedure) to tag the accepted
source, build and check the release SDKs, and hand over the approved downloads.
Follow [Update a WSC channel](releases.md#update-a-wsc-channel) for the branch
handoff. Neither the rebase helper nor a green CI build promotes a channel.

## Helper tests and limits

To check the helper itself:

```sh
python -B -m unittest discover -s dev/bots -p test_wsc_rebase.py
```

These tests use disposable repositories. They cover replay, conflict recovery,
input checks, and dependency-patch checking, not a real Flutter build or rendering
acceptance. Verification executes the candidate's scripts and tests, so use
trusted source. On Windows, the hash-helper test uses a process-only PowerShell
execution-policy override; it does not change machine settings.
