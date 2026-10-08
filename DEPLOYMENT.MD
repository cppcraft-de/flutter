# WSC Flutter deployment

This is the client runbook for building and distributing this fork. Developers
extract a host SDK archive, add `flutter/bin` to `PATH`, and use ordinary Flutter
commands without `--local-engine`.

## Documentation map

- **This file:** Jenkins setup, configuration, iteration, and acceptance.
- [Artifacts and SDK packaging](docs/wsc/artifacts.md): storage layout, warm
  caches, upload/download contracts, and why a mirror is required.
- [Release identity and maintenance](docs/wsc/releases.md): versions, tags,
  upstream updates, dependency patches, and release gates.
- [Local testing](docs/wsc/local-testing.md): installation-specific overrides
  and the temporary workspace-reuse exception. Not required on client CI.
- [Agent entry point](AGENTS.md): navigation and repository safety constraints.

## Current behavior

The pipeline is **`Jenkinsfile.testing`**. There is no separate production
Jenkinsfile. It builds engine artifacts, uploads them directly from their agents,
then packages and uploads Windows and macOS SDKs using those artifacts. Large
engine payloads do not pass through Jenkins stashes.

| Agent label | Work |
| --- | --- |
| `flutter_win` | Release metadata, mirror seeding, Windows engine, Windows Android AOT host tools, Windows x64 SDK |
| `flutter_macos` | macOS and iOS engines, macOS Android AOT host tools, macOS SDK (arm64 on the current packaging host) |
| `flutter_linux` | Android runtime/JAR/Maven artifacts and Web SDK artifacts; no Linux host SDK |

The target cells can run in parallel when executors are available. Runtime modes
run sequentially inside each target workspace to share dependencies and outputs.
Linux is the current upstream-builder layout choice, not a fundamental claim
that Android/Web cannot be built on macOS. Removing that agent would require
build/collection changes and validation, not merely changing a label.

These documents describe checked-in behavior, not proof that a particular
client environment has passed. A green source/unit test is not engine,
packaging, authentication, or developer-installation acceptance.

## 1. Prepare the agents

Use persistent agent work directories with sufficient room for dependencies,
per-target engine outputs, temporary packaging clones, SDK caches, and archives.
Changing paths can invalidate Ninja outputs containing absolute paths. Do not
enable workspace-wipe/cleanup steps for the persistent engine workspaces.

- **All agents:** compatible Jenkins agent Java, Git, Python 3, depot_tools with
  `gclient`, and the native build prerequisites for the pinned Flutter source.
  Verify commands in the actual agent process environment, not only your shell.
- **Windows:** VS2022 and Windows SDK components for the built architectures,
  including ARM64 libraries and matching debugging tools/`dbghelp.dll`; `7za`
  on PATH for packaging. `7z.exe` alone is not the command used by this packager.
  Enable Git/OS long-path support for the agent account. `WINDOWS_PYTHON`
  defaults to `python`; verify that it is a working interpreter, not a broken
  launcher or Windows Store alias.
- **macOS:** Xcode, its selected command-line tools/SDKs (including Metal tools
  required by the engine), and `python3`, `zip`, and `unzip` on PATH. Allow disk
  capacity for both macOS and iOS workspaces plus SDK packaging.
- **Linux:** the commissioning baseline is Ubuntu 26.04 in a VM or WSL2 with
  native Linux filesystem storage. Install the pinned engine's Linux build
  prerequisites. Android Studio is not required for this engine CI path;
  dependency synchronization obtains the DEPS-managed build inputs.

CPU/RAM and free disk should be sized for the selected concurrent targets, not
just one checkout. Existing small incremental workspaces are not a clean-build
capacity estimate. Reserve additional space for another supported release line
and packaging; measure peak use on the first complete run before fixing quotas.
Retain released artifacts independently of disposable Jenkins workspaces.

Agents need outbound access to Bitbucket, dependency/toolchain downloads,
pub.dev, and the artifact endpoints. This is not an air-gapped build setup.
Use the source revision's [engine environment guide](docs/engine/contributing/Setting-up-the-Engine-development-environment.md)
and [compilation guide](docs/engine/contributing/Compiling-the-engine.md) for
platform prerequisites; WSC packaging requirements above are additional.

## 2. Configure Jenkins and credentials

1. Create a multibranch job with script path **`Jenkinsfile.testing`**. Do not
   add a root `Jenkinsfile` during commissioning: another Jenkins installation
   could discover it and start builds. Keep one shared pipeline implementation.
2. Install the required plugins: Declarative Pipeline, Git with
   `gitUsernamePassword`, Credentials Binding, Folder Properties with
   build-start exposure, and Email Extension. Configure SMTP if using email.
   FTP/SFTP plugins are needed only for those alternative upload transports.
