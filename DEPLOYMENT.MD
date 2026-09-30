# Deploying this Flutter fork

This fork is intended to be distributed as a normal Flutter SDK: developers
extract an archive, put `flutter/bin` on `PATH`, and use `flutter run` or
`flutter build` without `--local-engine`.

## Recommended release model

Use a host-specific SDK archive plus a private HTTPS engine-artifact mirror.

Build and publish one SDK archive per host operating system and architecture,
for example:

* `flutter-custom-windows-x64.zip`
* `flutter-custom-macos-arm64.zip`

The current pipeline produces Windows x64 and macOS arm64 SDK archives. The
Linux agent builds Android and Web engine artifacts; having a Linux build agent
does not require distributing a Linux host SDK.

The SDK archive includes the framework fork, the host Dart SDK, Flutter tool
bootstrap/cache files, and pre-cached artifacts. Keeping one archive per host
avoids a single all-host mega-archive, but does not necessarily make each ZIP
small.

The current pipeline deliberately uses upstream's package creator unchanged in
this respect. It runs an unfiltered `flutter precache`, warms the SDK cache, and
can therefore produce multi-gigabyte host archives. A future thin-package mode
could omit selected cache contents and let Flutter download them lazily from
the mirror, but that is not implemented today and would need explicit
acceptance testing. The mirror is still required for Android Maven artifacts,
cache repair, and artifacts not present in the packaged cache.

## Engine identity

Every framework release must pin the exact engine artifacts it uses in the
tracked `bin/internal/engine.version` file. The value identifies the artifact
set uploaded by CI.

The packaging pipeline must reject a release if its engine artifacts do not
match this pin. Do not use `--local-engine` in the resulting SDK or in its
acceptance tests.

## Artifact mirror

The artifact mirror is part of the distributed fork, not merely an optional CI
cache. A packaged SDK is pinned to a fork-specific engine ID, and Flutter's
public storage does not contain artifacts for that ID.

Flutter expects ordinary HTTP(S) downloads using GET and HEAD; FTP and SFTP are
not download protocols for the Flutter tool. A static HTTP artifact host is
sufficient: an internal object store (S3/MinIO), nginx, Apache, IIS, Caddy, or
an existing web space. No Flutter-specific service or database is needed.

Upload and download access should be separated. Developer machines need
non-interactive read access, normally on the company network or VPN. Only
Jenkins should receive write access, using authenticated HTTP PUT, SFTP, or
another server-side publishing mechanism. Never expose an unauthenticated PUT
endpoint publicly.

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
  flutter_infra_release/flutter/fonts/<font-version>/fonts.zip
  flutter_infra_release/gradle-wrapper/<wrapper-version>/gradle-wrapper.tgz
  flutter_infra_release/ios-usb-dependencies/arm64_x86_64/...
  flutter_infra_release/flutter/coverage/lcov.info
  download.flutter.io/io/flutter/...
  wsc-sdk/<release-name>/
    flutter_windows_<release-name>.zip
    flutter_macos_<release-name>.zip
    SHA256SUMS
