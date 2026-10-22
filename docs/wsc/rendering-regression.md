# SDK rendering regression in Jenkins

Jenkins uses the font rendering tester (FRT) to compare a newly built SDK with
an approved earlier SDK, called the **baseline**. This helps you catch rendering
changes before releasing an update. Windows and Web comparisons run on the
Windows packaging agent.
macOS FRT is disabled; macOS engine builds and SDK packaging remain enabled.
Android and iOS are not wired into this pipeline.

For FRT setup, local comparisons, fixtures, and capture commands, use the
[FRT README](https://bitbucket.org/schoolcraftteam/font_rendering_tester/src/master/README.md).
This page covers the Flutter pipeline's settings, results, and acceptance.

- [Review results](#outcomes-evidence-and-acceptance).
- [Configure the integration](#configure-once-then-version-the-defaults).
- [Prepare and accept the agents](#commission-capture-on-the-actual-agents).
- [Check coverage limits](#target-placement-and-later-mobile-coverage).

## Outcomes, evidence and acceptance

After a build, open Jenkins' **Test Result** page for the summary. Download
`artifacts/frt-comparisons.zip`, extract it, and open `index.html` for the detailed
comparisons. The ZIP also contains `summary.json` and `junit.xml`.

| Outcome | Jenkins result | Next step |
| --- | --- | --- |
| Complete, passing comparison | Success | Review the result with the other release checks. |
| Verified rendering/layout mismatch | Unstable | Inspect the comparison and decide whether the change is intended. |
| Build/capture error, incomplete diagnostics, or missing/invalid report | Failure | Fix the execution problem and rerun the comparison. |
| Watchdog timeout or operator cancellation | Aborted | Treat the comparison as incomplete. |
| FRT disabled | NOT VALIDATED in the log | Supply a reviewed developer-run comparison before accepting rendering. |

SDK upload happens **before** FRT runs. An uploaded SDK is still a candidate
until its results are reviewed. Do not change the baseline or weaken comparison
checks to make a build green. Pixel differences are informational in the current
FRT comparison; inspect the reported layout/rendering checks as well.

A developer-run comparison can supply release evidence while Jenkins agents are
being set up. Follow the FRT README and record the baseline and candidate SDKs,
exact FRT commit, target/settings, reports, and review decision. Release approval
requires reviewed results; Jenkins does not have to launch the comparison.

If a report is missing, check the console's `[FRT <host>]` output and archived
`runner.log` / `jenkins-result.json`. A checkout or tool-startup failure may occur
before reports exist. Jenkins aggregates available results after a cell fails;
missing expected results remain failures. Cancellation skips aggregation.

Jenkins also archives available compiler, client, and server logs, including
partial logs when a build or capture fails. Find them under
`build/frt-results/<host>-<BUILD_NUMBER>/results/<target>/`: `*-build.log` files
are at that level; `*-client.log` and `server.log` are in `comparison/`.
The same paths exist in the capture agent's SDK-stage workspace. The archived
`runner.log` contains progress and errors, not all subprocess output.

At the end of each FRT cell, Jenkins also prints these nested logs and the
SDK settings, version information, and result status as named console sections
before sending its failure or mismatch email. They are therefore included in the
existing compressed `build.log` attachment, not a second ZIP. Early emails contain only
the evidence available so far; the final email includes all completed cells.
Original files remain archived separately in Jenkins. Client bundles, databases,
screenshots and document files are not added to these console sections.

Reports are archived in Jenkins, not included in the public SDK payload or
attached to email. `archiveArtifacts` does not make them private: configure
Jenkins access control to restrict the job and its artifacts. Failure/mismatch
emails contain the console log and build link. Retain release review evidence
under your team's retention policy.

## Configure once, then version the defaults

[frt_ci.json](../../dev/bots/frt_ci.json) owns the defaults. FRT is enabled by
default. Windows and Web use the configured Windows baseline SDK. The macOS
baseline is retained for future use but not required by the current pipeline.
The checked-in baselines are from Jenkins build #24 and still
need testing on your agents before you rely on them for release decisions.

Choose a baseline that matches the agent architecture and exposes the APIs
needed by the selected FRT client. Keep that SDK and its engine artifacts
available. Set its `url` and `sha256` in the config; the adapter checks these
automatically. URLs must have no embedded credentials or query strings. Never
select a moving latest build or promote a candidate to baseline automatically.

Nonempty folder properties override the JSON defaults:

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
| `WSC_FRT_BROWSER` | Exact Windows path to Chrome/Edge; otherwise require Edge in standard installation directories |

Expose folder properties at build start as described in the
[CI runbook](../../DEPLOYMENT.MD#3-set-folder-properties). Remove temporary
properties when adopting committed defaults; inherited values continue to win.
The FRT checkout credential needs read access to that repository. Do not put
credentials in folder properties.

When enabled and `HOST_SDKS` includes Windows, a valid Windows baseline is required
or preflight fails. The Jenkinsfile limits capture and report expectations to
Windows and Web. macOS-only or empty `HOST_SDKS` means no SDK regression cells.
Use `WSC_FRT_ENABLED=0`
while setting up an agent if necessary; that leaves rendering unvalidated.

Preflight resolves the FRT ref to one commit for all cells. FRT changes do not
trigger Flutter SCM polling. Push required FRT changes before starting the
Flutter build. Once the setup is accepted, pin an exact FRT commit in the config
for repeatable comparisons. FRT owns its fixtures, client dependencies, and
comparison behavior; this repository owns the Jenkins adapter and settings.

The adapter inherits the agent environment. FRT environment settings can
override the pinned checkout's checker defaults, so a pinned commit alone does
not fix the comparison policy. Review the effective settings using the FRT
README when commissioning agents and recording acceptance evidence.

## Execution and prerequisites

The pipeline packages and uploads the Windows SDK, then compares its local ZIP against
the approved baseline. It builds two FRT clients per target and uses isolated
comparison data. It does not run another engine build or use a shared FRT server.

Reporting needs a `flutter_win` executor. A macOS-only SDK run skips FRT and reporting.
That executor needs Git, FRT repository access, and `WINDOWS_PYTHON -m uv` for
the report checkout and aggregation.

On the Windows packaging/capture agent:

- Provide the native app-build tools and a graphical desktop for desktop capture.
  Use the FRT README for its current Python and runtime prerequisites.
- Install the `uv` Python package for the interpreter that runs the adapter:
  `WINDOWS_PYTHON` on Windows and `python3` on macOS. The adapter calls that
  interpreter with `-m uv`; a standalone executable on `PATH` is insufficient.
- For Web, install Edge in its standard Windows location or set
  `WSC_FRT_BROWSER` to an existing Chrome/Edge executable. Jenkins does not
  download a browser or silently substitute one when the configured choice fails.
- Keep capture settings consistent and serialize desktop comparisons across
  jobs sharing a desktop. `disableConcurrentBuilds()` only serializes one branch
  job, not all jobs on an agent.
- Install Jenkins' JUnit plugin. The pipeline publishes Test Result entries and
  archives `artifacts/frt-junit.xml` as well as the comparison ZIP.

Each comparison uses a temporary Gradle home. This isolates dependency caches;
it does not clear the SDK's warm Flutter cache or bypass CDN caching. Current
CI targets do not exercise Android Maven downloads, so retain the separate
[SDK acceptance checks](../../DEPLOYMENT.MD#5-accept-the-sdks-before-distribution).

The adapter removes its `frt-input-*` directory (baseline download and Gradle
home) on ordinary completion or failure. FRT also removes its temporary SDK
extractions and client source/build work directories. The result tree remains,
including copied client bundles, comparison database, reports, and logs; the
pipeline does not prune it. A crashed agent can leave temporary directories.
Inspect abandoned directories and apply your team's result-retention policy
without cleaning persistent engine workspaces.

## Commission capture on the actual agents

Before relying on unattended comparisons, check that the setup works on your
Jenkins agents:

1. A passing pair produces complete reports and Jenkins test results.
2. An intentional mismatch makes the build unstable.
3. A capture/build failure or missing expected report makes the build fail.
4. The comparison ZIP opens locally, evidence stays private, and notifications
   and temporary-directory cleanup work.
5. Desktop capture works with the agent's actual session, display settings,
   and other jobs. Source tests do not establish this.

The comparison watchdog is 90 minutes; aggregation has a 20-minute watchdog.
A watchdog abort is not a rendering result. Keep incomplete comparisons pending
and record a separate developer-run comparison if needed for release review.

## Target placement and later mobile coverage

| Target | Current Jenkins capture |
| --- | --- |
| Windows | Windows packaging agent |
| macOS | Disabled (SDK packaging remains enabled) |
| Web | Windows packaging agent, headless Chromium; Edge by default |
| Android | Not integrated |
| iOS | Not integrated |

Engine compilation stays on its existing hosts; it is separate from where FRT
runs consumer applications. Chromium coverage does not establish Safari support.
Desktop/Web results do not establish mobile or physical-device rendering.

Before adding mobile CI, validate FRT capture on the actual emulator, simulator,
or device using the FRT README. Record device/runtime and rendering settings,
and retain representative physical-device checks for deployed hardware.
