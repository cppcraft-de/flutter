# Local testing exceptions

These settings are for the maintainer's existing installation, **not client
prerequisites**. Follow [DEPLOYMENT.MD](../../DEPLOYMENT.MD) for the shared setup.

Enable folder-property build-start exposure and set:

```ini
DISABLE_SCM_POLLING=1
WSC_ARTIFACT_BASE_URL=http://192.168.0.63:8765
WSC_HTTP_UPLOAD_BASE_URL=http://192.168.0.63:8765
```

Leave `BUILD_LOG_MAIL_RECIPIENT` unset. Create a secret-text credential
`HTTP_UPLOAD_KEY` containing a nonempty dummy value; the local PUT-capable server
can ignore the `AccessKey` header. Plain Python `http.server` does not support
PUT. The custom local server/start script lives outside this repository.
Leave explicit URL/credential build parameters empty so they inherit these
properties. The Git credential must still be the real HTTPS username/token
credential; a dummy upload key does not grant source access.

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

Client CI leaves both properties unset and naturally reuses its own per-job
workspaces. Remove this exception once local reuse is no longer needed, but
schedule the resulting path change/initial build deliberately. Do not delete
the older workspaces as an incidental cleanup step.

Changing properties does not immediately update installed polling schedules;
the pipeline must run once to apply them. Disabling polling does not cancel
existing queued work. No credential or Jenkins configuration changes are made
automatically by these instructions.