3. Set the SCM URL to
   `https://bitbucket.org/schoolcraftteam/flutter_wsc.git`. Select a Jenkins
   **Username with password** credential: username
   `x-bitbucket-api-token-auth`, password a Bitbucket API token with repository
   read access. Use a service identity appropriate for the client's operations.
4. Both SDK stages reuse that SCM credential ID for the packager's nested HTTPS
   clone through Jenkins' Git credential binding. No SSH key, `known_hosts`,
   `setsid`, or interactive login is required for this path. Do not put tokens
   in URLs, scripts, folder properties, or build parameters.
5. Create a **Secret text** credential with ID **`HTTP_UPLOAD_KEY`**, containing
   the Bunny storage key. This is separate from the Git credential; it is sent
   as the upload `AccessKey` header, never embedded in the SDK.
6. The fork URL is also configured in
   [prepare_package/common.dart](dev/bots/prepare_package/common.dart). A new
   repository requires updating those constants and their tests, not only the
   job URL. The `RELEASE_BRANCH` ref (default `stable`) must exist in that fork,
   and the build commit must be fetchable. Packaging clones that branch then
   resets to the exact Jenkins build revision; the branch name controls SDK
   channel identity, not source selection.
7. Suppress automatic SCM/indexing builds in the multibranch job, including
   newly discovered branches. For the existing suppression UI, `^$` under
   **Branch names to build automatically** matches no normal branch. Perform
   an initial scan to discover the branch you intend to build.

Deploy the pipeline **and its supporting scripts together**. Do not copy only
the Jenkinsfile into an otherwise older source tree.

## 3. Set folder properties

Use **Folder Properties** on the containing Jenkins folder and enable
**Expose these properties at build start**. This is required for the polling
expression evaluated before the normal pipeline wrapper. Folder properties
are inherited by all branch jobs; they are configuration, not secret storage.

| Property | Client value/default |
| --- | --- |
| `DISABLE_SCM_POLLING` | Unset or `0`: poll for commits approximately every five minutes |
| `BUILD_LOG_MAIL_RECIPIENT` | Desired email address; unset/empty disables email |
| `WSC_ARTIFACT_BASE_URL` | Unset uses `https://fluttertest.b-cdn.net` |
| `WSC_HTTP_UPLOAD_BASE_URL` | Unset uses `https://storage.bunnycdn.com/fluttertest` |
| `WSC_UPLOAD_CREDENTIALS_ID` | Unset uses `HTTP_UPLOAD_KEY` |
| `WSC_ENGINE_WORKSPACE_JOB` | Leave unset; local-testing exception only |
| `WSC_ENGINE_WORKSPACE_KEY` | Leave unset; local-testing exception only |

URLs are base roots **without trailing slashes**. Explicit nonempty build
parameters for URLs/credential ID override these properties. Leave those
parameters empty to inherit; saved values on an existing job may override new
defaults. Only the download URL is written into the SDK.

### Polling and email

`DISABLE_SCM_POLLING=1`, `true`, `yes`, or `on` disables periodic polling
(case-insensitive, whitespace ignored). Other/unset values enable
`pollSCM('H/5 * * * *')`. This builds on detected changes, not on every timer
tick. Indexing/event-triggered builds remain suppressed by
`overrideIndexTriggers(false)`; the parent **Periodically if not otherwise run**
scan may stay unchecked. Scanning discovers branches; polling checks existing
branch jobs for commits.

Run the desired branch manually once to register its schedule. Later changes
to the folder property also take effect on the next pipeline run, not when the
folder is saved, and do not cancel queued builds. Normal polling requests with
identical parameters coalesce into one pending request per branch. Running
builds are not aborted. Other branches/different parameters are separate jobs
or requests; a started pipeline waiting for an agent already counts as running.

Email sends a compressed console log on target/SDK stage failure and a final
summary/log from global cleanup. The early log contains the overall run so far;
other targets may continue. Delivery errors are logged without replacing the
build result. No recipient means no email.

## 4. Run the integration build

These are the current script defaults (verify saved job parameters):

```ini
TARGETS=windows,macos,ios,android,web
HOST_SDKS=windows,macos
MODES=debug,profile,release
BUILD_POLICY=incremental
SYNC_ENGINE_DEPS=false
PUBLISH_ENGINE_ARTIFACTS=true
UPLOAD_TRANSPORT=http_put
RELEASE_BRANCH=stable
REQUIRE_RELEASE_TAG=false
```

