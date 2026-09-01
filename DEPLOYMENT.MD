# Deploying this Flutter fork

This fork is intended to be distributed as a normal Flutter SDK: developers
extract an archive, put `flutter/bin` on `PATH`, and use `flutter run` or
`flutter build` without `--local-engine`.

## Recommended release model

Use a small, host-specific SDK archive plus a private HTTPS engine-artifact
mirror.

Build and publish one SDK archive per host operating system and architecture,
for example:

* `flutter-custom-windows-x64.zip`
* `flutter-custom-macos-arm64.zip`
* `flutter-custom-linux-x64.tar.xz`

The SDK archive includes the framework fork, the host Dart SDK, Flutter tool
bootstrap/cache files, and any intentionally pre-cached common artifacts. It
does not need to include every engine target and mode.

Flutter downloads the matching engine artifact lazily when a developer first
needs it. This avoids an oversized archive containing debug, profile, and
release artifacts for every supported target.

## Engine identity

Every framework release must pin the exact engine artifacts it uses in the
tracked `bin/internal/engine.version` file. The value identifies the artifact
set uploaded by CI.

The packaging pipeline must reject a release if its engine artifacts do not
match this pin. Do not use `--local-engine` in the resulting SDK or in its
acceptance tests.

## Artifact mirror

Flutter expects ordinary HTTPS downloads; FTP is not supported. A static HTTP
artifact host is sufficient: an internal object store (S3/MinIO), nginx, or a
stable Jenkins-published-artifact endpoint. No Flutter-specific service or
database is needed.

Publish artifacts in Flutter's usual layout, for example:

```text
https://flutter-artifacts.example.internal/
  flutter_infra_release/flutter/<engine-id>/
    engine_stamp.json
    dart-sdk-windows-x64.zip
    flutter_patched_sdk.zip
    flutter_patched_sdk_product.zip
    flutter-web-sdk.zip
    windows-x64/windows-x64-flutter.zip
    windows-x64-profile/windows-x64-profile-flutter.zip
    windows-x64-release/windows-x64-release-flutter.zip
    android-arm64-release/windows-x64.zip
  download.flutter.io/io/flutter/...
```

The Android Maven repository is the exception to the revision-root layout:
Gradle reads it directly from `<base-url>/download.flutter.io`. The Maven
artifact versions themselves contain the engine ID.

Artifact names and archive contents must match what `flutter_tools` expects.
Publish the engine build's produced artifact ZIPs rather than assembling them
from individual DLLs or executables.

`flutter_patched_sdk.zip` and `flutter_patched_sdk_product.zip` are required
when the fork changes a
public `dart:ui` API. They contain the patched platform summaries used by the
toolchain and IDE analysis, not native runtime DLLs. Build the
`//flutter/build/archives:flutter_patched_sdk` target in debug/profile and
release configurations. Flutter downloads these ZIPs from the engine-revision
root and extracts them into the local `artifacts/engine/common/` cache
directory.

The mirror must be reachable without an interactive login. A private network,
VPN, or transparent service authentication is fine.

## Default mirror configuration

The Flutter tool honors `FLUTTER_STORAGE_BASE_URL`. This fork's launchers first
respect an explicitly set environment variable, then fall back to
`bin/internal/flutter_storage_base_url` when that file exists. The package
creator writes that file from the Jenkins `ARTIFACT_BASE_URL`, so the extracted
SDK uses the private mirror without developer setup while still allowing an
explicit override.

## Jenkins pipeline

Use a multibranch pipeline following the framework and engine revisions after
each upstream rebase. The target matrix is a release policy decision; examples
include Windows host plus Windows desktop, Android ARM/ARM64/x64, and Web.

The repository `Jenkinsfile` implements this pipeline. Its main selectors are
comma-separated `TARGETS` (`android,ios,windows,macos,web`), `MODES`
(`debug,profile,release`), and `HOST_SDKS` (`windows,macos`). Web produces one
SDK artifact and does not vary by runtime mode. SDK assembly deliberately uses
upstream's unfiltered `flutter precache`, so a Windows SDK requires Android,
Web, and Windows artifacts, while a macOS SDK requires Android, iOS, Web, and
macOS artifacts. Both require all three native modes. Use an empty `HOST_SDKS`
value for intentionally partial engine-only builds.

