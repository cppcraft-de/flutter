# Release identity and maintenance

Use [DEPLOYMENT.MD](../../DEPLOYMENT.MD) for Jenkins setup and SDK acceptance.
This document separates implemented identity behavior from release governance
that operators must still enforce.

## Version and channel identity

| Identity | Source and meaning |
| --- | --- |
| Framework revision | Exact Git commit selected by the Jenkins branch job |
| Engine ID | Tracked `bin/internal/engine.version`; namespace of the engine/Maven artifacts |
| `frameworkVersion` | Flutter-compatible numeric version; WSC exact tags supply their embedded upstream version |
| `wscVersion` | Exact WSC release tag, or an automatically derived development identity |
| Channel | Packaged local branch name selected by `RELEASE_BRANCH` |
| Download root | Resolved artifact URL; independent of channel and build policy |

There are no `SOURCE_REVISION`, `SDK_CHANNEL`, or `PUBLISH_ENV` parameters in the
current Jenkinsfile. Source comes from SCM; `RELEASE_BRANCH` chooses the packaged
channel. `BUILD_POLICY` chooses incremental versus rebuilding outputs. URL
configuration chooses the storage environment. Do not overload a channel name
to mean production approval.

### Tags and generated metadata

Keep upstream numeric tags on their original commits. Tag the patched release
with **`wsc-<upstream-version>-r<number>`**, for example:

```text
Git tag:          wsc-3.44.4-r1
frameworkVersion: 3.44.4
wscVersion:       wsc-3.44.4-r1
channel:          stable
Windows archive:  flutter_windows_wsc-3.44.4-r1-stable.zip
```

Beta bases use the same grammar, e.g. `wsc-3.45.0-0.1.pre-r1`. The revision
number starts at 1. A tag such as `wsc-3.44.4` without `-r1` is not a recognized
final release tag. Put at most one recognized WSC release tag on a commit;
source preflight rejects ambiguity.

The fork extends Flutter's existing Git-tag logic in
[version.dart](../../packages/flutter_tools/lib/src/version.dart). An exact WSC
tag supplies the WSC identity and embedded numeric Flutter version. Untagged
work derives WSC identity using `git describe` over reachable upstream/WSC tags:

```text
wsc-3.44.4-dev.45-g097c6f756e
wsc-3.44.4-r1-dev.5-gabcdef1234
```

The latter means development after r1, not a prediction of r2. Flutter's own
untagged numeric fallback deliberately retains upstream's highest-available-tag
and commit-count calculation. Fetching newer tags can therefore make the numeric
development version look newer than the actual base. The additive WSC identity
and commit identify the candidate; an exact WSC tag fixes release identity.
No manually maintained candidate-version file is required.

The generated `bin/cache/flutter.version.json` stores `wscVersion` beside the
existing fields. `flutter --version` adds a `WSC SDK` line;
`flutter --version --machine` exposes the field. The packager uses it for the
archive name. That JSON is disposable generated cache, not a second authority.

`RELEASE_BRANCH=stable` causes the packager to clone the fork's existing stable
ref and reset the attached local branch to the exact build revision. It does
not build the latest upstream stable commit. Branch names on arbitrary source
checkouts can display `[user-branch]`; packaging supplies the desired channel.

### Engine identity

After committing all engine/DEPS changes, run from the repository root:

```sh
bin/internal/last_engine_commit.sh
```

On Windows use `bin\internal\last_engine_commit.ps1`. Put the returned full SHA
in `bin/internal/engine.version`, commit that pin, then verify it again. Do not
substitute the framework tip or a release tag for this calculation.

The pipeline checks the pin using full history. A mismatch warns on incremental
staging builds but fails a `full_rebuild` with publication enabled. Another
engine-affecting commit requires repinning. Rewriting history can change this
identity even with identical source contents. Agent/toolchain changes, however,
are not encoded by this Git calculation; record them for accepted releases.

## Release procedure

1. Build an **untagged candidate** with the complete SDK matrix on staging.
   Incremental workspaces are appropriate during iteration. Check the resulting
   WSC development identity and perform the runbook's extracted-SDK acceptance
   tests, including rendering validation and HTTP/Maven cache misses.
2. Finish engine changes and verify the engine pin. Tag the exact accepted
   source commit with one immutable WSC release tag. Keep the upstream tag
   untouched. If source changes afterward, test again and use the next WSC
   revision; do not move published tags.
3. Build the tagged source with `REQUIRE_RELEASE_TAG=true`,
   `BUILD_POLICY=full_rebuild`, `SYNC_ENGINE_DEPS=true`, the complete matrix, and
   the intended release artifact root. The source checkout must actually select
   the tagged commit; `RELEASE_BRANCH` is not a tag-selection parameter.
4. Verify both SDKs again and retain ZIPs/checksums, source SHA, engine ID,
   upstream base, and agent/toolchain versions. Only then advertise the release.

This is an **operator procedure**, not an implemented tag-only production job
or automatic promotion. Use the same pipeline source; do not create another
Jenkinsfile during commissioning. `REQUIRE_RELEASE_TAG` validates identity but
does not enforce clean policy, select storage, or approve a release.

