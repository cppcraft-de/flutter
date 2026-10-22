# Local testing exceptions

This page records exceptions for one existing development workstation. Use
[the shared build setup](../../DEPLOYMENT.MD) unless you are maintaining that
workstation; these addresses and workspace names are specific to it.

Enable folder-property build-start exposure and set:

```ini
DISABLE_SCM_POLLING=1
WSC_ARTIFACT_BASE_URL=http://192.168.0.63:8765
WSC_HTTP_UPLOAD_BASE_URL=http://192.168.0.63:8765
```

Leave `BUILD_LOG_MAIL_RECIPIENT` unset. Create a secret-text credential
`HTTP_UPLOAD_KEY` containing a nonempty dummy value; the local PUT-capable server
can ignore the `AccessKey` header. It must also support origin GET for receipt
readback/existence checks and anonymous GET/HEAD with exact `Content-Length`,
`200` for existing files and `404` for absent files. Follow the
[upload and read contract](artifacts.md#upload-and-read-contract).
Plain Python `http.server` does not support PUT. The custom local server/start
script lives outside this repository.
Leave explicit URL/credential build parameters empty so they inherit these
properties. The Git credential must still be the real HTTPS username/token
credential; a dummy upload key does not grant source access.

This bare-root override may already contain pre-guard artifacts and therefore
need [reviewed adoption](artifacts.md#explicit-overwrite-and-first-adoption);
it does not inherit the empty-prefix assumption of the shared `ci-v2` default.

HTTPS works with Gradle's repository policy when its certificate is trusted.
The HTTP URLs above do not configure Gradle to allow an insecure Maven
repository. That opt-in is not implemented by this pipeline. Before Android
acceptance, decide whether to serve this local mirror over HTTPS or separately
review a local Gradle configuration that permits HTTP; the current HTTP setup
alone is insufficient evidence of Android acceptance.

## Temporary reuse of the pre-consolidation engine workspace

Only if reusing the existing local outputs, set **both**:

```ini
WSC_ENGINE_WORKSPACE_JOB=flutter_wsc/wsc-main-3.44.4
WSC_ENGINE_WORKSPACE_KEY=flutter_wsc/jenkins_build
```

The selector must match the full `JOB_NAME`, including parent folders. Only
that exact job gets the override; other branches keep their own paths. An
incomplete pair fails early. Keep the old `jenkins_build` job stopped: the normal
concurrency guard protects one branch job, not two jobs sharing a directory.
Do not move/copy these outputs to a new path to avoid a rebuild; Ninja files
can embed absolute paths.

For the shared build setup, leave both properties unset so each job uses its own
workspace. Remove this exception once local reuse is no longer needed, but
schedule the resulting path change/initial build deliberately. Do not delete
the older workspaces as an incidental cleanup step.

Changing properties does not immediately update installed polling schedules;
the pipeline must run once to apply them. Disabling polling does not cancel
existing queued work. No credential or Jenkins configuration changes are made
automatically by these instructions.