`Jenkinsfile.testing` intentionally starts with a much smaller default while
the pipeline is being commissioned: `TARGETS=windows`, `MODES=debug`, and an
empty `HOST_SDKS`. It uses the `flutter_win` node. macOS, iOS, Android, and Web
work uses `flutter_mac`; this testing pipeline does not require or schedule a
Linux agent. Android debug and Web reuse upstream's host-independent archive
declarations from the Linux-named builder JSON, but execute their GN/Ninja
builds on macOS. Android profile/release use upstream's macOS AOT builder.

### Build reuse policy

`BUILD_POLICY` controls whether engine work is performed:

- `auto` (default) sends an HTTP `HEAD` request for a completion marker. It
  reuses the published artifact set when present and builds otherwise.
- `full_rebuild` deletes `engine/src/out` on each participating build agent,
  invokes the selected engine builds from scratch, and overwrites the
  immutable-revision artifact paths when publishing is enabled.
- `reuse` requires the completion marker and fails immediately when it is not
  available.

Markers are specific to the engine ID and the canonical target, mode, and host
SDK selections. They live below
`jenkins_build_markers/<engine-id>/...` on `ARTIFACT_BASE_URL`. CI publishes the
marker only after the full artifact payload succeeds. Therefore its presence
means that an exact prior matrix completed; merely finding one engine ZIP is
not treated as sufficient.

Server reuse requires `ARTIFACT_BASE_URL`. A local test without an artifact
server may leave `PUBLISH_ENGINE_ARTIFACTS=false`; `auto` then builds, while a
repeated build in the same persistent agent workspace remains incremental and
Ninja reuses unchanged outputs.

Configure Jenkins agents with depot_tools/gclient and the native platform
toolchains. Publishing can use the small HTTP PUT helper, Jenkins Publish Over
FTP, or Publish Over SSH (SFTP). If the artifact server uses a provider-specific protocol such as an S3
API, replace only the publishing step while preserving the staged directory
layout.

The pipeline uses Jenkins `stash`/`unstash` between the build agents and the
separate upload stage. Because a full matrix is large even without symbols,
configure a remote Jenkins Artifact Manager (for example, S3-backed storage)
or change the pipeline to upload each staged tree directly from its build
agent instead of routing stashes through the controller.

### Jenkins setup checklist

1. Create a multibranch Pipeline job pointed at this repository. Jenkins will
   discover and run the checked-in `Jenkinsfile` for each selected branch.
2. Give the agents labels `flutter_win` and `flutter_mac`, or change
   `WINDOWS_AGENT_LABEL` and `MACOS_AGENT_LABEL` to the labels already used by
   the Jenkins installation.
3. Install `depot_tools` (including `gclient`), Git, Python 3, and the native
   build toolchain on every agent. Windows additionally needs Visual Studio and
   the Windows SDK; macOS needs Xcode plus the Android and Web dependencies used
   by the selected engine configurations. Set `WINDOWS_PYTHON` if `python3` is not the
   Python command on Windows. Install Jenkins Publish Over FTP when using
   `UPLOAD_TRANSPORT=ftp`, or Publish Over SSH when using `sftp`.
4. Ensure that every SDK-packaging agent can authenticate to the fork URL
   declared in `dev/bots/prepare_package/common.dart` and fetch the exact commit
   selected by the multibranch job. It currently uses the repository's
   Bitbucket SSH URL. Enable `SYNC_ENGINE_DEPS` unless the agents maintain a
   compatible, already-synchronized engine checkout themselves.
5. Set `ARTIFACT_BASE_URL` to the HTTP(S) download root described below. Select
   `UPLOAD_TRANSPORT=http_put` and configure `UPLOAD_AUTH` plus
   `UPLOAD_CREDENTIALS_ID`, or select `ftp`/`sftp` and set the Jenkins
   `TRANSFER_CONFIG_NAME`.