Production uses fresh compilation outputs for correctness; `full_rebuild`
clears engine `out`, not every dependency or machine setting. A controlled
environment and runtime acceptance are still required. Repeat the same tag
after a transient infrastructure failure only when preserving its intended
inputs; do not silently replace already accepted binaries after toolchain
changes. Production uploads are not transactional—see
[publication and retention](artifacts.md#environments-and-retention).

Tagging alone changes no source and needs no engine rebuild for an incremental
identity check. It **does** require fresh SDK packaging to regenerate version
metadata: adding a tag does not invalidate an already-created archive/cache.
The clean production build above is release policy, not a consequence of Git
tagging. Rollback uses the retained previous SDK and its matching artifact tree.

## Upstream updates and patch replay

Follow [Updating the WSC fork](updating.md), the shared human/agent procedure
with preview-first preparation and source-verification helpers. Treat every
upstream update, including a patch release, as a new candidate. Preserve the
previous accepted line and its artifact IDs. Maintain a linear WSC-only tail on
a known upstream base; replay that tail, not old upstream history, onto the new
base. The helper uses ordinary Git cherry-pick state and stops for conflicts;
it never publishes refs or approves a release. Conflict-free application is not
proof of semantic correctness.

The intended channel policy is that fork `main`/`beta`/`stable` point to accepted
patched equivalents of the selected upstream lines. These are moving refs;
immutable WSC tags identify releases. There is no checked-in automation that
continuously rebases/mirrors every upstream channel. Do not treat an arbitrary
existing ref or a forward-port branch as certified without checking it. Beta
support is optional; there is no need to visit every intermediate release.

### Nested Skia and FreeType patches

The source of truth is
[wsc_font_rendering_patches](../../engine/src/flutter/tools/wsc_font_rendering_patches/)
and the DEPS revisions, not ad hoc edits in nested workspaces.

1. Use an isolated candidate checkout. Inspect and preserve unrelated nested
   changes before syncing. Outer `git status` does not report all nested changes.
2. `gclient sync` runs the WSC pre-dependency reset hook and subsequent patch
   application. Record the resulting Skia/FreeType HEADs. Resetting patch-owned
   files can alter mtimes and cause rebuilds; there is no mtime-restoration layer.
3. If patches fail, port their intent to the new pristine dependency revision
   and regenerate the patch files in the declared order. Do not guess rendering
   conflict resolutions or blindly update the expected revisions.
4. Review `EXPECTED_SKIA_REVISION`, `EXPECTED_FREETYPE_REVISION`, and
   `GROUP_MARKERS` in `apply_patches.py` when their targets change. Verify a clean
   sync/apply and an already-applied invocation. Markers are not a substitute
   for testing an evolved patch stack.
5. Run layout/rendering tests on supported backends before accepting the port.
   Historical diagnostic instrumentation may remain in ignored nested trees;
   do not mistake it for the checked-in release stack or discard it blindly.

Runtime-gated diagnostics with negligible disabled overhead remain a design
direction, not a release guarantee. Do not instruct maintainers to add/remove a
diagnostic branch as a required CI step unless that workflow is explicitly
implemented and validated.

### Rebase audit checklist

- **Launchers/bootstrap:** mirror selection, `sky_engine`/`flutter_gpu` fetches,
  Dart/tool bootstrap, and Windows path handling still work from a clean SDK.
- **Version/package changes:** exact WSC tags, untagged identity, generated JSON,
  archive naming, and HTTPS nested-clone authentication still agree.
- **Artifact manifests:** collector layout matches new engine builder JSON;
  new outputs/targets are covered. Do not copy binaries under guessed paths.
- **Pinned downloads:** compare `bin/internal/*.version`, including fonts,
  Gradle wrapper, and iOS tools. Seeding handles known paths; audit newly added
  input types. Keep old objects and record the unversioned coverage snapshot.
- **Toolchains:** review the new revision's prerequisites and record installed
  versions. Skipping dependency synchronization across a rebase is not safe.
- **Engine pin:** commit source changes, calculate the engine ID, then commit
  its pin. Preserve older accepted artifact namespaces.
- **Verification:** source/patch tests first, then real engine compilation,
  packaging, uploads, fresh SDK/cache-repair tests, and rendering tests. A pass
  at one level does not certify the following levels.

Useful focused tests (with a compatible configured Dart/Python environment):

```sh
python -m unittest discover -s dev/bots -p test_artifact_publishing.py
python -m unittest discover -s dev/bots -p test_validate_sdk_identity.py
dart test dev/bots/test/prepare_package_test.dart
```

Also run Flutter tooling's version tests with its normal test harness. Do not
commit generated `.dart_tool/package_config.json`, caches, build outputs, or
machine-specific test environment paths.

## Implementation map

| Responsibility | Source |
| --- | --- |
| Candidate preparation and source checks | [wsc_rebase.py](../../dev/bots/wsc_rebase.py), used by the [update procedure](updating.md) |
| Orchestration, workspace policy, credentials, polling, notifications | [Jenkinsfile.testing](../../Jenkinsfile.testing) |
| Engine artifact collection from builder manifests | [collect_engine_artifacts.py](../../dev/bots/collect_engine_artifacts.py) |
| Upstream-owned seed inventory and HEAD checks | [seed_artifact_mirror.py](../../dev/bots/seed_artifact_mirror.py) |
| Authenticated HTTP PUT | [upload_artifact_tree.py](../../dev/bots/upload_artifact_tree.py) |
| Source-tag and SDK-JSON checks; SHA256 sidecars | [validate_sdk_identity.py](../../dev/bots/validate_sdk_identity.py) |
| SDK cloning, warm cache, and archive creation | [prepare_package](../../dev/bots/prepare_package/) |
| WSC Git-tag parsing and generated version metadata | [version.dart](../../packages/flutter_tools/lib/src/version.dart) |

Keep changes close to these existing paths. Do not introduce a second release
identity manifest or duplicate publishing pipeline without a concrete need.
