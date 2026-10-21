# Artifacts and SDK packaging

For setup and current build defaults, use [DEPLOYMENT.MD](../../DEPLOYMENT.MD).
This reference explains the artifact contract rather than duplicating the
Jenkins configuration checklist.

- [Find an SDK or engine artifact](#storage-layout).
- [Check the upload and download endpoints](#upload-and-read-contract).
- [Handle an existing or interrupted publication](#publish-once-policy-and-recovery).
- [Understand packaging and mirror selection](#packaging-and-mirror-selection).
- [Check supported targets](#supported-targets-and-reductions).
- [Plan artifact retention](#environments-and-retention).

## Why SDK archives and an HTTP mirror

The distributed product is one SDK archive per supported host, plus an HTTP(S)
artifact tree. A fork-specific engine ID does not exist in Flutter's public
storage. The mirror is a product dependency, not merely a CI cache.

The upstream-style package creator runs unfiltered `flutter precache`: archives
contain a **warm cache**, not only framework source. Standard artifacts for the
host's supported target set and modes are preloaded. This can produce
multi-gigabyte ZIPs. It is not an all-host/all-future-artifact offline bundle.

Common subsequent HTTP consumers are:

- **Android Gradle builds:** Gradle resolves versioned engine embedding/runtime
  dependencies from the Maven layout at `download.flutter.io`. Gradle is the
  build tool; Maven here describes a repository layout/metadata format, not
  another build step or a separate server. Those downloads are distinct from
  Flutter's warmed `bin/cache` and may be needed on the first `flutter build apk`.
- **Cache repair:** clearing part of `bin/cache`, or a missing cache stamp, can
  make `flutter precache` or a normal build download engine files again.
- **Additional supported artifacts:** commands for content absent from the ZIP
  can request more files. An unimplemented target is not supported merely
  because a download URL exists.

Bundling every platform/configuration and the Maven repository would require a
different distribution contract. Thin packages, bundled Maven, and arbitrary
offline/CIPD mirroring are not implemented. Ordinary developer builds do not
require engine sources, PDBs, or `--local-engine`.

For an explanation of the different IDs and the Android Maven directory mapping,
see [Understanding engine versions and artifact downloads](engine-identity.md).

## Storage layout

The same server/root serves engine artifacts, Maven artifacts, and SDK ZIPs:

```text
<download-root>/
  flutter_infra_release/flutter/<engine-id>/
    engine_stamp.json
    dart-sdk-windows-x64.zip
    sky_engine.zip
    flutter_gpu.zip
    flutter_patched_sdk.zip
    flutter_patched_sdk_product.zip
    flutter-web-sdk.zip
    windows-x64-debug/windows-x64-flutter.zip
    windows-x64-profile/windows-x64-flutter.zip
    windows-x64-release/windows-x64-flutter.zip
    android-arm64-release/windows-x64.zip
    ...
  flutter_infra_release/flutter/fonts/<font-version>/fonts.zip
  flutter_infra_release/gradle-wrapper/<wrapper-version>/gradle-wrapper.tgz
  flutter_infra_release/ios-usb-dependencies/arm64_x86_64/...
  flutter_infra_release/flutter/coverage/lcov.info
  download.flutter.io/io/flutter/...
  wsc-publications/<engine-id>.json
  sdk/<framework-commit>/<Jenkins-build-number>/<host>/
    <archive>.zip
    <archive>.zip.sha256
```

`host` is `windows` or `macos`. Maven versions include the engine ID but live
outside the engine-revision directory. The SDK archive name contains the WSC
version and channel; its containing path is commit/build/host, not a `latest`
alias or a release-name directory. Two jobs publishing the same path need
distinct storage roots if their outputs must remain separate.

Do not hand-assemble runtime ZIP contents. The collector interprets the
checked-in engine CI builder manifests and copies their declared archives.
For Maven, the upstream build emits content-hash filenames and POM versions
inside a Git-revision directory. The collector selects those existing variants
from the current build and moves them into `1.0.0-<content-hash>` directories,
matching upstream upload-recipe behavior. JAR and POM bytes are unchanged; legacy
commit variants and stale incremental-output directories are not published.
Missing files, incorrect POM coordinates, stale GN identity, or conflicting
collected objects fail collection. The publication guard verifies new downloads
against their SHA-256 and reused downloads against the publication receipt.
This verifies publication, not application compilation or rendering.

Standalone `symbols.zip` and `.pdb` outputs are excluded by default. PDBs already
inside Windows runtime ZIPs remain included; the collector does not rewrite
those archives. Separate symbol retention is an operator policy.

### Bootstrap packages versus engine runtimes

`sky_engine.zip` and `flutter_gpu.zip` are generated Dart packages needed by
the framework Pub workspace and Flutter-tool bootstrap. The fork's bootstrap
scripts download these before normal cache initialization. They do not replace
platform runtime binaries.

`flutter_patched_sdk.zip` and `flutter_patched_sdk_product.zip` contain patched
Dart platform summaries (including the fork's public `dart:ui` API). The Flutter
toolchain/IDE uses these; they are not host SDK distribution ZIPs or native DLLs.
They are extracted under `bin/cache/artifacts/engine/common`.

## Upload and read contract

Current HTTP publication uses separate roots: authenticated Bunny storage GET/PUT
and anonymous CDN HEAD/GET. The URL/credential defaults and overrides are listed
only in the [runbook](../../DEPLOYMENT.MD#3-set-folder-properties).

- Jenkins alone receives upload access. The PUT helper sends the secret as
  `AccessKey`, rejects redirects, streams files, and retries bounded failures.
  The publication guard also reads receipts and probes existing files directly
  at this storage origin, with the same credential and without redirects. This
  must be the authoritative, uncached origin, not the public CDN alias.
- The download root must preserve relative paths and return file bytes and
  `200` on anonymous GET/HEAD for existing files, with an exact `Content-Length`
  on both methods, and `404` for absent files. Login redirects
  and HTML error pages masquerading as success are not acceptable.
- Use TLS trusted by agents and developers. An intranet/VPN can restrict reads;
  the SDK does not inherit Jenkins upload credentials. Noninteractive public
  reads are also possible. Do not expose unauthenticated public writes.
- During WIP iterations, avoid stale CDN caching after overwrites and long-lived
  negative caching. The pipeline does not issue Bunny cache-purge API calls.
- Publication is **not atomic** across targets/hosts. Failed runs may leave
  partial uploads. Only approve a complete tested run for distribution.

Other static servers/object stores can serve this layout. Guarded engine
publication currently supports HTTP GET/PUT storage only. The old FTP/SFTP
helpers remain for non-engine transfers, but selecting them for engine
publication fails preflight: do not bypass the guard. Supporting them requires
an equivalent authoritative receipt/read/write adapter. The read side stays HTTP.
A provider-specific signed API needs a different uploader, not different
Flutter download paths. Plain `python -m http.server` cannot receive PUT.

Do not use Jenkins `lastSuccessfulBuild` as the engine root: it is mutable and
build retention is not SDK retention. Jenkins archives are a convenient second
copy of SDK outputs, not the durable mirror contract.

## Publish-once policy and recovery

### Why overwriting caused trouble

The engine ID hashes committed `engine/`, `DEPS`, and the release-candidate
branch version file. It is not a checksum of the resulting binaries. A
framework/CI-only commit can retain that ID while rebuilt archives differ:
the engine embeds its build Git revision, archive metadata can differ, and
machine/toolchain inputs are not all hashed. A release tag alone changes no
engine input. Even a clean build can therefore upload different bytes to the
same engine/Maven URLs.

Overwriting replaces the origin, not copies already in CDN, Gradle, or Flutter
caches. That caused a client build's Maven verification to see an older cached
JAR after a successful PUT. Disabling CDN caching helps testing but cannot
invalidate developers' caches. Clearing only the Maven cache does not refresh
Flutter's separate engine cache. Nor does it restore the original bytes for
an old SDK whose download URLs have been replaced.

Upstream's [release recipe](https://flutter.googlesource.com/recipes/+/refs/heads/main/recipes/release/release_builder.py)
skips engine build/upload when the previous commit has the same content hash.
Its comments assume serialized previous publication; that hash comparison does
not itself check previous upload success. We retain upstream identity and
stable download URLs but check publication explicitly. Per-build download roots
would strand `flutter upgrade` on an old root when Git advances to a new engine.
No upstream hash/parser changes or manually maintained artifact revision are
introduced here.

### Implemented behavior

[publish_engine_artifacts.py](../../dev/bots/publish_engine_artifacts.py) maintains
one small receipt at `wsc-publications/<engine-id>.json`. It contains exact
artifact paths, sizes, SHA-256 values, and a pending-path list. It records
publication, not release approval or another source/version identity.

- Local compilation/collection still runs; Ninja reuse is unchanged.
- Recorded files are reused, not compared with newly compiled bytes. The guard
  confirms origin existence and anonymous HEAD sizes; POM/JSON metadata also
  gets a content-hash check. A CDN-cached copy cannot hide a removed origin file.
- Unrecorded paths must be absent at the origin before ordinary publication.
  New targets/modes add their exact files to the existing inventory; a smaller
  earlier build is not treated as complete coverage for a larger one. Shared
  files are reused, not overwritten by the next target.
- Before any payload write, the guard writes and reads back the pending
  receipt. After every new/replaced file is uploaded, it streams that file
  through the anonymous download URL and verifies SHA-256. This costs one full
  download per newly published file, not per normal reused binary.
- Download verification logs the URL and retries transient connection failures,
  timeouts, interrupted reads and HTTP 404/408/429/500/502/503/504 up to six
  attempts, five seconds apart. Authentication, TLS certificate and integrity
  failures are not retried. These retries do not repeat uploads or rebuilds.
- Only after successful verification is the receipt saved with no pending
  paths. A failed/interrupted publication blocks ordinary publication for that
  engine until reviewed. Unknown files, malformed receipts, unavailable recorded
  files, auth errors and checksum mismatches fail closed; they are not silently
  adopted, overwritten, or repaired.
- One Jenkins `lock` named `wsc-engine-artifact-publication` serializes publisher
  operations across targets and branch jobs on that controller. Compilation is
  still parallel. Install **Lockable Resources**; the resource is automatic.
  Another controller, old pipeline, or manual uploader must not write the same
  root concurrently. Use separate roots for independent Jenkins installations.

The receipt covers its recorded files only, not every possible platform. SDK
matrix validation and packaging still enforce required target coverage. Receipt
updates are not an atomic multi-file deployment, and already-distributed SDKs
do not read the receipt. External modification of supposedly immutable objects
is outside this contract; reused binary HEAD checks are not a full corruption
audit. Keep storage write access restricted.

### Explicit overwrite and first adoption

`DANGEROUSLY_OVERWRITE_BUILD_ARTIFACTS=false` is the default, including tagged
and `full_rebuild` runs. Setting it to `true` replaces **only the selected staged
engine/Maven files**, not the entire server, seed objects or SDK ZIP namespace.
It invalidates completion before replacement and re-verifies downloads before
recording completion. It does not delete Ninja outputs or change `BUILD_POLICY`.

Use it only after reviewing the affected engine ID/root and existing consumers:

1. Stop other writers/consumers while repairing. On a disposable test root,
   disable/purge CDN caching first; the flag does not call the CDN purge API.
2. Check that the selected target's payload contains **all** pending paths;
   unrelated target stages cannot clear pending state. A reduced run with empty
   `HOST_SDKS` can repair payloads that do not require host Android AOT tools.
   For pending Windows/macOS payloads containing those tools, see the limitation
   below before starting a recovery run. A malformed receipt needs manual inspection.
3. Run with the overwrite flag explicitly enabled. A stale CDN response still
   fails verification, even if the old and new payloads have the same length.
4. Return the flag to `false` for ordinary builds. Re-test extracted SDKs; affected
   consumers may need fresh Gradle and Flutter caches. Never treat the flag as
   permission to silently replace an accepted release's binaries.

**Host Android AOT recovery limitation:** empty `HOST_SDKS` omits the original
host-specific Android AOT payload. Selecting the host restores that payload
but requires all modes and that host's standard target set. The pipeline has
no parameter to run the affected target first; its parallel target stages can
reach publication while the engine receipt still lists another target's pending
paths. A controller-wide publication lock serializes writes but does not control
target order. This case
requires a separately reviewed recovery procedure; the reduced-run recipe above
does not cover it.

Existing pre-guard artifact trees have no receipts and will fail as unrecorded.
The Jenkins defaults instead use a fresh, fixed **`ci-v2`** prefix under the
existing testing storage/pull zone. It is not a per-build prefix: retain it
while SDKs depend on it and publish subsequent engines there too. An empty origin
and CDN prefix avoids legacy migration and stale CDN objects without changing
workspace paths or requiring a clean compilation. The first run uploads/seeds that root;
normal subsequent publication can use CDN caching. Explicit URL overrides can
still select an older root, in which case the migration rules below apply.

For **disposable test artifacts**, a reviewed overwrite run performs migration
and creates the receipt. Do not fabricate a complete receipt or automatically
adopt unknown files. Accepted releases need a separately reviewed preservation
or migration plan, not a blanket overwrite.

An environment-only correction that must replace a released engine remains an
explicit release decision: the source hash cannot detect every machine change.
This rare case is deliberately not automated with extra versioning machinery.

## What seeding does

Before engine builds, when host SDK packaging is selected,
[seed_artifact_mirror.py](../../dev/bots/seed_artifact_mirror.py) checks the
authenticated storage origin and stages only missing upstream-owned inputs:

- Material icon fonts and Gradle wrapper, pinned by the corresponding
  `bin/internal/*.version` files. These are not FreeType/font-rendering patches.
- For macOS: pinned `libimobiledevice`, `libusbmuxd`, `libplist`, `openssl`,
  `libimobiledeviceglue`, and `ios-deploy` archives for iOS device support.
- `flutter_infra_release/flutter/coverage/lcov.info`, an unversioned input
  used by upstream packaging's `flutter update-packages`.

Only 404 means missing. Downloads come from upstream Google storage, preserve
their paths, verify the supplied MD5 hash, and log SHA256. The normal uploader
publishes the staged files; a bounded anonymous CDN HEAD check then waits for
visibility. An origin `200` preserves a file without auditing its integrity,
even when the CDN still returns `404`.

Jenkins holds the shared publication lock across the origin checks and uploads,
serializing seed writers on that controller. Other controllers must use separate
storage roots. Seeding requires HTTP PUT and authenticated origin GET; it does
not use engine publication receipts. Authentication, network, or server errors
fail the step instead of being treated as absence.

This is **CI seeding**, not an SDK fallback and not engine-build reuse. Engine
artifacts must come from this fork's builds. Keep the unversioned coverage
snapshot stable; a deliberate refresh needs recorded provenance/checksum.
On an upstream update, audit both changed pins and newly introduced input types.

## Packaging and mirror selection

[prepare_package.dart](../../dev/bots/prepare_package.dart) is invoked with
`--revision`, `--branch`, and `--dry_run`, without `--publish`. Despite the flag's
name, it creates the local SDK ZIP; it does not publish Flutter's public Google
Storage release metadata. Jenkins subsequently validates identity, writes a
SHA256 sidecar, archives the outputs, and uploads the payload.

The creator clones the fork into a clean directory, attaches the selected
channel branch to the exact build revision, bootstraps tools/packages, warms
the cache, and archives it. WSC modifications include the fork origin,
Windows long-path handling, WSC archive identity, and a packaged mirror file.

`bin/internal/flutter_storage_base_url` is tracked with the default download
root `https://fluttertest.b-cdn.net`, so fresh source clones retain the existing
bootstrap artifacts until the new CI root is populated. This source-checkout
default is separate from Jenkins' `ci-v2` default; do not change it to an empty
mirror. Approved FRT baseline URLs also keep their original locations.
SDK packaging overwrites this file in its temporary checkout with
the resolved deployment download root. The Flutter launchers load it only when
`FLUTTER_STORAGE_BASE_URL` is not explicitly set. Set that environment variable
to use another mirror for a local checkout without editing the tracked default.
The selected mirror must contain the artifacts for the checkout's engine pin;
configuring its URL does not publish them. CI does not change the tracked
source-checkout root. After publishing a new pin only to CI's root, source users
must select that populated root before running Flutter. For the CI default,
set this in the PowerShell session:

```powershell
$env:FLUTTER_STORAGE_BASE_URL = 'https://fluttertest.b-cdn.net/ci-v2'
```

If the build used a URL override, use its actual resolved download root instead.
See [local engine development](engine-identity.md#local-engine-development)
for working with local commits and engine builds.
There is no availability fallback from a configured private mirror to public
storage. The fork bootstrap requires a configured root; bypassing/removing
that setup does not make public storage contain the fork's engine ID.

The SDK contains no Jenkins Git credentials. Git operations against its private
Bitbucket origin require the developer's own repository access. Artifact read
access and source-repository access are separate; distributing the ZIP does not
grant either implicitly.

## Supported targets and reductions

The complete packaging matrix follows upstream's unfiltered precache. Modes
are not separate Jenkins cells; Web builds once regardless of `MODES`.
Android debug currently includes ARM, ARM64, x86, and x64. Profile/release use
ARM, ARM64, and x64, plus each SDK host's AOT snapshot tools. Android x86 is
present in upstream engine configuration/precache even though normal app
target choices differ. iOS includes simulator prerequisites even for some
reduced mode selections.

For smoke tests, reduce targets/modes and leave `HOST_SDKS` empty. ABI filtering
is **not a pipeline parameter today**. If adding it, apply it consistently to
runtime, Maven, and host snapshot outputs. On a controlled ARM64 appliance
fleet, verify actual device ABIs (`adb shell getprop ro.product.cpu.abilist`)
before excluding ARM/x64. Default APK/App Bundle builds request multiple ABIs;
an ARM64-only distribution requires an explicit application workflow such as
`--target-platform android-arm64` and its own acceptance tests. Removing profile
also removes the normal performance-profiling workflow.

No Linux host SDK or Linux desktop engine is packaged. A future Linux-developer
SDK for Web needs Linux host tooling and Web artifacts; Linux desktop support
is a separate product choice, but the default unfiltered packager would need
review before promising a reduced Linux SDK.

## Environments and retention

Flutter channel (`main`/`beta`/`stable`) and deployment maturity
(development/staging/production) are separate axes. A stable-based candidate
belongs in staging until accepted. Domain versus path naming is an operations
choice; choose distinct roots where isolation is needed and keep the embedded
download URL stable for the SDK's lifetime.

The pipeline uploads candidates directly and has no production promotion step,
private `releases_*.json` publisher, or tested channel-update service. Initial
distribution uses direct SDK links. Do not promise that `flutter upgrade`
implements a private binary release promotion workflow.

Retain engine, Maven, and pinned global objects while any supported SDK uses
them. A warm cache can hide missing remote files until the next repair or a new
developer's Android build. Never overwrite accepted release artifacts under
the same ID to fix a changed environment; validate a new release namespace or
an explicitly reviewed recovery procedure.
