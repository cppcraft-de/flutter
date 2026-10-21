# WSC fork: agent entry point

Start with the [WSC maintenance guide](docs/wsc/README.md).
Read [DEPLOYMENT.MD](DEPLOYMENT.MD) for current CI behavior and configuration.
Use [release maintenance](docs/wsc/releases.md) for versioning/rebases and the
implementation map; use [artifact contracts](docs/wsc/artifacts.md) for storage
and packaging. Temporary workstation exceptions belong only in
[local testing](docs/wsc/local-testing.md).

For an upstream update, follow [Updating the WSC fork](docs/wsc/updating.md).
Humans and agents use the same procedure and helpers; source-check success is
not permission to publish or change rendering baselines.

## Working rules

For saved Jenkins email log archives, use the repo-local
[Jenkins log triage skill](.agents/skills/triage-jenkins-logs/SKILL.md).
It delegates read-only diagnosis; applying fixes needs separate authorization.

- Keep the single pipeline in `Jenkinsfile.testing`. Do not introduce a root
  `Jenkinsfile`, change Jenkins settings/credentials, launch builds, or move
  public refs unless the user authorizes that action.
- Preserve unrelated edits, nested dependency changes, and persistent engine
  workspaces. Do not clean/move build outputs as part of a docs or source task.
- Secrets belong in Jenkins credentials, never repository URLs, documentation,
  logs, or packaged SDK files. Folder properties are not secret storage.
- Preserve upstream tags and existing release artifacts. Keep WSC identity in
  the existing tag/version machinery rather than adding another source of truth.
- Before declaring a CI candidate ready, pushing it, or starting its build, run
  `python dev/bots/validate_sdk_identity.py --revision <full HEAD SHA>` against
  the integrated branch, even for docs/CI-only edits. Resolve stale pins using
  the [engine-pin procedure](docs/wsc/releases.md#engine-identity); local-only
  engine development should retain its published bootstrap pin.
- For docs changes, verify defaults against the pipeline and scripts. Update
  the owning reference and link to it; do not replicate setup tables in README.
- Report source tests, actual compilation, packaging, upload, and runtime
  acceptance separately. Do not present a proposed workflow as implemented or
  a local result as proof of client CI readiness.

The remainder of the root README and `docs/` includes upstream Flutter
documentation. Prefer a narrow WSC-specific entry/link over rewriting upstream
guides. Do not commit generated package configs, caches, or local helper files.
