# Updating the WSC fork

One procedure for humans and coding agents. Scripts handle mechanical checks;
Git holds the replay state. There is no separate AI release process or custom
rebase-state manifest. Use this for patch releases, minor releases, or a chosen
upstream development commit. You need not visit every intermediate release.

This guide prepares **candidates**, not automatically approved releases. See
[release identity and policy](releases.md) and the [CI runbook](../../DEPLOYMENT.MD)
for packaging, release tags, Jenkins settings, and developer acceptance.

## Boundaries and prerequisites

- Start from the latest intended WSC source line, including diagnostics and CI
  changes. A forward-port branch is not necessarily the most current patch set.
- Finish and commit the changes to replay first. The helper refuses dirty or
  shallow source checkouts and unfinished Git operations; it never stashes work.
- Use Python 3.10+ and Git. Tests and engine identity checks also use the normal
  platform tools (PowerShell on Windows, Bash elsewhere). Run only trusted fork
  code: verification executes its scripts/tests and imports its patch inventory.
  The Windows engine-pin check uses the same process-scoped execution-policy
  override as Jenkins; it does not change user/machine PowerShell settings.
- Choose a **new sibling worktree** on a volume with sufficient space. Source
  preparation does not download dependencies or compile engines. Dependency sync
  and CI builds later need much more space. Do not repurpose, move, or clean
  accepted-version Jenkins workspaces to make this procedure work.
- Obtain human approval for the selected source range/new base, semantic conflict
  resolutions or changed test expectations, and release publication. Agents can
  execute the same commands within those approvals. Never weaken tests or update
  rendering references merely to make a candidate pass.

The helper never fetches, pushes, tags, moves channel refs, starts Jenkins, or
cleans workspaces. `prepare --apply` creates a local branch/worktree and commits
the replay. `verify` checks sources; its exit code is **not release approval**.

## 1. Choose and review the inputs

Check the upstream URL, then fetch branches/tags without forcing tag updates.
In the maintained source checkout:

```sh
git remote -v
git fetch upstream --tags
```

Select three explicit inputs:

| Input | Meaning |
| --- | --- |
| `OLD_BASE` | Exact upstream commit/tag on which the WSC source line was based |
| `WSC_TIP` | Committed WSC source to carry forward, including its latest fixes |
| `NEW_BASE` | Exact upstream tag/commit to port onto |

Use full SHAs in the final invocation so a moving branch cannot change the plan.
Resolve tags/refs with `git rev-parse REF^{commit}` (quote the revision expression
in PowerShell). Record the three SHAs and chosen baseline in the review/PR.
This is review evidence, not another SDK version authority.

The helper checks that `OLD_BASE..WSC_TIP` is a nonempty linear tail with no merge
commits. **It cannot prove these are all WSC changes.** A base chosen too far back
can include upstream commits even in a linear range. Review the printed list and
its diff. If the range is not suitable, stop and clarify the base/stack; do not
silently squash published history or select a guessed merge base.

Example, from the source checkout; replace all uppercase placeholders. Commands
are single lines so they work without shell-specific continuation characters:

```sh
python dev/bots/wsc_rebase.py prepare --old-base OLD_BASE --tip WSC_TIP --new-base NEW_BASE --branch wsc-candidate-NEW_VERSION --worktree ../wsc-candidate-NEW_VERSION
```

This only previews. Once the source range, disk location, and candidate name are
approved, repeat the same command with `--apply`:

```sh
python dev/bots/wsc_rebase.py prepare --old-base OLD_BASE --tip WSC_TIP --new-base NEW_BASE --branch wsc-candidate-NEW_VERSION --worktree ../wsc-candidate-NEW_VERSION --apply
```

Use `python3` if that is the working Python command on your host. No existing
destination/branch is overwritten. The original source checkout stays on its
original branch, and its build outputs are not touched.

## 2. Resolve replay stops and review the result

Work inside the **new candidate** from this point onward. If replay stops:

```sh
git status
git diff
# Edit and review the conflicting files, then stage only those files:
git add PATH_TO_RESOLVED_FILE
git cherry-pick --continue
```

An empty commit can mean upstream already provides the change. Inspect it before
explicitly choosing `git cherry-pick --skip`; never skip automatically. To abandon
the replay use `git cherry-pick --abort` **in the candidate**. Its directory/branch
remain, and the original accepted line is unchanged. A fresh attempt needs a new
candidate name/path unless you explicitly arrange cleanup yourself.

After replay, inspect both the patch correspondence and resulting source delta:

```sh
git range-diff OLD_BASE..WSC_TIP NEW_BASE..HEAD
git diff --stat NEW_BASE..HEAD
git diff NEW_BASE..HEAD
```

Pay particular attention to upstream replacements for our workarounds, builder
configuration changes, version/package scripts, and patch hooks. A clean replay
is not proof that a workaround remains necessary or correct. An unexpected engine
pin conflict is not a reason to reuse the old pin: resolve the file conflict as
part of replay, then derive the final pin again in step 4.

## 3. Port and check nested dependency patches

Outer Git replay only moves the **patch files**. It does not establish that they
still apply to the new Skia/FreeType revisions.

1. Review the candidate's `DEPS` dependency revisions against
   `EXPECTED_REVISIONS` in `apply_patches.py`. Adapt the patches to the actual new
   dependency sources before updating those expected revisions. Do not copy the
   old dependency pins over upstream changes just to make a check pass.
