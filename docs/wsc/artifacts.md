# Artifacts and SDK packaging

For setup and current build defaults, use [DEPLOYMENT.MD](../../DEPLOYMENT.MD).
This reference explains the artifact contract rather than duplicating the
Jenkins configuration checklist.

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
    windows-x64/windows-x64-flutter.zip
    windows-x64-profile/windows-x64-profile-flutter.zip
    windows-x64-release/windows-x64-release-flutter.zip
    android-arm64-release/windows-x64.zip
    ...
  flutter_infra_release/flutter/fonts/<font-version>/fonts.zip
  flutter_infra_release/gradle-wrapper/<wrapper-version>/gradle-wrapper.tgz
  flutter_infra_release/ios-usb-dependencies/arm64_x86_64/...
  flutter_infra_release/flutter/coverage/lcov.info
  download.flutter.io/io/flutter/...
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
Symbols/PDBs are excluded by default; separate symbol retention is an operator
policy, not an automatic diagnostic publication feature of this pipeline.

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

Current HTTP publication uses separate roots: authenticated Bunny storage PUT
and anonymous CDN HEAD/GET. The URL/credential defaults and overrides are listed
only in the [runbook](../../DEPLOYMENT.MD#3-set-folder-properties).

- Jenkins alone receives upload access. The PUT helper sends the secret as
  `AccessKey`, rejects redirects, streams files, and retries bounded failures.
- The download root must preserve relative paths and return file bytes on GET,
  `200` on HEAD for existing files, and `404` for absent files. Login redirects
  and HTML error pages masquerading as success are not acceptable.
- Use TLS trusted by agents and developers. An intranet/VPN can restrict reads;
  the SDK does not inherit Jenkins upload credentials. Noninteractive public
  reads are also possible. Do not expose unauthenticated public writes.
- During WIP iterations, avoid stale CDN caching after overwrites and long-lived
  negative caching. The pipeline does not issue Bunny cache-purge API calls.
- Publication is **not atomic** across targets/hosts. Failed runs may leave
  partial uploads. Only approve a complete tested run for distribution.

Other static servers/object stores can serve this layout. The pipeline also
offers Jenkins FTP/SFTP publishers; their server credentials live in Jenkins
configuration, `TRANSFER_CONFIG_NAME` selects the server, and
`TRANSFER_REMOTE_DIRECTORY` selects its subdirectory. The read side stays HTTP.
A provider-specific signed API needs a different uploader, not different
Flutter download paths. Plain `python -m http.server` cannot receive PUT.

Do not use Jenkins `lastSuccessfulBuild` as the engine root: it is mutable and
build retention is not SDK retention. Jenkins archives are a convenient second
copy of SDK outputs, not the durable mirror contract.

## What seeding does

Before engine builds, when host SDK packaging is selected,
[seed_artifact_mirror.py](../../dev/bots/seed_artifact_mirror.py) HEAD-checks the
download root and stages only missing upstream-owned inputs:

- Material icon fonts and Gradle wrapper, pinned by the corresponding
  `bin/internal/*.version` files. These are not FreeType/font-rendering patches.
- For macOS: pinned `libimobiledevice`, `libusbmuxd`, `libplist`, `openssl`,
  `libimobiledeviceglue`, and `ios-deploy` archives for iOS device support.
- `flutter_infra_release/flutter/coverage/lcov.info`, an unversioned input
  used by upstream packaging's `flutter update-packages`.

Only 404 means missing. Downloads come from upstream Google storage, preserve
their paths, verify the supplied MD5 hash, and log SHA256. The normal uploader
publishes the staged files; a second bounded HEAD check waits for visibility.
Existing files are not replaced or integrity-audited by HEAD. Authentication,
network, or server errors fail the step instead of being treated as absence.

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

`bin/internal/flutter_storage_base_url` is generated from the resolved download
root. The SDK launchers load it only when `FLUTTER_STORAGE_BASE_URL` is not
explicitly set. Developers normally need no mirror environment variable.
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