```

The host SDK ZIPs may be served by the same web server and from the same
storage root as the engine mirror. Keep them in their own subtree because SDK
release names and retention differ from engine artifact IDs.

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

`sky_engine.zip` and `flutter_gpu.zip` are also required at the engine-revision
root. They are generated Dart packages needed to resolve the framework's Pub
workspace and build the Flutter tool in a clean SDK checkout. This fork's
bootstrap scripts download just these two packages before normal Flutter cache
initialization takes over. They are build/bootstrap inputs, not replacements
for the platform-specific engine archives.

Some universal artifacts are pinned outside the engine-ID tree and are not
produced by an engine build. For this checkout they are identified by
`bin/internal/material_fonts.version` and
`bin/internal/gradle_wrapper.version`. Seed those exact immutable upstream
objects into the mirror before SDK packaging. Preserve their complete relative
paths, verify their upstream hashes, and repeat this check after every upstream
rebase because the pins can change. Do not solve a missing global object by
adding an automatic fallback to public storage.

macOS SDK packaging also precaches Flutter's pinned iOS device-support tools:
`libimobiledevice`, `libusbmuxd`, `libplist`, `openssl`,
`libimobiledeviceglue`, and `ios-deploy`. Their revisions are recorded in the
corresponding `bin/internal/*.version` files. Mirror each upstream ZIP without
changing its relative path:

```text
flutter_infra_release/ios-usb-dependencies/arm64_x86_64/
  <artifact>/<version>/<artifact>.zip
```

Snapshot and checksum this complete set for every upstream rebase. These are
upstream-owned, version-pinned packaging inputs; the engine target builds do
not generate or publish them.

Upstream's SDK packager also runs `flutter update-packages`, which downloads
`flutter_infra_release/flutter/coverage/lcov.info`. Unlike the two version-file
artifacts above, that upstream path is not content-versioned. Snapshot the
verified upstream object into the private mirror for each release and record
its checksum with the release inputs. Existing SDK operation does not depend on
continually replacing it with the newest upstream object.

The mirror must be reachable without an interactive login. A private network,
VPN, or transparent service authentication is fine.

## Default mirror configuration

The Flutter tool honors `FLUTTER_STORAGE_BASE_URL`. This fork's launchers first
respect an explicitly set environment variable and otherwise load
`bin/internal/flutter_storage_base_url` when that file exists. The package
creator writes that file from the Jenkins `ARTIFACT_BASE_URL`, so the extracted
SDK uses the private mirror without developer setup while still allowing an
explicit override.

There is no availability fallback from the configured private mirror to
Flutter's public Google storage. A missing object, HTTP error, or unreachable
mirror makes the Flutter command fail. The upstream Google URL is only the
default when `FLUTTER_STORAGE_BASE_URL` is entirely absent, such as after
removing the packaged configuration or bypassing the SDK launcher. Even then,
the public mirror normally cannot satisfy this fork's engine ID.

The fork's bootstrap scripts are stricter: they require either the environment
variable or the packaged mirror file and fail immediately when neither exists.

This does not by itself make CI fully air-gapped. `gclient sync`, source
checkouts, toolchain downloads, and the Windows packager's current Mingit URL
may still use upstream internet services. Mirror those inputs separately if an
offline build environment becomes a requirement.

## Jenkins pipeline

Use a multibranch pipeline following the framework and engine revisions after
each upstream rebase. The target matrix is a release policy decision; examples
include Windows host plus Windows desktop, Android ARM/ARM64/x64, and Web.

The current commissioning implementation is `Jenkinsfile.testing`. Configure
the multibranch job's script path explicitly; this keeps the team's default
`Jenkinsfile` untouched until the pipeline is ready to be promoted. Its main
selectors are comma-separated `TARGETS` (`android,ios,windows,macos,web`), `MODES`
(`debug,profile,release`), and `HOST_SDKS` (`windows,macos`). Web produces one
SDK artifact and does not vary by runtime mode. SDK assembly deliberately uses
upstream's unfiltered `flutter precache`, so a Windows SDK requires Android,
Web, and Windows artifacts, while a macOS SDK requires Android, iOS, Web, and
macOS artifacts. Both require all three native modes. Use an empty `HOST_SDKS`
value for intentionally partial engine-only builds.

`Jenkinsfile.testing` intentionally starts with a smaller default while the
pipeline is being commissioned: `TARGETS=windows,macos`, `MODES=debug`, and an
empty `HOST_SDKS`. Windows uses `flutter_win`, macOS and iOS use
`flutter_macos`, and Android and Web use `flutter_linux`. The Android and Web
builders are upstream Linux release configurations. In the current pipeline,
the Linux agent produces the complete Android target runtime, JAR, Maven, and
Web artifact sets. Host SDK packaging additionally builds the smaller
host-specific Android AOT snapshot tools on Windows or macOS; it does not
rebuild the complete Android engine on those host agents.

This is a current CI/release-layout choice, not a claim that Android or Web can
only be cross-compiled from Linux. Their target artifacts are consumed by
developers on every host. Upstream declares the complete release archives in
`linux_android_debug_engine.json`, `linux_android_aot_engine.json`, and
`linux_web_engine_build.json`, while the Windows and macOS Android builders
declare only their host-specific AOT tools. Using those manifests lets the
collector publish the exact upstream archive layout without maintaining a
second list.

Eliminating the Linux agent is possible in principle. macOS is the more
plausible replacement, but it would require expanding its builders to produce
the complete Android runtime/JAR/Maven archives, adding or adapting an archive
manifest, validating Web/emsdk output, and comparing clean-build artifacts and
SDK behavior with the upstream Linux path. Windows has the larger compatibility
gap because upstream specializes its Android configuration for host
`gen_snapshot`, and complete release builds encounter Unix-oriented actions.
This is therefore a deliberate CI customization, not a label substitution.
It would also move substantial work and disk usage onto the macOS agent that
already builds macOS and iOS.

The Linux Android AOT manifests also publish Linux-host `gen_snapshot` and
analyze-snapshot archives. Those host tools are unnecessary while no Linux SDK
is supported and may be filtered as a small publishing optimization. The
Android target runtime/Maven artifacts and Web SDK archive remain required for
the Windows and macOS SDKs.

Engine targets are a real Declarative Pipeline matrix axis. Invalid
target/agent pairs are excluded, leaving Windows on `flutter_win`, macOS and
iOS on `flutter_macos`, and Android and Web on `flutter_linux`. `TARGETS`
filters the static axis before an agent is allocated.

Runtime mode is intentionally not a second matrix axis. A target's selected
debug/profile/release configurations run sequentially in one matrix cell and
workspace. This shares checkout, `gclient sync`, host bootstrap configurations,
simulator prerequisites, and persistent Ninja outputs instead of repeating
them in separate mode cells. Web ignores the mode list and builds once.

### Choosing a reduced build matrix

Distinguish quick engine validation from publishing a generally usable SDK.
For routine smoke builds, select only the targets and modes under test and
leave `HOST_SDKS` empty. For a closed Android appliance fleet, an ARM64-only
debug/release smoke build is a reasonable minimum. Keep ARM64 profile available
as an on-demand or scheduled build: debug-mode timings are not representative,
and profile mode is the supported way to diagnose frame-time and startup
problems on the real smart-board hardware.

Before declaring the fleet ARM64-only, check every supported board model:

```sh
adb shell getprop ro.product.cpu.abilist
```

Do not infer the device ABI merely from the Windows or Linux architecture of
the build agent. The Android artifact ABI is the target device ABI.

The current Android list is hard-coded in `Jenkinsfile.testing`. If an
`ANDROID_ARCHS` parameter is added, apply it consistently to Android debug
engine builds, Android AOT engine builds, and the host-specific AOT snapshot
artifacts built for each packaged SDK.

Reduction candidates and their consequences are:

- `android_debug_x86` (32-bit x86) is an upstream engine CI configuration and
  remains part of `flutter precache --android`, but the current Flutter tool's
  ordinary APK/App Bundle target choices do not include x86. It is therefore
  the safest first omission from a smoke-only build when no old 32-bit Android
  emulator is supported. Do not omit it from the current unfiltered SDK
  packaging flow.
- Android x64 can be omitted when developers use neither x86_64 emulators nor
  x86_64 target devices.
- 32-bit ARM can be omitted only when all supported physical devices are
  ARM64 and the application build is explicitly restricted accordingly.
- Omitting profile removes `flutter run --profile` and useful DevTools
  performance analysis for that target. Prefer making it on-demand instead of
  removing it from the published product contract.
- Web has one release-style engine build and already ignores `MODES`.

Vanilla `flutter build apk` and `flutter build appbundle` currently default to
Android ARM, ARM64, and x64. If the private mirror publishes only ARM64, those
commands can request missing artifacts. Projects must then consistently use,
for example, `--target-platform android-arm64`, and acceptance tests must cover
that workflow. This is a visible SDK policy change, not merely a CI
optimization.

Likewise, upstream SDK assembly performs an unfiltered precache. The current
pipeline therefore requires all standard targets and all three modes when
`HOST_SDKS` is non-empty. Keep the complete matrix for official, drop-in SDK
publishing unless the packager and developer workflow are intentionally changed
and documented together. A practical compromise is a reduced per-commit smoke
matrix plus a complete release or scheduled publication matrix.

Each matrix cell uses a deterministic custom workspace below the agent root:

```text
engine-workspaces/<Jenkins JOB_NAME>/<BUILD_TARGET>
```

Including the full multibranch `JOB_NAME` prevents different branches from
sharing incompatible outputs, while the target suffix prevents target cells
from reconfiguring each other's GN output directories. This also avoids
executor-dependent `@2`/`@3` workspace allocation, so `engine/src/out` is
available to the same branch and target on later runs. The pipeline deletes
only `build/artifact-payload` during normal `incremental` builds;
`full_rebuild` is the explicit operation that removes `engine/src/out`.

Temporary local exception: `wsc-main-3.44.4` hardcodes the existing
`engine-workspaces/flutter_wsc/jenkins_build/<BUILD_TARGET>` paths in
`Jenkinsfile.testing` to preserve Ninja's absolute paths during consolidation
testing. There is no workspace override parameter. Restore `${JOB_NAME}` before
forward-porting or deploying to the client. Keep the old `jenkins_build` job
stopped, suppress automatic SCM/indexing builds, and check queued builds before
running the new branch. `disableConcurrentBuilds()` only serializes one job;
there is no cross-job lock. Use `BUILD_POLICY=incremental` and, after confirming
that dependencies and patches match, `SYNC_ENGINE_DEPS=false`. No directory
move or copy is needed, though revision changes may still cause relinking.

### Build policy and release profiles

`BUILD_POLICY` controls local workspace reuse:

- `incremental` (default) always invokes the selected engine builds while
  preserving `engine/src/out`, allowing GN and Ninja to reuse valid local
  outputs.
- `full_rebuild` deletes `engine/src/out` on each participating build agent,
  then invokes the selected builds from scratch.

Neither policy consults the artifact server to suppress a build. This avoids
reusing output after an untracked agent or toolchain change. Use three simple
profiles:

- A smoke build uses `incremental`, a reduced target/mode selection,
  `PUBLISH_ENGINE_ARTIFACTS=false`, and an empty `HOST_SDKS`.
- An SDK integration build uses `incremental`, the complete matrix required by
  the selected `HOST_SDKS`, and publishes to a staging mirror. The resulting
  SDK exercises the same download flow as a developer installation.
- A production release uses `full_rebuild`, `SYNC_ENGINE_DEPS=true`, the
  complete matrix, and the production mirror.

The pipeline compares `bin/internal/engine.version` with Flutter's existing
`last_engine_commit` calculation. A mismatch is a warning for incremental
staging builds, but a clean publishing build fails before compilation. This
prevents different engine source revisions from sharing a production artifact
namespace. The release-resolution workspace uses a full-history checkout so
that calculation cannot mistake the tip of a shallow clone for the last engine
commit. The large per-target engine workspaces remain separate, persistent,
and eligible for shallow checkout and incremental Ninja reuse.

Do not enable Jenkins Git options such as "Wipe out repository before build"
or an external workspace cleanup step for this job. They defeat local reuse.
These custom workspaces are deliberately outside normal build-number rotation;
clean obsolete branch directories explicitly when branches are deleted or disk
pressure requires it.

Configure Jenkins agents with depot_tools/gclient and the native platform
toolchains. Publishing can use the small HTTP PUT helper, Jenkins Publish Over
FTP, or Publish Over SSH (SFTP). If the artifact server uses a provider-specific
protocol such as an S3 API, replace only the publishing step while preserving
the staged directory layout.

Each target agent publishes its collected tree directly to the artifact
server. Jenkins does not route the multi-gigabyte engine payload through
`stash`/`unstash`. The SDK stage begins only after every requested matrix cell
has built and uploaded successfully.

### Jenkins setup checklist

1. Create a multibranch Pipeline job pointed at this repository. While the
   pipeline is being commissioned, set its script path to `Jenkinsfile.testing`.
   Do not add a repository-root `Jenkinsfile` yet: that could be discovered by
   the client's existing Jenkins setup before commissioning is complete. When
   the pipeline has been accepted for production, promote the tested
   `Jenkinsfile.testing` implementation to `Jenkinsfile` in a controlled
   change. Do not maintain separate staging and production copies of the
   pipeline logic.
2. Give the agents labels `flutter_win`, `flutter_macos`, and `flutter_linux`.
   If those labels ever change, update the matrix axis/exclusions and the
   non-matrix agent declarations in `Jenkinsfile.testing` together.
3. Install `depot_tools` (including `gclient`), Git, Python 3, Java 21 for the
   Jenkins agent, and the native build toolchain on every agent. The current
   Linux commissioning baseline is Ubuntu 26.04 LTS. A regular Linux VM or
   WSL2 can build the artifacts; for production, choose whichever the
   operations team can keep running as a persistent service with stable storage
   and networking. It does not need Android Studio.
4. Windows additionally needs Visual Studio 2022, the Windows SDK, Debugging
   Tools for Windows for every built host architecture, and a `7za` executable
   on `PATH` for upstream SDK packaging. Installing 7-Zip may provide `7z.exe`
   rather than `7za.exe`; verify the command name actually used by the
   packager. The inner SDK checkout enables `core.longpaths`, but the Jenkins
   service account and filesystem must still support long paths.
5. macOS needs Xcode and enough free space for macOS and iOS outputs. If the
   Jenkins Git client is launched with
   `-Dorg.jenkinsci.plugins.gitclient.CliGitAPIImpl.useSETSID=true`, ensure
   `setsid` is on the agent process's `PATH` and restart the agent after changing
   its Java options or environment.
6. Set `WINDOWS_PYTHON` if `python3` is not the Python command on Windows.
   Install Jenkins Publish Over FTP when using `UPLOAD_TRANSPORT=ftp`, or
   Publish Over SSH when using `sftp`.
7. Ensure that every SDK-packaging agent can authenticate to the fork URL
   declared in `dev/bots/prepare_package/common.dart` and fetch the exact commit
   selected by the multibranch job. It currently uses the repository's
   Bitbucket SSH URL. Use a repository access/deploy key or a dedicated
   read-only service account. Store the private key and, if it is encrypted,
   its passphrase in Jenkins credentials; never put either in the Jenkinsfile.
   The clone must complete non-interactively under the agent service account.
   Note that the upstream package creator performs a second, raw SSH clone into
   its temporary packaging directory. A Jenkins SCM checkout credential is not
   automatically guaranteed to cover that subprocess; expose the same
   credential to the packaging step with an SSH-agent wrapper or otherwise
   provision non-interactive read access for the service account.
8. Configure SSH host-key verification. Pinning Bitbucket's published host key
   in `known_hosts` is preferable for production. Jenkins's "Accept first
   connection" strategy is a reasonable bootstrap option on a controlled new
   agent, but it trusts that first network connection. The raw packaging clone
   must also see a valid `known_hosts` entry. Test SSH as the service account
   rather than only from an administrator's terminal.

   On a controlled first connection, run this as the agent OS user to populate
   the normal OpenSSH `known_hosts` file:

   ```sh
   install -d -m 700 "$HOME/.ssh"
   ssh -o StrictHostKeyChecking=accept-new -T git@bitbucket.org
   chmod 600 "$HOME/.ssh/known_hosts"
   ```

   For stronger production verification, obtain Bitbucket's published host-key
   fingerprint independently, compare it before accepting the key, and then
   pin the verified key instead of trusting the first connection.
9. Enable `SYNC_ENGINE_DEPS` for production and whenever a persistent checkout
   may be missing or stale. Disable it only for deliberate, short incremental
   test cycles against an already-synchronized workspace.
10. Set `ARTIFACT_BASE_URL` to the HTTP(S) download root described below. Select
   `UPLOAD_TRANSPORT=http_put` and configure `UPLOAD_AUTH` plus
   `UPLOAD_CREDENTIALS_ID`, or select `ftp`/`sftp` and set the Jenkins
   `TRANSFER_CONFIG_NAME`.
11. Give each build agent network access and upload credentials for the selected
   artifact transport. Set suitable workspace and artifact-server retention
   limits; engine outputs are large even though the publishing payload omits
   symbols.
12. Run an intentionally small first build (one target and one mode, with
   `HOST_SDKS` empty), verify upload and download behavior, then enable the full
   release matrix.

The principal release parameters are:

| Parameter | Purpose |
| --- | --- |
| `TARGETS` | Comma-separated engine targets. Testing default: Windows and macOS. |
| `MODES` | Comma-separated native modes. Testing default: debug only. Web does not use this axis. |
| `HOST_SDKS` | Windows and/or macOS host SDK archives. Leave empty for engine-only builds. SDK assembly requires all standard targets for that host and all three modes. |
| `BUILD_POLICY` | `incremental` preserves local Ninja outputs; `full_rebuild` deletes `engine/src/out` first. Neither skips work based on remote artifacts. |
| `RELEASE_BRANCH` | Channel/branch metadata written into the SDK archive. It is separate from the immutable framework revision. |
| `ARTIFACT_BASE_URL` | HTTP(S) root used by the packager and packaged SDKs for artifact downloads. |
| `PUBLISH_ENGINE_ARTIFACTS` | Uploads each selected target directly from its build agent. Required when `HOST_SDKS` is non-empty. |
| `UPLOAD_TRANSPORT` | `http_put`, `ftp`, or `sftp`. |
| `HTTP_UPLOAD_BASE_URL` | Optional HTTP PUT root when upload and download URLs differ. Empty uses `ARTIFACT_BASE_URL`. |
| `TRANSFER_CONFIG_NAME` | Jenkins Publish Over FTP or Publish Over SSH server configuration name. Credentials live in that Jenkins configuration. |
| `TRANSFER_REMOTE_DIRECTORY` | Optional directory below the configured FTP/SFTP server root. |

### Upload endpoint contract

For `UPLOAD_TRANSPORT=http_put`, `dev/bots/upload_artifact_tree.py` treats
`HTTP_UPLOAD_BASE_URL` (or `ARTIFACT_BASE_URL` when it is empty) as a
static-file root. The server must:

- accept HTTP PUT requests to arbitrary nested paths and return a 2xx status;
- allow an identical path to be overwritten safely while an unreleased build
  is retried;
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

Prefer SFTP over unencrypted FTP where the available server supports it. The
Jenkins publishing plugins preserve the staged directory hierarchy. Keep two
separate concepts in the configuration:

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

### Publishing host SDK archives

The engine mirror and the downloadable SDK ZIPs can share one server and one
Jenkins upload credential. Keep their URL namespaces separate, for example:

```text
https://downloads.example/flutter/flutter_infra_release/flutter/<engine-id>/...
https://downloads.example/flutter/download.flutter.io/...
https://downloads.example/flutter/wsc-sdk/<release-name>/flutter_windows_<release-name>.zip
https://downloads.example/flutter/wsc-sdk/<release-name>/flutter_macos_<release-name>.zip
```

The current `Jenkinsfile.testing` publishes the engine artifact trees but only
stores completed SDK archives with Jenkins `archiveArtifacts`. It does not yet
copy the SDK ZIPs into `wsc-sdk/`. Before production, add a small promotion or
upload step for the ZIPs and their SHA-256 checksums. The upload must occur only
after packaging and acceptance checks succeed; a failed build must not replace
the currently advertised release.

Direct download links are sufficient for an initial internal distribution.
Flutter channel metadata such as `releases_windows.json` and
`releases_macos.json` is only needed if the client wants upstream-style channel
discovery or automated `flutter upgrade` behavior.

Retain an engine artifact set for at least as long as any distributed SDK pins
its engine ID. Deleting an old engine directory can break a still-installed SDK
the next time a developer clears or repairs their local cache.

## Rebasing onto a new upstream Flutter version

Treat an upstream update as a new release line. Perform it on a temporary
integration branch, keep the previous published release intact, and record the
old fork commit, the selected upstream tag/commit, and the resulting fork
commit. Do not overwrite artifacts belonging to the previous engine ID.

The source update and the binary release are separate checkpoints. First make
the rebased source tree and its nested dependency patches reproducible; only
then assign the engine ID and run the clean release build.

### 1. Move the fork changes onto the selected upstream revision

1. Fetch upstream tags and verify the chosen Flutter tag or commit. Prefer an
   upstream stable tag unless a specific unreleased fix is required.
2. Create an integration branch at that revision. Replay the WSC commits with
   the team's normal rebase or cherry-pick workflow; do not experiment on the
   currently published release branch.
3. Resolve framework conflicts narrowly. Preserve upstream behavior unless a
   difference is an intentional WSC requirement. Pay particular attention to
   the SDK launcher, bootstrap, package-creation, artifact-layout, and version
   code modified by this fork.
4. Review the complete resulting diff against the selected upstream revision,
   including untracked files. A clean conflict resolution is not proof that an
   old customization is still necessary or correct.

### 2. Refresh the engine dependency patch stack

The Skia and FreeType sources are DEPS-managed nested checkouts. An upstream
Flutter update may move either dependency even when the WSC patch files have no
Git conflict in the outer repository.

1. Start from a clean engine dependency checkout and run `gclient sync` for the
   new source revision. The WSC pre-sync hook resets only patch-owned nested
   changes; stop and inspect rather than discarding unrelated dirty files.
2. Record the new nested revisions with `git rev-parse HEAD` in
   `engine/src/flutter/third_party/skia` and
   `engine/src/flutter/third_party/freetype2`.
3. Apply the files under
   `engine/src/flutter/tools/wsc_font_rendering_patches` in their declared
   order. If a patch no longer applies, port its intent onto the new dependency
   source and regenerate that patch from the pristine dependency revision.
   Do not use fuzz or a blanket conflict acceptance for rendering changes.
4. Update `EXPECTED_SKIA_REVISION` and `EXPECTED_FREETYPE_REVISION` in
   `apply_patches.py` only after the revised stack applies and the behavior has
   been reviewed. Also update `GROUP_MARKERS` when a patch adds, removes, or
   relocates its identifying code; those markers are how repeated application
   is detected.
5. Prove both paths: a clean sync followed by patch application, and a second
   application that correctly reports the selected patches already applied.
   Run the relevant rendering/layout tests before treating the source rebase as
   complete.

The Material Fonts archive is not part of this patch stack. It contains the
cached Material icon font used by Flutter applications; it is not the FreeType
library or WSC's font-rendering implementation.

### 3. Audit pinned downloads and build prerequisites

Compare the rebased `bin/internal/*.version` files with the previous release.
Some contain versions, while others contain complete paths below Flutter's
storage root. At minimum, verify:

- `material_fonts.version`, which points to the immutable `fonts.zip` extracted
  into `bin/cache/artifacts/material_fonts`;
- `gradle_wrapper.version`, which points to the immutable archive containing
  `gradlew`, `gradlew.bat`, and `gradle-wrapper.jar`; and
- any newly added path-valued version file used by `flutter precache` or SDK
  bootstrap.

If a pointer changed, download the exact upstream object, verify its published
hash or checksum, and place it at the identical relative path in the private
mirror. A pointer that did not change requires no republishing. Keep old
objects: an already-distributed SDK can continue to request them. Verify every
referenced object with HTTP HEAD from each packaging agent before starting the
SDK build; do not introduce a fallback to public storage.

Also refresh and record the checksum of the unversioned
`flutter_infra_release/flutter/coverage/lcov.info` snapshot used by
`flutter update-packages`. Treat that snapshot as an explicit release input;
do not let it change silently during a production build.

Also compare the new Flutter release's documented toolchain requirements with
the installed Jenkins agents: Xcode and macOS SDK, Visual Studio and Windows
SDK, Android SDK/NDK and Java, Ubuntu packages, Python, Git, and depot_tools.
Environment changes can alter outputs without changing the source revision, so
record the toolchain versions used for a production release.

### 4. Assign the engine identity

Finish and commit all engine-affecting source, DEPS, patch, and build changes
before updating `bin/internal/engine.version`. Calculate the expected revision
using the repository scripts:

```sh
bin/internal/last_engine_commit.sh
```

or on Windows:

```powershell
bin\internal\last_engine_commit.ps1
```

Write that full commit ID to `bin/internal/engine.version`, commit the update,
and rerun the command. The pipeline performs the same comparison and rejects a
mismatch for a clean publishing build. If another engine-affecting change is
committed afterward, repeat this step and publish under the new ID rather than
overwriting a release under an inaccurate identity.

### 5. Validate and publish the new release line

1. Use the staging job to build and test the intended source revision. It may
   use persistent incremental workspaces while the release is being prepared,
   but it must build the complete target/mode matrix required by the selected
   host SDKs before its candidate archives are accepted.
2. Publish the candidate engine and Maven artifacts into the staging mirror,
   then create the Windows and macOS SDK archives from that exact framework
   revision. Candidate archives carry an automatically derived WSC pre-release
   identity, so they cannot be mistaken for a final release.
3. Run the release acceptance tests below from freshly extracted candidate
   archives, including cache repair through the private mirror and the
   supported desktop, Android, Web, and iOS builds.
4. Only after the candidate passes, attach the immutable WSC release tag to the
   exact accepted source revision. For example, use `wsc-3.44.4-r1` for the
   first WSC release based on upstream `3.44.4`.
5. Once production automation has been commissioned, start the independent
   production release job with that tag as its only release-specific input.
   The job uses the same finalized pipeline implementation as staging, but
   must use fixed production settings,
   `full_rebuild`, `SYNC_ENGINE_DEPS=true`, the complete matrix, and the
   production mirror. It rebuilds rather than consuming staging workspaces,
   stashes, build numbers, or parameter manifests.
6. Publish the production SDK ZIPs, checksums, release notes, source revision,
   engine ID, upstream base tag, and recorded toolchain versions. Advertise the
   release only after both clean host archives pass.

Rollback means returning developers to the previous SDK archive and retaining
its corresponding mirror objects. It must not require rebuilding or mutating
that older artifact tree.

## Release identity and tags

Keep these identities distinct:

- the Git/framework revision, which identifies the exact fork source;
- `bin/internal/engine.version`, which identifies the exact artifact tree; and
- the upstream Flutter version on which the fork release is based; and
- the human-facing SDK release name used for ZIPs and release notes.

### Where upstream gets version and channel identity

Flutter normally calculates `frameworkVersion` from Git tags. It first looks
for a recognized numeric stable tag such as `3.44.4`, or a recognized
pre-release tag, directly on the checked-out revision. If none is attached, it
uses the numeric tags available in that clone and a commit count to synthesize
a development version. Consequently, the synthesized result can change when
the clone gains newer upstream tags even though the checked-out WSC revision
has not changed.

The channel is calculated separately from the current local Git branch name.
Known branch names such as `main`, `beta`, and `stable` become the corresponding
channel; an arbitrary branch becomes `[user-branch]`. Once calculated, these
values are written to the generated `bin/cache/flutter.version.json`, which
normal subsequent tool invocations read before consulting Git again. That file
is disposable cache state, not release source metadata.

The SDK package creator has another tag lookup for the archive name. In strict
publish mode it requires a tag attached to the exact revision. In the current
non-strict archive-only mode it may walk backwards to the nearest tag. The
package creator also clones the value supplied through `--branch` and then
resets that still-attached branch to `--revision`. Therefore `--revision`
selects the exact source content, while `--branch` determines the branch and
channel identity stored in the SDK and appended to the upstream-style archive
name.

Upstream release packaging therefore assumes that the numeric release tag
already points to the exact revision being published. WSC must not move the
upstream `3.44.4` tag from its original upstream commit to the patched commit.
The patched commit instead receives an immutable WSC tag such as
`wsc-3.44.4-r1`. Flutter's existing numeric version parser intentionally does
not treat that WSC tag as an upstream framework version.

### Source-ref strategy: patched mirror of upstream release refs

A simple long-term source model is to treat the WSC repository as a transformed
mirror of Flutter's public release surface: each supported upstream ref has an
equivalent WSC ref containing the same upstream state plus the current WSC
patch train.

```text
Flutter upstream                    WSC repository
main/master  -- apply patches -->   main
beta         -- apply patches -->   beta
stable       -- apply patches -->   stable

tag 3.44.4   -- apply patches -->   tag wsc-3.44.4-r1
tag 3.47.5   -- apply patches -->   tag wsc-3.47.5-r1
```

In this model, `main` is the canonical editable integration line. The WSC
`beta` and `stable` refs are protected outputs produced by replaying the patch
train on the corresponding moving upstream refs; nobody develops directly on
them. When upstream moves a channel, automation prepares the new patched tip,
runs the required tests, and moves the WSC channel ref only if the replay and
tests succeed. A conflict or failure leaves the last known-good WSC channel in
place and requires a narrow patch adaptation.

Published WSC tags remain immutable. `wsc-3.44.4-r1` means the first WSC
release based on upstream `3.44.4`; a WSC-only correction on the same upstream
base becomes `wsc-3.44.4-r2`. Do not reuse the bare `3.44.4` tag for patched
source: identically named upstream and fork tags cannot coexist cleanly in one
checkout, and a second WSC revision would otherwise require moving an existing
release tag.

Keep Flutter's standard version semantics separate from the WSC release
identity. An exactly WSC-tagged release based on upstream `3.44.4` exposes
`frameworkVersion=3.44.4` and `channel=stable` to code that expects Flutter's
version grammar, while its additive WSC identity remains unambiguous:

```text
source tag:       wsc-3.44.4-r1
frameworkVersion: 3.44.4
wscVersion:       wsc-3.44.4-r1
channel:          stable
archive:          flutter_windows_wsc-3.44.4-r1-stable.zip
```

The WSC tag is the sole source of final WSC release identity. Do not add a
second tracked version file whose values must be kept in sync with the tag.
This fork narrowly extends Flutter's existing Git-tag parser:

- an exact `wsc-<upstream-version>-r<number>` tag supplies `wscVersion` and
  preserves the embedded upstream version as `frameworkVersion`;
- an untagged descendant of upstream `3.44.4` automatically receives an
  identity such as `wsc-3.44.4-dev.45-g097c6f756e`;
- after `wsc-3.44.4-r1`, an untagged descendant describes development after
  that release, for example `wsc-3.44.4-r1-dev.5-gabcdef1234`. It does not
  predict the next release revision; and
- upstream pre-release bases are supported as well, for example
  `wsc-3.45.0-0.1.pre-dev.2-g4ad25ed4c4` during development and
  `wsc-3.45.0-0.1.pre-r1` once released.

The WSC development identity uses the nearest reachable recognized upstream or WSC
release tag, not the newest tag that happens to exist in the clone. Fetching a
newer unrelated upstream tag therefore does not change its base tag. The commit
count and abbreviated hash make different staging source states visibly distinct.

Flutter's own untagged `frameworkVersion` calculation deliberately remains
upstream behavior: it uses the highest available numeric tag and a commit
count from the common ancestor. An untagged fork based on `3.45.0-0.1.pre`
can therefore report `frameworkVersion=3.46.0-1.0.pre-6` while its WSC identity
still describes the 3.45 base. This also occurs with untagged upstream work on
older release lines. We accept that development-version convention rather than
maintaining a different Flutter fallback. The WSC identity identifies our base
and development state; an exact WSC release tag supplies the embedded upstream
version when producing a release. No manual candidate tags or version-file edits
are required.

The generated `bin/cache/flutter.version.json` stores the resolved
`wscVersion` next to Flutter's existing fields so packaged SDKs do not need Git
to rediscover it. This remains disposable generated cache, not a source of
truth. `flutter --version` adds a separate `WSC SDK` line,
`flutter --version --machine` exposes `wscVersion`, and the package creator
uses it in the archive filename. Existing `frameworkVersion`, channel,
framework revision, repository URL, and engine stamp behavior remains
unchanged.

`Jenkinsfile.testing` validates each completed Windows/macOS SDK ZIP before
archiving it, checking the source revision, channel, WSC identity, and filename.
For normal staging builds, leave `REQUIRE_RELEASE_TAG=false` (the default).
For SDKs intended for release, enable `REQUIRE_RELEASE_TAG=true`: source
preflight rejects missing or ambiguous WSC release tags before engine builds,
and the ZIP check requires the embedded Flutter version and WSC identity to
match the exact tag. Untagged staging SDKs retain upstream's synthesized
Flutter version and must carry a WSC development identity matching their source
hash. This switch is independent of `BUILD_POLICY`; it does not request a clean
engine rebuild. The SDKs are still archived by Jenkins, not automatically
promoted to the public download location. Any future release-publishing job
must enforce this check before distributing its SDKs.

Tagging a tested commit does not modify an existing SDK ZIP. Package the tagged
revision again from a clean SDK checkout, as the pipeline already does, to
regenerate `flutter.version.json`. Flutter's normal launcher invalidates that
cache when the tool revision changes; adding a tag alone does not change the
commit, so fresh packaging is important. This needs no extra cache mechanism
and no engine recompilation solely because of the tag.

This is intentionally less machinery than a WSC metadata manifest. The tag
already names the exact commit and carries both the upstream base version and
WSC revision; repeating those facts in a hand-maintained file would create a
second authority and another rebase/release step. The only fork-specific
tooling is the tag grammar, one additive generated JSON field, one human-readable
version line, and selection of that value for SDK archive names.

Do not reseat a published WSC tag. If a production build fails for a transient
infrastructure reason, rerun the same tag. If source must change, validate the
new staging candidate and tag it with the next revision (`r2`, `r3`, and so
on). This makes an SDK identity immutable without forcing every failed build
attempt to consume a revision number.

Patch development remains ordinary topic-branch and pull-request work against
the WSC integration line. The patch set is expected to be mostly stable; when
an upstream update breaks it, adapt the affected patch once and replay the
updated train onto the desired upstream development, beta, stable, or release
tag. There is no need to mirror every upstream feature branch or pull request.

For staging CI, keep four decisions independent rather than overloading a
branch name:

- `SOURCE_REVISION`: the exact WSC commit to build;
- `SDK_CHANNEL`: `main`, `beta`, or `stable`, used for Flutter channel behavior;
- `BUILD_POLICY`: `incremental` or `full_rebuild`; and
- `PUBLISH_ENV`: `none`, `staging`, or `production`.

The future production release job deliberately has a smaller interface: one
immutable WSC tag. It should use the same finalized pipeline implementation,
not a second Jenkinsfile; its matrix, channel policy, mirror, synchronization,
and clean-build settings are fixed job configuration rather than copied from a
staging build. This avoids jobs that must coordinate parameter JSON, build
numbers, or large stashes, while also avoiding duplicate pipeline code. The
clean rebuild is the small amount of deliberate duplication that buys
independence from unrecorded staging-agent state and toolchain changes; the
accepted staging ZIP proves the source is releasable, while the production job
proves the official output is reproducible in the production environment.

A minimal adoption path is to establish the real WSC `main` history, publish
the first immutable WSC tag after candidate acceptance, configure the tag-only
production job, validate a full release, and then create the protected `stable`
ref. The `beta` automation can follow later. Replacing an unrelated or
placeholder repository `main` history and changing public refs are one-time
invasive operations and require explicit review before they are performed.

### Initial patch-stack consolidation and forward ports

Start the canonical WSC stack on the already tested upstream `3.44.4` base;
do not combine history cleanup with an upstream upgrade. Consolidate the net
changes into a few logical commits and verify that the resulting Git tree is
identical to the accepted source branch. Keep the historical branches and
published tags intact. The fork's `main` need not track upstream's latest tip.

For each forward port, select an exact upstream tag or commit, create a
candidate branch there, and replay only the WSC tail:

```sh
git switch -c <candidate> <new-upstream-base>
git cherry-pick <old-upstream-base>..<patch-stack-tip>
```

The old base is excluded from that range. Keep the stack linear, fold
compatibility fixes into the relevant WSC commits before the next replay, and
retain the previous accepted version. Validate 3.45, then 3.46, then a pinned
upstream-main revision as separate steps; future maintenance need not visit
every intervening release.

History consolidation alone requires no engine build or duplicate workspace.
Jenkins currently keys engine workspaces by `JOB_NAME` and target, so a new
branch job would start with separate outputs unless workspace reuse is planned
explicitly. Preserve existing workspaces; do not delete a working older build
to make room for history-only work. For same-source incremental testing, reuse
the existing paths and dependencies without a clean or dependency reset.
Changed Git identity can still regenerate version data and cause relinking.
Review the engine artifact pin after rewriting history: identical source trees
do not make the old commit-based artifact ID a valid new release identity.

For each release:

1. Verify that `bin/internal/engine.version` identifies the latest
   engine-affecting commit.
2. Seed or verify the pinned global artifacts referenced by path-valued files
   in `bin/internal`, including Material Fonts and the Gradle wrapper.
3. Build the engine artifacts for each supported host, target, and build mode.
4. Publish each target's artifact ZIPs directly to the HTTPS mirror under that
   engine ID.
5. Assemble a clean host SDK staging directory using the framework revision.
6. Populate its basic cache/tooling and create the host-specific SDK archive.
7. Publish the SDK archive and checksum only after all requested target uploads
   and acceptance checks succeed.
8. Keep PDBs and other debug symbols as separate Jenkins diagnostic artifacts,
   with an appropriate retention policy. They are not normally required for
   Flutter runtime builds.

SDK assembly uses upstream's `dev/bots/prepare_package.dart` flow. This fork's
packaging changes remain narrow: use the private Bitbucket origin, preserve
Windows long-path support during the inner checkout, write the selected
`ARTIFACT_BASE_URL` into the packaged SDK, and bootstrap `sky_engine` and
`flutter_gpu` before the Flutter tool first starts. The launcher reads the
mirror file and exports `FLUTTER_STORAGE_BASE_URL`, so the upstream precache and
Gradle paths observe the same mirror without target-specific downloader
patches.

The Jenkins archive-only invocation passes upstream's `--dry_run` flag while
leaving `--publish` disabled. This still creates the complete local SDK archive
but prevents the package publisher from trying to read or update Flutter's
public Google Storage release metadata. SDK ZIP publication and private release
metadata are separate promotion steps described above.

The two Python files have narrow roles:

- `collect_engine_artifacts.py` interprets upstream engine builder JSON and
  copies declared archives into Flutter's mirror directory layout. Upstream's
  equivalent is part of LUCI recipes rather than a standalone local command.
- `upload_artifact_tree.py` is used only for `UPLOAD_TRANSPORT=http_put`.
  FTP/FTPS and SFTP use Jenkins plugins directly.

## Release acceptance test

Test each published archive after extracting it into a fresh directory. Do not
pass local-engine arguments. Test the pre-cached path, then remove one
non-bootstrap cache component and confirm that Flutter restores it from the
private mirror. Monitor the HTTP server or an outbound proxy during this test:
fork engine downloads must use the configured mirror and must not silently
switch to Flutter's public storage.

On Windows, exercise the actual supported target set, for example:

```powershell
flutter doctor
flutter create smoke
Set-Location smoke
flutter build windows
flutter build apk
flutter build web
```

On macOS, also exercise macOS and an unsigned iOS build:

```sh
flutter doctor
flutter create smoke
cd smoke
flutter build macos
flutter build ios --no-codesign
flutter build apk
flutter build web
```

Confirm downloads resolve only from the internal mirror and that the reported
engine revision is the release's pinned engine ID.

## Caveat: optional artifacts

Most standard engine artifacts are ordinary ZIP files. Some optional or
less-common Flutter dependencies use CIPD. A fully pre-cached supported target
matrix avoids needing to mirror those. If the goal expands to supporting
arbitrary future `flutter precache` targets by lazy download, audit the
corresponding tool paths and mirror the required CIPD content as well.