2. Use the candidate's isolated dependency checkout or separately prepared
   dependency repositories at those exact revisions. Do not sync/reset a dirty
   existing workspace. Follow the
   [nested patch rules](releases.md#nested-skia-and-freetype-patches).
3. After committing the adaptations and pin (next step), the optional
   `--skia-dir`/`--freetype-dir` verification checks ordered patch application on
   **pristine Git objects**. The supplied repositories provide objects; their
   dirty working files are neither trusted nor changed. No dependency downloads
   or full temporary dependency checkouts are needed for this check.
4. Still verify a real dependency sync/apply and a second already-applied hook
   invocation in the isolated candidate/build workspace. The object-only check
   does not test hooks, current working files, DEPS resolution, or rendering.

If dependencies are not prepared yet, source verification can run without those
arguments, but it reports dependency validation as **PENDING**. Do not treat that
as a completed port. CI's default `SYNC_ENGINE_DEPS=auto` synchronizes changed
dependency/patch inputs and reuses unchanged ones. Use `true` for a forced repair
or the documented production build; do not use explicit `false` to bypass the
first synchronization of a changed dependency/patch set. See the runbook's
[incremental behavior](../../DEPLOYMENT.MD#incremental-behavior) for tracking and
the first-run migration from the old checkbox.

## 4. Commit source changes and derive the engine pin

After all engine/DEPS/patch changes are committed, run the existing upstream
identity script and put its output in `bin/internal/engine.version`, as described
under [engine identity](releases.md#engine-identity). Commit only that pin change
and verify it again. Use `git add -f bin/internal/engine.version` if the new base
ignores an as-yet-untracked pin. Do not hand-copy the previous release's engine ID.

The helper checks the committed pin but deliberately does not stage files or
create a pin commit. Any later engine-affecting commit means repeating this step.

## 5. Run source checks

From the clean candidate checkout:

```sh
python dev/bots/wsc_rebase.py verify --new-base NEW_BASE
# With prepared dependency repositories (both arguments are required together):
python dev/bots/wsc_rebase.py verify --new-base NEW_BASE --skia-dir PATH_TO_SKIA --freetype-dir PATH_TO_FREETYPE
```

This checks linear ancestry, diff whitespace, the tracked engine pin, source tag
identity, and the focused Python identity/publishing/workflow tests. Missing test
files or failed checks stop verification. Optional patch checks use the candidate's
existing patch order/inventory, not a second maintained list.

Run the Dart/Flutter checks with the candidate's supported SDK and resolved
package configuration too; the Python helper does not bootstrap these toolchains:

```sh
dart pub get --directory dev/bots
dart test dev/bots/test/prepare_package_test.dart
cd packages/flutter_tools
flutter test test/general.shard/version_test.dart
cd ../..
```

Use an already available compatible SDK for source tests where possible. If
bootstrap requires not-yet-published candidate engine artifacts, record these
checks as pending and complete them after the CI build in step 6. Do not revert
the engine pin or accept missing tests to bypass a bootstrap failure.

Run the tests for touched rendering/diagnostic code as well. A changed upstream
test layout/toolchain may require updating these commands; do not turn missing
tests into skips. Consult the [rebase audit checklist](releases.md#rebase-audit-checklist)
for bootstrap, artifact manifests, pinned downloads, and toolchain review.

## 6. Build and accept the candidate

After reviewing the source result, obtain approval to push the candidate and run
the existing `Jenkinsfile.testing` pipeline. Verify indexing/polling behavior
before pushing: a new branch may cause a build depending on Jenkins settings.
Use the [CI runbook](../../DEPLOYMENT.MD), not a second maintenance pipeline.

- Use a separate persistent workspace for the new upstream line. Keep the prior
  accepted line intact. Budget for an initial build; incremental cannot promise
  reuse across changed source/toolchain versions or different absolute paths.
- Build/package the supported target/host matrix. Exercise the **extracted SDKs**
  and a cache miss against the mirror, not only the source checkout.
- Check diagnostics-disabled overhead as well as diagnostics-enabled behavior.
- **Rendering gate: PENDING IMPLEMENTATION.** No placeholder script returns a
  successful rendering verdict. Until the automatic checker is integrated,
  require recorded human rendering review against the explicitly chosen accepted
  WSC baseline. Without that review, this remains a CI candidate, not a release.

Review evidence should identify old/new upstream SHAs, WSC source SHA, engine ID,
source/patch test results, CI runs/SDKs, rendering baseline/result, and approvals.
A PR description or CI record is enough; no extra runtime metadata file is needed.

## 7. Release only after human sign-off

Follow the existing [release procedure](releases.md#release-procedure): immutable
WSC tag, appropriate release build/identity validation, retained artifacts, then
advertise the SDK and update the intended channel ref with explicit approval.
The old release and its artifact namespace remain available for rollback. An AI
assistant must not infer publication approval from a green source-check command.

## Helper tests and scope

```sh
python -B -m unittest discover -s dev/bots -p test_wsc_rebase.py
```

These offline tests create disposable tiny Git repositories: preview, replay,
conflicts/continue/abort, empty commits, invalid inputs, and dependency-patch
checks without changing dependency working files/indexes/objects. They do not
certify a real upstream Flutter port, engine build, or rendering equivalence.
