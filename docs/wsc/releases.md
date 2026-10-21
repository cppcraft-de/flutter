# Release identity and maintenance

Use this reference to release an accepted candidate and maintain its version
identity. To move to a new upstream version, start with
[Updating the WSC fork](updating.md). Jenkins setup belongs in the
[CI runbook](../../DEPLOYMENT.MD).

- [Release an accepted candidate](#release-procedure).
- [Update a WSC channel](#update-a-wsc-channel).
- [Understand versions and tags](#version-and-channel-identity).
- [Update the engine pin](#engine-identity).
- [Review an upstream port](#rebase-audit-checklist).
- [Find the implementation](#implementation-map).

## Release procedure

1. Build an **untagged candidate** with the complete SDK matrix on staging.
   Incremental workspaces are appropriate during iteration. Check the resulting
   WSC development identity and perform the runbook's extracted-SDK acceptance
   tests, including rendering validation and HTTP/Maven cache misses.
2. Finish engine changes and verify the engine pin. Tag the exact accepted
   source commit with one immutable [WSC release tag](#tags-and-generated-metadata).
   Keep the upstream tag
   untouched. If source changes afterward, test again and use the next WSC
   revision; do not move published tags.
3. Build the tagged source with `REQUIRE_RELEASE_TAG=true`,
   `BUILD_POLICY=full_rebuild`, `SYNC_ENGINE_DEPS=true`, the complete matrix, and
   the intended release artifact root. The source checkout must actually select
   the tagged commit; `RELEASE_BRANCH` is not a tag-selection parameter.
4. Verify both SDKs again and retain ZIPs/checksums, source SHA, engine ID,
   upstream base, and agent/toolchain versions. Record the accepted SDK links
   and rendering results in the release PR or build record. Only then advertise
   the release and follow the channel handoff below.

This is an **operator procedure**, not an implemented tag-only production job
or automatic promotion. Use the same pipeline source; do not create another
Jenkinsfile during commissioning. `REQUIRE_RELEASE_TAG` validates identity but
does not enforce clean policy, select storage, or approve a release.

For release source validation, `full_rebuild` clears engine `out`, not every
dependency or machine setting. It does **not** replace an already published
engine: packaging reuses that content hash's recorded artifacts. New IDs get
their first publication. Leave `DANGEROUSLY_OVERWRITE_BUILD_ARTIFACTS=false`;
see [publication policy and recovery](artifacts.md#publish-once-policy-and-recovery).
Thus a clean compilation is not proof that its new bytes are the shipped bytes;
acceptance tests must exercise the packaged/downloaded SDK. A controlled
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

### Tag the accepted source

Run this from the candidate checkout at the accepted commit. Replace
`ACCEPTED_SHA` with its full SHA and `WSC_TAG` with the agreed release tag,
for example `wsc-3.44.4-r1`:

```sh
python dev/bots/validate_sdk_identity.py --revision ACCEPTED_SHA
git tag -a WSC_TAG ACCEPTED_SHA -m "WSC release WSC_TAG"
python dev/bots/validate_sdk_identity.py --revision ACCEPTED_SHA --require-release-tag
```

After approval to publish the tag, push that tag only:

```sh
git push origin refs/tags/WSC_TAG
```

Run the release build from the candidate branch at that exact commit. Do not
advance the branch while selecting the build. The pipeline must fetch the tag;
`REQUIRE_RELEASE_TAG=true` checks it during preflight. A tag push by itself is
not an automatic release build or approval.

### Update a WSC channel

The fork's `main`, `beta`, and `stable` branches are intended to point to accepted
WSC versions of those upstream lines. Updating these refs is a separate,
reviewed action. Neither `sync_upstream.py`, `wsc_rebase.py`, nor Jenkins does it.

Before updating a channel, record:

- The channel, its current full SHA, and the accepted candidate's full SHA.
- The previous accepted tag or commit and SDK links for rollback.
- The approving maintainer and the release build/results being approved.

From the candidate checkout, fetch and inspect the channel. Replace `CHANNEL`
with `main`, `beta`, or `stable`, and `ACCEPTED_SHA` with the reviewed commit:

```sh
git fetch origin
git rev-parse refs/remotes/origin/CHANNEL
git log --oneline ACCEPTED_SHA..refs/remotes/origin/CHANNEL
git merge-base --is-ancestor refs/remotes/origin/CHANNEL ACCEPTED_SHA
```

The last command exits 0 if the update can fast-forward, or 1 if it cannot.
After patch replay, a non-fast-forward update is expected in many cases. Review
the commits that would leave the channel; they may contain fixes added since
you started the port. Do not merge the old channel into the candidate just to
make the push succeed: that changes the reviewed source and breaks the linear
patch sequence used by the update helper.

**The repository does not define the client's branch-protection or approval
rules.** Before the first promotion, agree who may update each channel and
whether reviewed non-fast-forward updates are allowed. For an approved rewrite,
use an explicit lease against the reviewed old SHA, never an unrestricted force
push. If branch protection rejects it, stop and resolve the release policy;
do not disable protection as part of a routine update.

Recheck source identity and Jenkins trigger settings before publishing the ref.
For an approved fast-forward update:

```sh
git push origin ACCEPTED_SHA:refs/heads/CHANNEL
```

If a non-fast-forward update has been explicitly approved and branch protection
allows it, use the recorded old SHA as the lease:

```sh
git push --force-with-lease=refs/heads/CHANNEL:OLD_CHANNEL_SHA origin ACCEPTED_SHA:refs/heads/CHANNEL
```

A failed lease means the remote changed. Fetch and review the new tip before
trying again. After a successful push, read the remote ref back:

```sh
git ls-remote origin refs/heads/CHANNEL
```

Confirm it matches the accepted commit. Share the approved SDK links with
developers. Keep the previous SDKs
and artifact tree for rollback; moving a Git ref does not replace an installed
SDK. There is no automatic binary promotion or private channel-update service.

## Version and channel identity

| Identity | Source and meaning |
| --- | --- |
| Framework revision | Exact Git commit selected by the Jenkins branch job |
| Engine ID | Tracked `bin/internal/engine.version`; upstream content hash selecting engine/Maven artifacts |
| `engineRevision` | Build-source commit recorded in the downloaded `engine_stamp.json`; may differ from the artifact namespace |
| `engineContentHash` | Engine input content hash recorded by the build; must match the artifact namespace |
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

For an explanation of the source commit, engine hash, and download paths, read
[Understanding engine versions and artifact downloads](engine-identity.md).

The pin-update procedure below prepares a distributable SDK candidate, including
an untagged Jenkins candidate. It is not required after each local development
commit.

For ordinary local engine development, retain a published, compatible
`bin/internal/engine.version` so Flutter and the IDE can bootstrap from the
mirror. Build your changes locally and select the outputs with `--local-engine`
and `--local-engine-host` (and `--local-engine-src-path` when needed). Local
commits do not automatically change the tracked pin, and local engine builds do
not need HTTP publication. See the [local development explanation](engine-identity.md#local-engine-development)
for bootstrap and SDK compatibility limits.

When preparing a distributable candidate, after committing all engine/DEPS/patch
changes, run from the repository root:

```sh
python dev/bots/engine_identity.py
```

Put the returned lowercase hash in `bin/internal/engine.version` and commit
only the pin change. The helper reads committed engine inputs without switching
branches or writing files. Framework-only changes and the pin commit itself do
not change this hash; later engine/DEPS/patch changes require checking it again.
Uncommitted edits in nested dependency checkouts must first become committed
patch inputs.

After the pin commit, obtain the current full source SHA and validate it:

```sh
git rev-parse HEAD
python dev/bots/validate_sdk_identity.py --revision FULL_SOURCE_SHA
```

Replace `FULL_SOURCE_SHA` with the first command's output. The validator requires
its checkout to match that revision and rejects stale pins on every build
policy, including untagged incremental builds. Add `--require-release-tag` when
checking a tagged release; that also requires an exact recognized WSC tag.

Jenkins supplies the upstream-compatible local build-branch context, pins SDK
packaging to the selected source SHA, and checks generated/published artifacts
and SDK metadata. See the [identity guide](engine-identity.md) for the branch
rule, Apple Git workaround, and why engine build provenance can legitimately
differ from the framework revision. Source and metadata checks do not replace
an extracted-SDK application build or rendering acceptance.

The content-hash migration applies to new SDKs and artifact paths. Retain
existing SDKs and their matching artifacts; validate a new candidate instead
of rewriting previously accepted artifacts under an old ID.

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
immutable WSC tags identify releases. The separate
[upstream sync helper](upstream-sync.md) copies vanilla branches under `upstream/*`
and adds original tags, without advancing WSC channels or replaying patches.
There is no automatic WSC channel promotion. Do not treat an arbitrary
existing ref or a forward-port branch as certified without checking it. Beta
support is optional; there is no need to visit every intermediate release.

### Nested Skia and FreeType patches

Follow [Port Skia and FreeType patches](dependency-patches.md) for the editing,
sync, and verification steps. Commit nested changes as patch inputs in the outer
repository. Do not rely on untracked edits in an existing dependency checkout.

Startup-gated diagnostics are implemented. The Dart API
`configureFontRenderingDiagnostics` selects collection before the first paragraph;
native startup also supports `WSC_FONT_DIAGNOSTICS`. Collection is off by default.
After a port, check enabled behavior and disabled overhead on the affected
backends. The presence of the API does not establish those runtime results.

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
| Upstream branches/tags in the fork; no WSC channel updates | [sync_upstream.py](../../dev/bots/sync_upstream.py), used by the [sync procedure](upstream-sync.md) |
| Candidate preparation and source checks | [wsc_rebase.py](../../dev/bots/wsc_rebase.py), used by the [update procedure](updating.md) |
| Orchestration, workspace policy, credentials, polling, notifications | [Jenkinsfile.testing](../../Jenkinsfile.testing) |
| Engine artifact collection from builder manifests | [collect_engine_artifacts.py](../../dev/bots/collect_engine_artifacts.py) |
| Upstream-owned seed inventory and HEAD checks | [seed_artifact_mirror.py](../../dev/bots/seed_artifact_mirror.py) |
| Authenticated HTTP PUT | [upload_artifact_tree.py](../../dev/bots/upload_artifact_tree.py) |
| Publish-once inventory, verification and explicit overwrite | [publish_engine_artifacts.py](../../dev/bots/publish_engine_artifacts.py) |
| Source-tag and SDK-JSON checks; SHA256 sidecars | [validate_sdk_identity.py](../../dev/bots/validate_sdk_identity.py) |
| SDK cloning, warm cache, and archive creation | [prepare_package](../../dev/bots/prepare_package/) |
| Desktop SDK rendering regression configuration and adapter | [frt_ci.json](../../dev/bots/frt_ci.json), [frt_ci.py](../../dev/bots/frt_ci.py); [setup and coverage](rendering-regression.md) |
| WSC Git-tag parsing and generated version metadata | [version.dart](../../packages/flutter_tools/lib/src/version.dart) |

Keep changes close to these existing paths. Do not introduce a second release
identity manifest or duplicate publishing pipeline without a concrete need.