6. Use a remote Artifact Manager, or enough controller storage and bandwidth,
   for the matrix stashes. Set suitable workspace and build-retention limits;
   engine outputs are large even though the publishing payload omits symbols.
7. Run an intentionally small first build (one target and one mode, with
   `HOST_SDKS` empty), verify upload and download behavior, then enable the full
   release matrix.

The principal release parameters are:

| Parameter | Purpose |
| --- | --- |
| `TARGETS` | Comma-separated engine targets. Testing default: Windows only. |
| `MODES` | Comma-separated native modes. Testing default: debug only. Web does not use this axis. |
| `HOST_SDKS` | Windows and/or macOS host SDK archives. Leave empty for engine-only builds. SDK assembly requires all standard targets for that host and all three modes. |
| `BUILD_POLICY` | `auto`, destructive `full_rebuild`, or strict `reuse`, using exact-matrix completion markers on the HTTP server. |
| `RELEASE_BRANCH` | Channel/branch metadata written into the SDK archive. It is separate from the immutable framework revision. |
| `ARTIFACT_BASE_URL` | HTTP(S) root used by the packager and packaged SDKs for artifact downloads. |
| `PUBLISH_ENGINE_ARTIFACTS` | Allows build/stage validation without changing the artifact mirror. |
| `UPLOAD_TRANSPORT` | `http_put`, `ftp`, or `sftp`. |
| `HTTP_UPLOAD_BASE_URL` | Optional HTTP PUT root when upload and download URLs differ. Empty uses `ARTIFACT_BASE_URL`. |
| `TRANSFER_CONFIG_NAME` | Jenkins Publish Over FTP or Publish Over SSH server configuration name. Credentials live in that Jenkins configuration. |
| `TRANSFER_REMOTE_DIRECTORY` | Optional directory below the configured FTP/SFTP server root. |
| `KEEP_ENGINE_PAYLOAD_IN_JENKINS` | Retains the staged payload as a Jenkins build artifact for diagnostics. |

### Upload endpoint contract

For `UPLOAD_TRANSPORT=http_put`, `dev/bots/upload_artifact_tree.py` treats
`HTTP_UPLOAD_BASE_URL` (or `ARTIFACT_BASE_URL` when it is empty) as a
static-file root. The server must:

- accept HTTP PUT requests to arbitrary nested paths and return a 2xx status;
- allow an identical path to be overwritten safely so a retried Jenkins build
  is idempotent;
- preserve the path below the base URL, especially
  `flutter_infra_release/flutter/<engine-id>/...` and
  `download.flutter.io/...`;
- serve the resulting objects with GET and HEAD to developer machines running
  the packaged SDK; and
- use a TLS certificate trusted by both Jenkins agents and developer machines.

Upload credentials are used only by Jenkins. The Flutter artifact downloader
does not automatically reuse those credentials, so downloads should be
reachable directly (for example, on the company VPN), placed behind transparent
network authentication, or supported by an additional authenticated-download
patch. A provider-specific object-store API or signed-request scheme requires a
different uploader, but the public download paths must retain the same layout.

`HEAD` is an HTTP existence check: it returns the same status and headers as a
`GET`, but without transferring the file body. Flutter uses it when checking
whether a remote artifact exists and expects `200 OK`. Normal static servers
such as nginx, Apache, IIS, and Caddy support it automatically. Verify a mirror
with, for example:

```sh
curl -I https://artifacts.example/flutter/flutter_infra_release/flutter/<engine-id>/flutter_patched_sdk.zip
```

### Hosting and upload alternatives

The upload and download endpoints are deliberately separate. Flutter only sees
`FLUTTER_STORAGE_BASE_URL` and uses HTTP(S) for downloads. Jenkins may publish
the same staged tree by HTTP PUT, FTP, or SFTP.

Jenkins can serve files, but its built-in choices have drawbacks for a durable
Flutter mirror:

- `archiveArtifacts` makes build outputs downloadable over HTTP, but their URLs
  are scoped to a job/build and retention normally follows the Jenkins build.
  Do not use `lastSuccessfulBuild` as an SDK mirror: it can move to a different
  engine revision. A build-number URL works only if that build and its artifacts
  are retained for the lifetime of every corresponding SDK.
- `$JENKINS_HOME/userContent` is exposed under `/userContent/` and can represent
  the required static directory tree. Using it requires a controlled way to
  copy files onto the controller, sufficient controller storage, independent
  retention, and non-interactive read access for SDK users. It is reasonable
  for a small prototype but is not an ideal large-binary artifact repository.

See the Jenkins documentation for
[`archiveArtifacts`](https://www.jenkins.io/doc/pipeline/steps/core/#archiveartifacts-archive-the-artifacts)
and [`userContent`](https://www.jenkins.io/doc/book/managing/user-content/).

Upload and download transports may be different. In particular, Jenkins may
upload via FTP, FTPS, SFTP, or a network share into a directory that an existing
web server exposes via HTTP(S):

```text
Jenkins --FTP/SFTP--> /srv/flutter-artifacts/
                              |
                              +--HTTPS--> https://downloads.example/flutter/
```

Prefer SFTP over unencrypted FTP where the available server supports it. The Jenkins publishing plugins
preserve the staged directory hierarchy. Keep two separate concepts in the
configuration:

```text
TRANSFER_CONFIG_NAME=client-artifact-upload
ARTIFACT_BASE_URL=https://downloads.example/flutter
```

The server named by `TRANSFER_CONFIG_NAME` contains the transfer protocol,
hostname, credentials, and server root in Jenkins global configuration.
`TRANSFER_REMOTE_DIRECTORY` selects a directory below that root. Regardless of
upload transport, preserve
`flutter_infra_release/flutter/<engine-id>/...` and `download.flutter.io/...`
below the HTTP download root. SDK creation must wait until publishing completes,
because its precache step immediately downloads from `ARTIFACT_BASE_URL`.

For each release:

1. Build the engine artifacts for each supported host, target, and build mode.
2. Publish those artifact ZIPs to the HTTPS mirror under the pinned engine ID.
3. Assemble a clean host SDK staging directory using the framework revision.
4. Populate its basic cache/tooling and create the host-specific SDK archive.
5. Publish the SDK archive and a manifest recording framework revision, engine
   revision, host, and included/pre-cached targets.
6. Keep PDBs and other debug symbols as separate Jenkins diagnostic artifacts,
   with an appropriate retention policy. They are not normally required for
   Flutter runtime builds.

SDK assembly uses upstream's `dev/bots/prepare_package.dart` flow. This fork's
only packaging-specific changes are the Bitbucket clone/origin constants and
writing the selected `ARTIFACT_BASE_URL` into the packaged SDK. The launcher
reads that file and exports `FLUTTER_STORAGE_BASE_URL`, so the upstream precache
and Gradle paths all observe the same mirror without separate patches.

The two Python files have narrow roles:

- `collect_engine_artifacts.py` interprets upstream engine builder JSON and
  copies declared archives into Flutter's mirror directory layout. Upstream's
  equivalent is part of LUCI recipes rather than a standalone local command.
- `upload_artifact_tree.py` is used only for `UPLOAD_TRANSPORT=http_put`.
  FTP/FTPS and SFTP use Jenkins plugins directly.

## Release acceptance test

Test each published archive after extracting it into a fresh directory. Do not
pass local-engine arguments. Ideally run this with a clean cache, and test both
the pre-cached and lazy-download paths:

```powershell
flutter doctor
flutter create smoke
Set-Location smoke
flutter build windows
flutter build apk
```

Confirm downloads resolve only from the internal mirror and that the reported
engine revision is the release's pinned engine ID.

## Caveat: optional artifacts

Most standard engine artifacts are ordinary ZIP files. Some optional or
less-common Flutter dependencies use CIPD. A fully pre-cached supported target
matrix avoids needing to mirror those. If the goal expands to supporting
arbitrary future `flutter precache` targets by lazy download, audit the
corresponding tool paths and mirror the required CIPD content as well.
