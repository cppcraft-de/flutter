# SDK rendering regression in Jenkins

The pipeline can compare each newly packaged desktop SDK with a manually
approved **Flutter/WSC SDK**, not Qt. It invokes FRT's existing `compare` command;
there is no shared FRT server or persistent reference-run database.

## Commission capture on the actual agents

A developer may run FRT's automated comparison on their workstation and retain
the results as release-review evidence. This avoids making Jenkins GUI/device
setup a prerequisite for rendering checks. Record the baseline/candidate SDK
checksums, exact FRT commit, target/runtime settings and reports. Release approval
requires reviewed results; it does not require that Jenkins launched the test.

The configured CI coverage is Windows, macOS and Web; mobile stages remain
future work. Use `WSC_FRT_ENABLED=0` to opt out while commissioning an agent.
The FRT repository now includes mobile/Web orchestration and an optional shared
server workflow for developer hosts; implementation is not proof that each
target works on the client's infrastructure. Follow its
[current README](https://bitbucket.org/schoolcraftteam/font_rendering_tester/src/master/README.md)
for those commands. This pipeline continues to use isolated per-cell instances.

## Configure once, then version the defaults

[frt_ci.json](../../dev/bots/frt_ci.json) owns the configuration. Testing is
disabled by default pending the first Windows baseline SDK. The macOS baseline
from client build #16 is already pinned. Run packaging without FRT first, then
pin the approved Windows ZIP URL/checksum and set `enabled` to `true` (or use
`WSC_FRT_ENABLED=1`). Do not automatically select a moving latest build.
When enabled, missing baselines fail preflight rather than silently skipping
tests. Disabled runs log **NOT VALIDATED** and skip regression stages.
Packaging success with regression disabled is not rendering acceptance.

Fill in each selected host's baseline `url` and `sha256`. The baseline must
match the agent architecture and be compatible with
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
| `WSC_FRT_BROWSER` | Optional Windows agent path to Chrome/Edge; otherwise detect Edge first, then Chrome in standard installation directories |

Expose folder properties at build start as described in the [CI runbook](../../DEPLOYMENT.MD).
Remove overrides when adopting committed defaults; inherited nonempty values
continue to win. Do not store credentials in these properties. The FRT checkout
credential must have read access to its repository. Checkout credentials are
not bound while running the comparison.

When enabled, missing/invalid baseline settings for **any selected `HOST_SDKS`
host fail preflight**. Selecting only one host requires only its baseline.
Windows SDK selection includes Windows and Web comparisons, using the same
approved Windows baseline SDK; macOS SDK selection includes macOS only.
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

This adds two application builds per target, **not another engine build**.
Windows and Web captures run sequentially on the Windows packaging agent;
macOS capture runs on the Mac. Android and iOS are not captured.
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

Web uses installed Edge by preference, or Chrome if Edge is absent. A nonempty
`WSC_FRT_BROWSER` selects an exact executable and must exist; it does not fall
back silently. No browser is downloaded. FRT launches a fresh headless Chromium
profile for each capture, with a 1280 x 1024 viewport and device scale factor 1,
using the SDK's bundled CanvasKit. `dpi` is the separate capture resolution.
Safari is not supported by this runner. Use the same browser installation for
baseline and specimen, avoid browser updates during a comparison, and record
its version when commissioning. Edge coverage is not Safari/browser-matrix
acceptance. Standard-directory detection runs in the actual agent environment.

Both SDKs must expose the APIs used by the same FRT client, including
`RenderParagraph.getLineBoundary`. If an older baseline lacks that API, prepare
and approve a compatible baseline once; do not patch it silently during tests.

FRT's `compare` workflow validates both client builds against the same input
lockfile: non-SDK dependencies must remain unchanged; SDK-sourced packages,
SDK constraints and YAML formatting may differ. Dependency drift is an execution
error. Jenkins does not compare lockfile bytes or duplicate FRT's validation.
Offline reporting alone cannot establish dependency compatibility; keep capture
on the `compare` workflow rather than supplying arbitrary prebuilt clients.

## Outcomes, evidence and acceptance

| Outcome | Jenkins result |
| --- | --- |
| Exit 0 with consistent, complete passing report | Success |
| Exit 1 with a verified rendering/layout mismatch | Unstable; early email |
| Exit 2, unexpected exit, missing/invalid report, incomplete diagnostics, checksum/dependency mismatch | Failure; early email |
| FRT's own client build/startup/capture/comparison timeout | Failure |
| Jenkins emergency watchdog (90 minutes), or operator cancellation | Aborted; not validated |

FRT owns comparison validation, including complete results and available
required checks. Its offline reporter checks every configured target, including
missing hosts, and requires nonempty HTML reports. Pixel differences remain
informational in FRT's configured comparison. Do not weaken checks to make a candidate green.
Results for other host branches can continue; unstable/failed/skipped comparisons
are **not release approval**. SDK publication precedes these tests, so uploads
remain candidates until reviewed, as with the existing manual acceptance gates.
The outer watchdog retains Jenkins' normal abort semantics. We do not inspect
internal exception APIs requiring extra Script Security approvals just to
relabel that emergency stop; neither aborted nor failed counts as acceptance.

Each host archives its input identities, execution status and runner log, and
stashes only result JSON and comparison JSON/HTML with their relative structure.
No SDKs, client bundles or databases are transferred. Each capture requires a
fresh results directory; previous attempts are never silently reused.

Global `post` aggregates these reports on `flutter_win`, even after a host fails.
It uses the same resolved FRT commit and `uv sync --locked`, but needs no running
FRT server, desktop, SDK or emulator for reporting. The expected target list
comes from the resolved plan, never from the subset of successful captures.
Missing stashes, unexpected exit codes or missing ZIP/XML are failures. Operator
abort skips aggregation; an abort during aggregation propagates normally. Node
allocation/reporting has a 20-minute watchdog. Existing failures are never
turned green or downgraded to unstable.

Download `artifacts/frt-comparisons.zip` from Jenkins, extract it, and open
`index.html` locally. It contains the portable HTML comparisons, `summary.json`
and `junit.xml`. Jenkins also publishes that XML as test results and archives
`artifacts/frt-junit.xml`. Diagnostic ZIPs are retained when reporting fails,
including when extracting JUnit fails. A failed checkout/tool startup may prevent
ZIP creation; consult archived cell logs and the console in that case.

FRT cleans its temporary trees on normal exit; an agent crash can leave scratch
data until the next clean **SDK packaging** checkout. Never clean the persistent
engine workspace to recover an FRT failure.

**Jenkins artifacts must be access-controlled.** These reports and logs never
enter the public SDK artifact payload. Configure bounded artifact retention on
the job/controller and preserve release SDKs in the artifact repository; this
change does not silently alter existing Jenkins retention or delete old builds.
Do not attach the evidence archive to email; normal compressed console mail
includes status and the build link. An FRT checkout failure can occur before any
comparison evidence exists; the console remains the diagnostic source then.

Before declaring this integration commissioned, demonstrate a passing pair, an
intentional mismatch becoming unstable, and a capture/build failure or missing
host/HTML becoming failed on the real agents. Verify offline ZIP links, JUnit,
retained evidence, cleanup, email, desktop
resolution and cross-job GUI isolation. Unit tests and Declarative validation
do not establish those runtime properties.

## Target placement and later mobile coverage

Engine-build hosts and regression-test hosts are different decisions. Keep
Android/Web **engine compilation on Linux** as it is; their consumer apps can
be built/tested using a Windows or macOS SDK.

| Target | Initial regression host | Capture environment / remaining work |
| --- | --- | --- |
| Windows | Windows | Existing FRT desktop flow; validate Jenkins execution |
| macOS | macOS | Existing FRT desktop flow; validate Jenkins execution |
| Web | Windows | Wired into CI; headless Edge/Chrome, SDK CanvasKit; validate actual agent capture |
| Android | macOS | Validate emulator/device build/install/capture before Jenkins integration; pin device/API/ABI and rendering configuration |
| iOS | macOS | Validate simulator/device capture before Jenkins integration; pin model/runtime and handle signing for devices |

Consolidate mobile testing on macOS and keep Web on Windows, without adding a
graphical session to the headless Linux VM. Run macOS/iOS/Android comparisons
sequentially on the Mac to limit memory pressure and GUI interference. Do not
duplicate these tests on every host initially.
Safari coverage would require an additional runner; moving this Chromium
command to a Mac does not provide Safari testing.

Validate Android independently: a working iOS Simulator does not establish that
Android's emulator works on the same Mac. Software graphics and unaccelerated
CPU emulation are different fallbacks; the latter may be impractically slow.
Android's [acceleration documentation](https://developer.android.com/studio/run/emulator-acceleration#restrictions)
warns against VM-accelerated emulators inside another VM. Prove boot, app launch
and capture on the actual host before scheduling unattended runs. For Android
smart-board acceptance, retain a separate representative physical-device check;
emulator regression results do not certify the deployed hardware.

iOS simulator results likewise do not certify physical-device rendering.
This Jenkins integration covers `windows`, `macos` and `web`; mobile capture
in FRT is not yet wired into this pipeline. Each future
target needs its own explicit baseline/candidate runs under the same device or
browser configuration, using the existing SDK comparison/reporting contract.