Start the first run manually. It seeds missing upstream-owned mirror inputs,
builds/publishes the target artifacts, and then creates, validates, and uploads
both host SDK ZIPs and checksum sidecars. See the
[actual storage layout](docs/wsc/artifacts.md#storage-layout) for download paths.
The first run on an empty agent must compile everything selected.

### Incremental behavior

Engine workspaces are persistent, relative to each agent root:

```text
engine-workspaces/<full Jenkins JOB_NAME>/<BUILD_TARGET>
```

- `incremental` preserves `engine/src/out`; Ninja decides which work is needed.
  The pipeline still invokes every selected build and republishes its payload;
  it does not skip builds because artifacts already exist remotely.
- With `SYNC_ENGINE_DEPS=false`, each fresh target workspace synchronizes and
  applies patches before its first build. Subsequent runs skip synchronization
  when `.gclient` and the expected Dart executable exist. This is a bootstrap
  check, **not** a dependency-integrity or patch-freshness check. After changing
  DEPS, patch files, or upstream base, or repairing a partial workspace, set
  sync to `true` for that run, then return to `false` for quick iterations.
- Synchronization can reset/reapply nested patches and cause recompilation;
  it is not done once per runtime mode. Each target has its own dependency tree.
- SDK packaging intentionally uses clean separate checkouts and warms/downloads
  a new cache. Incremental engine builds do not make packaging a no-op.
- `full_rebuild` explicitly deletes `engine/src/out` before building. It does
  not recreate every dependency/toolchain/cache or make the agent hermetic.
- Stable paths matter. Renaming the job, changing its workspace key, or adding
  a target can create new output directories. There is no cross-job workspace
  lock. Do not share paths or enable automatic cleanup of these workspaces.

Reduced smoke tests can set fewer targets/modes and **empty `HOST_SDKS`**.
Complete SDK packaging requires all three modes and the standard targets:
Windows needs `windows,android,web`; macOS needs `macos,ios,android,web`.
Debug-only SDK packaging is not implemented. Detailed tradeoffs are in
[Artifacts and SDK packaging](docs/wsc/artifacts.md#supported-targets-and-reductions).

### Remaining parameters

| Parameter | Purpose |
| --- | --- |
| `ARTIFACT_BASE_URL` | Explicit download root; empty inherits folder/default |
| `HTTP_UPLOAD_BASE_URL` | Explicit PUT root; empty inherits folder/default |
| `UPLOAD_CREDENTIALS_ID` | Credential ID, not the key; empty inherits folder/default |
| `WINDOWS_PYTHON` | Working Python command on Windows; default `python` |
| `TRANSFER_CONFIG_NAME` | Jenkins FTP/SFTP server configuration, only for those transports |
| `TRANSFER_REMOTE_DIRECTORY` | Optional relative directory for FTP/SFTP |

## 5. Accept the SDKs before distribution

A successful upload is not a release approval. Extract each SDK into a fresh
directory and use **that SDK's** `flutter` executable, without `--local-engine`.
Check `flutter --version --machine`: WSC identity, framework revision, channel,
and engine revision must match the intended build. See
[release identity](docs/wsc/releases.md#version-and-channel-identity).

With the application's normal platform toolchains installed:

```sh
flutter doctor
flutter create smoke
cd smoke
flutter build apk
flutter build web
# On Windows:
flutter build windows
# On macOS:
flutter build macos
flutter build ios --no-codesign
```

Also exercise debug/profile workflows and the actual WSC rendering tests on
the supported devices. After checking the warm-cache path, remove a selected
non-bootstrap component in this **disposable extracted SDK cache** and confirm
Flutter restores it from the configured mirror. Observe the HTTP requests;
fork engine/Maven downloads must not silently switch to public storage.
Pub/Gradle/toolchain downloads are separate and may still use public services.

Keep failed/partial runs as candidates, not releases. One host's SDK may have
uploaded before the other failed. Production acceptance additionally requires
the [tag, engine-pin, clean-build, and retention gates](docs/wsc/releases.md#release-procedure).
Automatic production promotion, a tag-only release job, and a private channel
update service are **not implemented by this pipeline**.

## Troubleshooting reference

| Symptom | First check |
| --- | --- |
| Git authentication fails or prompts | Job uses HTTPS and a username/password credential; its token can read the fork; packager URL matches. Do not restore SSH workarounds for an HTTPS problem. |
| PUT fails with 401/403/501 | Storage URL, secret-text credential, and server support for PUT. The CDN read URL is not the upload endpoint. |
| Packaging gets 404 after an upload | Exact engine ID/path, target publication result, and CDN stale/negative caching. A green seed check only covers seed inputs. |
| Unexpected broad rebuild | Confirm job/workspace path, build policy, dependency-sync setting, source/toolchain changes, and preserved output directories before cleaning anything. |
| Polling/email differs from configuration | Check inherited folder properties, build-start exposure, saved parameters, and whether the pipeline has run to apply the schedule. |
| Disk pressure | Pause and review ownership/capacity. Do not delete shared dependency trees or previous release workspaces during an active build. |
