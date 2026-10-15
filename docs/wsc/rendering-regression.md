# SDK rendering regression in Jenkins

The pipeline can compare each newly packaged desktop SDK with a manually
approved **Flutter/WSC SDK**, not Qt. It invokes FRT's existing `compare` command;
there is no shared FRT server or persistent reference-run database.

## Commission manually before enabling CI

A developer may run FRT's automated comparison on their workstation and retain
the results as release-review evidence. This avoids making Jenkins GUI/device
setup a prerequisite for rendering checks. Record the baseline/candidate SDK
checksums, exact FRT commit, target/runtime settings and reports. Release approval
requires reviewed results; it does not require that Jenkins launched the test.

Keep the Jenkins integration disabled until desktop capture is reliable. Enable
Windows/macOS CI first if useful; mobile/Web Jenkins stages remain future work.
The FRT repository now includes mobile/Web orchestration and an optional shared
server workflow for developer hosts; implementation is not proof that each
target works on the client's infrastructure. Follow its
[current README](https://bitbucket.org/schoolcraftteam/font_rendering_tester/src/master/README.md)
for those commands. This pipeline continues to use isolated per-cell instances.

## Configure once, then version the defaults

[frt_ci.json](../../dev/bots/frt_ci.json) owns the configuration. It initially
disables testing because approved baseline URLs/checksums have not been supplied.
The pipeline logs **NOT VALIDATED** and skips the regression stages in this case.
Packaging success with regression disabled is not rendering acceptance.

Fill in each selected host's baseline `url` and `sha256`, and set `enabled` to
`true`. The baseline must match the agent architecture and be compatible with
the pinned FRT client. URLs are unauthenticated HTTP(S), without embedded
credentials or query strings; use HTTPS outside local testing. Keep accepted
SDKs **and their referenced engine artifacts** immutable. Never automatically
promote a passing candidate to the baseline.

During commissioning, nonempty folder properties override the JSON defaults:

| Property | Overrides |
| --- | --- |
| `WSC_FRT_ENABLED` | `enabled`; true: `1`, `true`, `yes`, `on`; false: `0`, `false`, `no`, `off` |
| `WSC_FRT_REPOSITORY` | FRT HTTPS clone URL |
| `WSC_FRT_REF` | FRT branch, `refs/tags/<tag>`, or full commit SHA; default `master` |
| `WSC_FRT_CREDENTIALS_ID` | Jenkins checkout credential ID; empty uses the Flutter job's SCM credential |
| `WSC_FRT_BASELINE_WINDOWS_URL` | Approved Windows SDK ZIP URL |
| `WSC_FRT_BASELINE_WINDOWS_SHA256` | Its SHA-256, exactly 64 hexadecimal characters |
| `WSC_FRT_BASELINE_MACOS_URL` | Approved macOS SDK ZIP URL |
| `WSC_FRT_BASELINE_MACOS_SHA256` | Its SHA-256 |

Expose folder properties at build start as described in the [CI runbook](../../DEPLOYMENT.MD).
Remove overrides when adopting committed defaults; inherited nonempty values
continue to win. Do not store credentials in these properties. The FRT checkout
credential must have read access to its repository. Checkout credentials are
not bound while running the comparison.

When enabled, missing/invalid baseline settings for **any selected `HOST_SDKS`
host fail preflight**. Selecting only one host requires only its baseline.
`HOST_SDKS` empty means no SDK regression cells. There are no separate FRT build
parameters or per-platform runtime jobs to keep synchronized.

FRT `master` is resolved to one SHA during release preflight; both host agents
check out that SHA. FRT checkouts do not participate in SCM polling. Updating
FRT alone therefore does not trigger Flutter builds. Push required FRT commits
first. Once stable, commit an exact FRT SHA in the config instead of `master`.
Fixture, client source/fonts, Python lockfile and comparison defaults come from
that FRT checkout. The JSON selects the fixture, build mode and capture DPI.

## Execution and prerequisites

Windows and macOS run independently, on their SDK packaging agents:

```text
package + upload candidate SDK -> compare approved SDK / local candidate ZIP
```

This adds two small application builds per host, **not another engine build**.
Persistent engine paths, Ninja outputs and dependency-sync policy are unchanged.
The helper verifies the baseline checksum, records candidate/fixture checksums,
runs `uv sync --locked`, then calls `uv run --locked font-rendering-regression
compare`. FRT extracts the ZIPs, builds isolated clients, creates a fresh database,
imports the fixture, captures both runs and compares their explicit IDs.

Agents need `uv` on their actual process PATH, Python 3.14+ available to uv, the
native app-build toolchain and a working graphical desktop session. The Jenkins
wrapper uses the existing `WINDOWS_PYTHON` or `python3`; FRT's environment is
managed by uv. A 1280 x 1024 desktop is the intended commissioning environment,
but capture at that resolution still needs runtime validation. `dpi: 192` sets
capture resolution, not display scale or available window size. Keep display
settings and rendering flags consistent for both clients. Serialize GUI tests
across jobs sharing one desktop; `disableConcurrentBuilds()` only covers a
single branch job, not every job on an agent.

Both SDKs must expose the APIs used by the same FRT client, including
`RenderParagraph.getLineBoundary`. If an older baseline lacks that API, prepare
and approve a compatible baseline once; do not patch it silently during tests.

The adapter conservatively
requires the two retained `frt-pubspec.lock` files to be byte-identical before
accepting a comparison. Differences, including SDK-constraint-only differences,
fail for review rather than silently changing test dependencies. Future
compatibility rules belong in FRT, not a second YAML/dependency resolver here.
Newer FRT code also validates non-SDK dependencies itself; this adapter's
additional byte-equality guard is stricter and may reject otherwise compatible
cross-version comparisons.

## Outcomes, evidence and acceptance

| Outcome | Jenkins result |
| --- | --- |
| Exit 0 with consistent, complete passing report | Success |
| Exit 1 with a verified rendering/layout mismatch | Unstable; early email |
| Exit 2, unexpected exit, missing/invalid report, incomplete diagnostics, checksum/dependency mismatch | Failure; early email |
| FRT's own client build/startup/capture/comparison timeout | Failure |
| Jenkins emergency watchdog (90 minutes), or operator cancellation | Aborted; not validated |

The adapter requires nonempty comparisons, distinct runs, and available
`line_metrics` and `fonts` checks. Pixel differences remain informational in
FRT's configured comparison. Do not weaken checks to make a candidate green.
Results for other host branches can continue; unstable/failed/skipped comparisons
are **not release approval**. SDK publication precedes these tests, so uploads
remain candidates until reviewed, as with the existing manual acceptance gates.
The outer watchdog retains Jenkins' normal abort semantics. We do not inspect
internal exception APIs requiring extra Script Security approvals just to
relabel that emergency stop; neither aborted nor failed counts as acceptance.

The pipeline archives `build/frt-evidence/<host>-<build>.tar.gz` in Jenkins, even
after a comparison failure when evidence exists. It contains input identities,
reports, logs, client bundles and the comparison database. Tar preserves macOS
bundle symlinks. Baseline ZIPs and interrupted temporary SDK/build trees are not
archived. FRT cleans its own temporary trees on normal exit; an agent crash can
leave scratch data until the next clean **SDK packaging** checkout. Never clean
the persistent engine workspace to recover an FRT failure.

**Jenkins artifacts must be access-controlled.** These captures/databases never
enter the public SDK artifact payload. Configure bounded artifact retention on
the job/controller and preserve release SDKs in the artifact repository; this
change does not silently alter existing Jenkins retention or delete old builds.
Do not attach the evidence archive to email; normal compressed console mail
includes status and the build link. An FRT checkout failure can occur before any
comparison evidence exists; the console remains the diagnostic source then.

Before declaring this integration commissioned, demonstrate a passing pair, an
intentional mismatch becoming unstable, and a capture/build failure becoming
failed on the real agents. Verify retained evidence, cleanup, email, desktop
resolution and cross-job GUI isolation. Unit tests and Declarative validation
do not establish those runtime properties.

## Later targets: recommended hosts, not implemented coverage

Engine-build hosts and regression-test hosts are different decisions. Keep
Android/Web **engine compilation on Linux** as it is; their consumer apps can
be built/tested using a Windows or macOS SDK.

| Target | Initial regression host | Capture environment / remaining work |
| --- | --- | --- |
| Windows | Windows | Existing FRT desktop flow; validate Jenkins execution |
| macOS | macOS | Existing FRT desktop flow; validate Jenkins execution |
| Web | Windows | Validate FRT browser capture and later wire into Jenkins; pin browser version, viewport/DPR and renderer/backend |
| Android | macOS | Validate emulator/device build/install/capture before Jenkins integration; pin device/API/ABI and rendering configuration |
| iOS | macOS | Validate simulator/device capture before Jenkins integration; pin model/runtime and handle signing for devices |

Consolidate mobile testing on macOS and keep Web on Windows, without adding a
graphical session to the headless Linux VM. Run macOS/iOS/Android comparisons
sequentially on the Mac to limit memory pressure and GUI interference. Do not
duplicate these tests on every host initially.
For Web, add macOS/Safari only when browser coverage is required; a single
Windows browser is not proof of all browser backends.

Validate Android independently: a working iOS Simulator does not establish that
Android's emulator works on the same Mac. Software graphics and unaccelerated
CPU emulation are different fallbacks; the latter may be impractically slow.
Android's [acceleration documentation](https://developer.android.com/studio/run/emulator-acceleration#restrictions)
warns against VM-accelerated emulators inside another VM. Prove boot, app launch
and capture on the actual host before scheduling unattended runs. For Android
smart-board acceptance, retain a separate representative physical-device check;
emulator regression results do not certify the deployed hardware.

iOS simulator results likewise do not certify physical-device rendering.
This Jenkins integration accepts only `windows` and `macos`; mobile/Web capture
in FRT is not yet wired into this pipeline. Each future
target needs its own explicit baseline/candidate runs under the same device or
browser configuration, using the existing SDK comparison/reporting contract.
