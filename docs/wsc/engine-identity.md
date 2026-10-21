# Understanding engine versions and artifact downloads

This explains why our Flutter SDK has several different version IDs, how they
fit together, and why Android needs special handling when publishing artifacts.
For the commands used to prepare a release, see
[engine pin maintenance](releases.md#engine-identity). For server paths and
packaging details, see [artifacts and SDK packaging](artifacts.md).

- [Work on the engine locally](#local-engine-development).
- [Prepare a distributable candidate](#preparing-a-distributable-candidate).
- [Look up the version fields](#where-the-ids-are-stored).
- [Diagnose an identity or download failure](#checks-and-troubleshooting).

The historical Maven failure and CI branch-name explanation are at the end.

## Start with the two things we distribute

A Flutter application uses both the **framework** (Dart libraries and tools) and
the **engine** (compiled code that lays out text, draws pixels, and runs Dart).
Our font-rendering changes include engine and dependency patches, so developers
need the engine binaries produced from our fork.

Jenkins distributes a host SDK ZIP and publishes the associated compiled files
to an HTTP(S) server. These downloadable files are called **artifacts**. The SDK
contains a prefilled download cache, but some files are downloaded later. In
particular, Android's build tool, Gradle, downloads engine libraries from a
Maven repository. Here, Maven means a directory layout and dependency metadata;
we do not need a separate Maven server application.

An SDK therefore needs a precise answer to: **which set of engine files should
I download?** A human-readable version such as `wsc-3.44.4-r1` names a release,
but is not the identifier used for those downloads.

## A commit and a content hash answer different questions

| Identifier | Question it answers |
| --- | --- |
| Framework Git revision | Which source commit was selected for this SDK? |
| Engine build Git revision | Which source commit was checked out when the engine was built? |
| Engine content hash | Which committed engine inputs does this engine represent? |

A Git revision changes with every commit, including a framework-only change.
The engine content hash is calculated from the committed `engine/` directory,
`DEPS` dependency specification, and `bin/internal/release-candidate-branch.version`.
It stays the same when those inputs stay the same.

For example, adding a framework fix can produce a new framework revision while
leaving the engine hash unchanged. A previously built engine with that hash can
still be used. Its recorded build revision may then be older than the framework
revision. That difference is expected; forcing the revisions to match would
undermine the reason for having a content hash.

Changing one of our committed Skia/FreeType patch files changes the hash because
those patch files live under `engine/`. Editing an untracked dependency checkout
by hand is not sufficient: its changes must be represented in the committed
patches and dependency inputs before producing a distributable SDK.

The content hash is **not a checksum of the finished binaries** and does not
prove that rendering is correct. Machine configuration and toolchain changes
are not fully captured by it. Artifact checksums, application builds, and FRT
comparisons still serve separate purposes.

Rebuilding identical hashed inputs can change archive bytes without changing
their download ID. Normal publication therefore reuses completed remote files;
it does not overwrite them with the latest local output. See
[publish-once policy and explicit recovery](artifacts.md#publish-once-policy-and-recovery)
for the receipt, cache dilemma, and dangerous overwrite option. A release tag
or `full_rebuild` does not override that policy.

## Where the IDs are stored

The similar filenames below are easy to confuse:

| File or field | Purpose |
| --- | --- |
| `bin/internal/engine.version` | Committed pin: the engine content hash this SDK should download. |
| `bin/cache/engine.stamp` | Generated local copy of the selected download ID. The launcher normally derives it from the pin; Android's Gradle plugin reads it. |
| `bin/cache/engine_stamp.json` | Downloaded build record containing `content_hash`, `git_revision`, and build dates. |
| `engineContentHash` in `flutter --version --machine` | The content hash from that build record. |
| `engineRevision` in the same output | The Git revision from that build record. It is not the download ID. |

For our newly packaged SDKs, the pin, selected download ID, and reported content
hash must agree. The reported engine revision must agree with the build record;
it need not equal the framework revision.

Upstream also supports `FLUTTER_PREBUILT_ENGINE_VERSION` as an explicit override
of the download ID written to `bin/cache/engine.stamp`. The fork's earlier
`sky_engine`/`flutter_gpu` bootstrap reads `bin/internal/engine.version` directly
and does not use this override. Developers normally leave it unset. Setting it
to make a missing download disappear can select a different engine and hide a
packaging mistake. Editing generated cache stamps is likewise not a durable
repair: the launcher can regenerate them.

## Local engine development

A source checkout uses the published engine selected by the tracked
`bin/internal/engine.version` to bootstrap its Dart SDK and tooling. Keep that
pin at a published, compatible version while making local commits. The launcher
uses the tracked pin rather than recalculating it from each local commit.
Select a mirror containing that pin's artifacts before starting the tool or IDE;
see [mirror selection](artifacts.md#packaging-and-mirror-selection).

Use the source revision's [engine setup guide](../engine/contributing/Setting-up-the-Engine-development-environment.md)
and [compilation guide](../engine/contributing/Compiling-the-engine.md) to build
the modified engine locally, then select its outputs with `--local-engine`
and `--local-engine-host`, optionally supplying `--local-engine-src-path`.
See [using the Flutter tool with a local engine](../tool/README.md).
These local builds do not need to be uploaded to the mirror before using the
IDE or running an app with the local engine.

The bootstrap happens before the Flutter tool processes `--local-engine`.
Changing the pin to an unpublished ID can therefore prevent tool and IDE startup
even when local engine outputs exist. Changes to Dart itself or exposed
`dart:ui` APIs may also require a matching local SDK and generated API files;
keeping the bootstrap pin does not guarantee compatibility with arbitrary changes.

## Preparing a distributable candidate

The following steps apply when preparing engine artifacts and an SDK for
publication, including untagged Jenkins candidates. They are not required for
each local development commit.

Source-checkout bootstrap still uses its selected mirror. After CI publishes
the candidate, select that build's download root before retrying Dart/Flutter
commands; the tracked default does not automatically follow Jenkins' `ci-v2`
root. See [mirror selection](artifacts.md#packaging-and-mirror-selection).

1. Commit engine, dependency, and patch-file changes first. The hash is based on
   committed inputs; saving a source edit without committing it is insufficient.
2. Follow [engine pin maintenance](releases.md#engine-identity) to calculate and
   commit the new pin. A framework-only change normally needs no pin change.
3. Build a new candidate SDK with Jenkins. A stale pin now fails preflight even
   for an untagged incremental build. Do not bypass that check with a guessed ID.
4. Test an application using the extracted SDK. Android acceptance should use
   an isolated Gradle dependency cache so previously downloaded libraries cannot
   hide missing server files. See the [SDK acceptance steps](../../DEPLOYMENT.MD#5-accept-the-sdks-before-distribution).
5. Run the required rendering comparison separately. Successful publication and
   compilation do not establish font-rendering equivalence.

Existing SDKs and accepted artifacts retain their original IDs and paths. This
transition requires a new SDK and its matching published artifact tree; editing
an old SDK's pin alone cannot supply the missing artifacts.

## Checks and troubleshooting

| Failure | Meaning and next step |
| --- | --- |
| Preflight says the pin differs from the content hash | Derive the pin again after committing engine inputs. Check the selected source before publishing. |
| Collector rejects `args.gn` revision or hash | Build output does not describe the selected source/context. Inspect the checkout and build invocation; do not relabel stale files. |
| Maven 404 | Compare the exact requested hash, directory, filename, and POM version. Confirm the Android stage published that mode/ABI to the SDK's download root. |
| Gradle rejects an HTTP repository | Transport configuration, separate from version identity. Use HTTPS; any temporary HTTP exception needs a separately agreed local setup. |
| SDK metadata check fails | The packaged pin, downloaded engine record, or generated version metadata disagree. Inspect packaging inputs and caches instead of hand-editing the stamps. |

The pipeline checks source identity, generated outputs, POM coordinates, and
packaged metadata. Publication hashes new downloads through the anonymous
endpoint; reused artifacts are checked against the receipt rather than new
local bytes. These checks establish publication
consistency; they do not replace an extracted-SDK app build or device testing.

Implementation and regression tests live in `dev/bots/engine_identity.py`,
`collect_engine_artifacts.py`, `verify_maven_artifacts.py`, and
`validate_sdk_identity.py`, with corresponding `test_*.py` files and
`test_engine_identity.groovy`. Upstream's
[artifact documentation](../tool/Engine-artifacts.md) and
[Android build definitions](../../engine/src/flutter/shell/platform/android/BUILD.gn)
explain the underlying conventions.

## What went wrong, and why the fix follows upstream

The failure was found while testing Jenkins build 8 on 2026-10-15. These are
historical example IDs, abbreviated for readability:

| Value | Build 8 used |
| --- | --- |
| Selected source/build revision | `723bf605…` |
| Actual engine content hash | `65a21167…` |
| SDK's configured download pin | `f749a74d…` |

Our earlier release procedure pinned the **last engine-changing commit**,
`f749a74d…`. Its engine inputs were identical to those at `723bf605…`, but a
commit SHA is still a different identifier from their content hash.

The collector put ordinary engine ZIPs under that configured pin. For Android,
it copied the generated Maven directory as-is. Gradle consequently requested
`1.0.0-f749a74d…`, while the Maven files were published under a directory named
`1.0.0-723bf605…`. The request returned 404 even though Android compilation and
artifact upload had succeeded.

Upstream already generates another set of Maven filenames and POMs using the
content hash. A **POM** is the small XML file declaring a library's identity and
dependencies; a **JAR** contains the library payload. The intermediate build
layout intentionally puts the content-hash variants inside the commit directory.
Upstream's upload recipes then place them in their final content-hash directory.
Our collector was missing that publication step.

Using `G` for the build revision and `H` for its engine content hash:

```text
Generated file:
  download.flutter.io/io/flutter/<library>/1.0.0-G/<library>-1.0.0-H.pom

Published file requested by Gradle:
  download.flutter.io/io/flutter/<library>/1.0.0-H/<library>-1.0.0-H.pom

The POM already declares version 1.0.0-H. JAR files follow the same mapping.
```

The corrected pipeline pins `H`, publishes ordinary engine artifacts under
`flutter_infra_release/flutter/H/`, and applies this Maven directory mapping.
It copies the existing content-hash POM and JAR bytes unchanged. It selects only
the current build's variants, excluding old directories left by incremental
builds.

We chose this over rewriting POM versions to fit our old commit-based pin. That
alternative would preserve a fork-specific convention and make us responsible
for translating metadata whenever upstream changes its packaging. The fix
instead adapts our Jenkins integration and collector to upstream's existing
artifact identities. Upstream hashing, GN generation, Maven generation, and
SDK download scripts remain unchanged.

## Why Jenkins uses a special local branch name

Upstream's hash helper does not always hash the checked-out sources. On some
development branches it hashes the **merge-base**: the shared ancestor between
the local branch and an upstream branch. This helps upstream contributors use
existing engine artifacts while doing local development.

That is unsuitable when publishing our patched engine: it could identify the
upstream ancestor instead of our fork's engine inputs.

Jenkins therefore attaches the already-selected commit to the local branch
`flutter-wsc-candidate.ci`. The name matches upstream's `flutter-*-candidate.*`
rule, under which the helper hashes the checked-out commit. This is a local CI
checkout detail. It does not select another commit, rename the public WSC
branch, move a release tag, or change the packaged SDK channel.

For developers working on arbitrary branch names, `dev/bots/engine_identity.py`
calculates the same upstream hash operation explicitly at committed `HEAD`.
It does not switch branches or write the pin. Tests compare its result with
the unmodified upstream helper in the CI branch context. The collector also
checks the hash actually emitted by GN, so a mistaken build context fails before
publication rather than silently labeling artifacts with the wrong ID.

Packaging checks out the exact framework SHA selected at the start of the build,
even if someone pushes another commit to the branch during compilation. The
validator rejects a checkout whose `HEAD` differs from `--revision` before
reading its pin or calculating its hash. All of those checks therefore refer to
the same source revision.

The Python helper also preserves upstream's Apple Git compatibility workaround:
it adds `-c core.multiPackIndex=false` to the `git ls-tree` command when Git
identifies itself as Apple Git. This handles an older Xcode Git reading an index
written by newer Git; it changes neither repository nor machine configuration.
See [upstream issue 184376](https://github.com/flutter/flutter/issues/184376).
