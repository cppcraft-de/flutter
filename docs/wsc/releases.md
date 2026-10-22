# Release the patched Flutter SDK

Use this guide after you have an updated branch that is ready to build and test
for release. A **candidate** is that proposed version before release approval.
The steps below cover testing it, adding a release tag, and updating the fork's
main, beta, or stable branch.

To apply the patches to a newer Flutter version, start with
[Update to a new Flutter version](updating.md). For Jenkins setup, see
[Build and distribute SDKs](../../DEPLOYMENT.MD). Detailed version fields and
implementation links follow the release steps below.

- [Release an accepted candidate](#release-procedure).
- [Update a release channel](#update-a-release-channel).
- [Understand versions and tags](#version-and-channel-identity).
- [Update the engine pin](#engine-identity).
- [Review an upstream port](#rebase-audit-checklist).
- [Find the implementation](#implementation-map).

## Release procedure

1. Build the proposed version on the testing server before adding a release
   tag. Select all required targets and modes for both SDKs. You can reuse
   existing build outputs while working through fixes. Check the SDK version
   and follow [test the extracted SDKs](../../DEPLOYMENT.MD#5-accept-the-sdks-before-distribution),
   including rendering checks and builds that download dependencies into fresh caches.
2. Finish engine changes and verify the engine pin. Tag the exact accepted
   commit with one [release tag](#tags-and-generated-metadata) that will stay on
   that commit. Keep the official Flutter tag untouched. If the code changes
   afterward, test again and use the next fork release revision; do not move
   published tags.
3. Build the tagged commit with `REQUIRE_RELEASE_TAG=true`,
   `BUILD_POLICY=full_rebuild`, `SYNC_ENGINE_DEPS=true`, all required targets and
   modes, and the intended release download server. The build must select
   the tagged commit; `RELEASE_BRANCH` is not a tag-selection parameter.
4. Test both packaged SDKs again. Keep the archives and their generated checksums,
   commit ID, engine ID, upstream base, and agent/toolchain versions.
   Record the accepted SDK links
   and rendering results in the release PR or build record. Only then advertise
   the release and update its channel branch as described below.

You run these steps using the existing `Jenkinsfile.testing`. There is no
separate release job that handles them automatically. `REQUIRE_RELEASE_TAG`
checks the tag; you still select the build settings and server and review the result.

`full_rebuild` clears the engine's `out` directory and recompiles it. It does not
reset every dependency or machine setting. If files for that engine ID are
already published, packaging reuses them. Leave
`DANGEROUSLY_OVERWRITE_BUILD_ARTIFACTS=false`;
see [publication policy and recovery](artifacts.md#publish-once-policy-and-recovery).
Test the SDK that developers will download: a successful rebuild alone does not
show which binaries ended up in that SDK. You can retry the same tag after a
temporary infrastructure failure if its intended inputs stay the same. A
toolchain change is not permission to replace already accepted binaries.
Uploads can complete for one target before another fails; see
[publication and retention](artifacts.md#environments-and-retention).

Adding a tag does not change the engine code. It does require packaging a new
SDK so that the version output and archive name include the tag. The full
rebuild above is part of the release procedure, not something Git requires.
To roll back, use the previous SDK and keep its matching downloads available.

### Tag the tested commit

Run this from the candidate checkout at the accepted commit. Replace
`ACCEPTED_SHA` with its full commit ID and `RELEASE_TAG` with the agreed release tag,
for example `wsc-3.44.4-r1`:

```sh
python dev/bots/validate_sdk_identity.py --revision ACCEPTED_SHA
git tag -a RELEASE_TAG ACCEPTED_SHA -m "Patched Flutter release RELEASE_TAG"
python dev/bots/validate_sdk_identity.py --revision ACCEPTED_SHA --require-release-tag
```

After approval to publish the tag, push that tag only:

```sh
git push --no-follow-tags origin refs/tags/RELEASE_TAG
```

Run the release build from the candidate branch at that exact commit. Do not
advance the branch while selecting the build. The pipeline must fetch the tag;
`REQUIRE_RELEASE_TAG=true` checks it during preflight. A tag push by itself is
not an automatic release build or approval.

### Update a release channel

The fork's `main`, `beta`, and `stable` branches are intended to point to accepted
patched versions of those Flutter channels. Updating these branches is a separate,
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
make the push succeed: that changes the reviewed code and breaks the linear
patch sequence used by the update helper.

**The repository does not define your team's branch-protection or approval
rules.** Before the first promotion, agree who may update each channel and
whether reviewed non-fast-forward updates are allowed. For an approved rewrite,
use an explicit lease against the reviewed old SHA, never an unrestricted force
push. If branch protection rejects it, stop and resolve the release policy;
do not disable protection as part of a routine update.

Recheck the SDK version and engine pin, and check whether pushing will trigger Jenkins.
For an approved fast-forward update:

```sh
git push --no-follow-tags origin ACCEPTED_SHA:refs/heads/CHANNEL
```

If a non-fast-forward update has been explicitly approved and branch protection
allows it, use the recorded old SHA as the lease:

```sh
git push --no-follow-tags --force-with-lease=refs/heads/CHANNEL:OLD_CHANNEL_SHA origin ACCEPTED_SHA:refs/heads/CHANNEL
```

A failed lease means the remote changed. Fetch and review the new tip before
trying again. After a successful push, read the remote ref back:

```sh
git ls-remote origin refs/heads/CHANNEL
```

Confirm it matches the accepted commit. Share the approved SDK links with
the team. Keep the previous SDKs and their downloads for rollback;
moving a branch does not replace an installed
SDK. There is no automatic binary promotion or private channel-update service.

## Version and channel identity

The release tag identifies our patched SDK; the embedded Flutter version keeps
compatibility with Flutter's tools. Existing tags and metadata use the `wsc`
prefix, short for Worksheet Crafter. These names are part of the current tooling.

| Identity | Source and meaning |
| --- | --- |
| Framework revision | Exact Git commit selected by the Jenkins branch job |
| Engine ID | Tracked `bin/internal/engine.version`; upstream content hash selecting engine/Maven artifacts |
| `engineRevision` | Build-source commit recorded in the downloaded `engine_stamp.json`; may differ from the artifact namespace |
| `engineContentHash` | Engine input content hash recorded by the build; must match the artifact namespace |
| `frameworkVersion` | Flutter-compatible numeric version; the fork's release tags supply their embedded upstream version |
| `wscVersion` | Exact fork release tag, or an automatically derived development identity |
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
final release tag. Put at most one recognized fork release tag on a commit;
the pre-build check rejects multiple release tags.

The fork extends Flutter's existing Git-tag logic in
[version.dart](../../packages/flutter_tools/lib/src/version.dart). An exact fork release
tag supplies the patched SDK version and embedded numeric Flutter version. Untagged
builds derive the fork version using `git describe` over reachable Flutter and fork tags:

```text
wsc-3.44.4-dev.45-g097c6f756e
wsc-3.44.4-r1-dev.5-gabcdef1234
```

The latter means development after r1, not a prediction of r2. Flutter's own
untagged numeric fallback deliberately retains upstream's highest-available-tag
and commit-count calculation. Fetching newer tags can therefore make the numeric
development version look newer than the actual base. The fork version and commit
identify the candidate; an exact release tag identifies a release.
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

**Check the pin before every push that can start a Jenkins build, even for a
docs-only change.** Upstream includes every tracked file under `engine/` in the
engine hash, including Markdown files. Editing a document there changes the
hash without changing rendering code. A stale pin stops Jenkins before any
compilation; incremental builds are not exempt.

When preparing a distributable candidate, after committing your changes, run
from the repository root:

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
checking a tagged release; that also requires an exact recognized fork release tag.

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

Follow [Update to a new Flutter version](updating.md) for the full procedure.
Even a small Flutter patch release needs a new test build. Keep the previous
tested version and its downloads available while checking the update.

Keep the fork's commits as a linear sequence after the recorded official Flutter
commit. The update helper reapplies that sequence to the new Flutter version
and stops for conflicts. It does not push branches or approve releases. Patches
that apply cleanly still need build and rendering tests.

The fork's `main`, `beta`, and `stable` branches should point to reviewed patched
versions. Release tags stay fixed on their commits. The separate
[sync helper](upstream-sync.md) copies official Flutter history into the fork;
it does not update our patched channel branches. Check the review record before
using an existing branch as a release. Beta support is optional, and updates can
skip intermediate Flutter releases.

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
- **Version/package changes:** fork release tags, untagged identity, generated JSON,
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

For source-checkout Dart/Flutter commands, first select a mirror containing the
tracked engine pin's artifacts; see [mirror selection](artifacts.md#packaging-and-mirror-selection).
Publishing to Jenkins' `ci-v2` root does not change the source checkout's default.
Use a compatible available SDK or leave these checks pending until publication
if the candidate's artifacts are not yet available.

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
| Copies of official Flutter branches and tags | [sync_upstream.py](../../dev/bots/sync_upstream.py), used by the [sync procedure](upstream-sync.md) |
| Prepare an update branch and run its checks | [wsc_rebase.py](../../dev/bots/wsc_rebase.py), used by the [update procedure](updating.md) |
| Orchestration, workspace policy, credentials, polling, notifications | [Jenkinsfile.testing](../../Jenkinsfile.testing) |
| Engine artifact collection from builder manifests | [collect_engine_artifacts.py](../../dev/bots/collect_engine_artifacts.py) |
| Copy missing upstream files to the download server | [seed_artifact_mirror.py](../../dev/bots/seed_artifact_mirror.py) |
| Authenticated HTTP PUT | [upload_artifact_tree.py](../../dev/bots/upload_artifact_tree.py) |
| Publish-once inventory, verification and explicit overwrite | [publish_engine_artifacts.py](../../dev/bots/publish_engine_artifacts.py) |
| Source-tag and SDK-JSON checks; SHA256 sidecars | [validate_sdk_identity.py](../../dev/bots/validate_sdk_identity.py) |
| SDK cloning, warm cache, and archive creation | [prepare_package](../../dev/bots/prepare_package/) |
| Desktop SDK rendering regression configuration and adapter | [frt_ci.json](../../dev/bots/frt_ci.json), [frt_ci.py](../../dev/bots/frt_ci.py); [setup and coverage](rendering-regression.md) |
| Fork release-tag parsing and generated version metadata | [version.dart](../../packages/flutter_tools/lib/src/version.dart) |

Keep changes close to these existing paths. Do not introduce a second release
identity manifest or duplicate publishing pipeline without a concrete need.
