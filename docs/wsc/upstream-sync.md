# Synchronizing upstream Git history

Use [sync_upstream.py](../../dev/bots/sync_upstream.py) to make upstream Flutter
history available in the client's fork. This is separate from replaying patches,
building SDKs, or promoting WSC channel refs.

| Source on `upstream` | Destination on `origin` |
| --- | --- |
| Every branch `<name>` | Branch `upstream/<name>` at the same commit |
| Every tag `<name>` | Tag `<name>` with the identical Git object |

All other destination branches, including `main`, `master`, `beta`, `stable`
and WSC development branches, are untouched. Destination-only tags (including
WSC releases) are retained. Git objects reachable from these branches/tags are
transferred, not GitHub PR metadata, dependency checkouts or build artifacts.

## Running the sync

Requires Python 3.10+ and Git 2.31+ (`rev-parse --path-format=absolute`).
Preview needs read access to both remotes; applying changes also needs fork write access.
Configure `upstream` as the official Flutter repository and `origin` as the
client's fork. Use normal Git credential helpers or SSH; do not put secrets in
remote URLs. Repository-local authentication settings are not copied into the
temporary repository; use your user-level credential helper/SSH configuration.

From the source checkout:

```sh
git remote -v
python dev/bots/sync_upstream.py
python dev/bots/sync_upstream.py --apply
```

To also remove mirrored branches that disappeared upstream, preview and apply
with `--prune`:

```sh
python dev/bots/sync_upstream.py --prune
python dev/bots/sync_upstream.py --prune --apply
```

The first invocation previews changes using remote ref lists only. `--apply`
fetches upstream history into a temporary bare repository and requests an atomic
push; a server that does not advertise atomic pushes is rejected, with no fallback
to non-atomic publication. The helper waits one second before verifying the
published refs. A mismatch or failed read gets up to two additional read-only
attempts, five seconds apart; the push is never retried automatically.
Unchanged runs are a no-op. Source changes during fetch abort before pushing;
rerun the preview. The apply invocation computes a fresh plan, not a saved one.

On a push/connection failure, inspect a fresh preview before retrying. Some Git
server policies (notably hidden-ref rejection) can still accept a subset of refs
despite `--atomic`, and a lost connection does not prove the server rejected the
push. The helper reports failure without rolling back accepted refs. Fix the
server policy/authentication issue and rerun; equal refs are skipped safely.

`--repo PATH` selects the checkout whose remote configuration to read. By default
this is the repository containing the script, regardless of your working
directory. `--source NAME` and `--destination NAME` select alternative **named
remotes**. The destination's push URL is used, and multiple URLs are rejected.
That URL must support `ls-remote` for preview and verification, object fetching
for apply's lease checks, and pushes; a write-only endpoint is insufficient.

The fixed `upstream/*` destination namespace is owned by synchronization. Applying
the sync updates it even if upstream rewrote a branch; never develop WSC changes
there. Only planned changes are pushed, with leases on the previously observed
commits (or absence for new refs). The plan is stored in temporary Git config;
temporary tracking refs supply the expected branch commits. These refs are
checked against the initial destination snapshot and never refreshed before
pushing. This keeps the command short on Windows even for thousands of refs,
while preserving a single atomic push. A concurrent change
to a branch being updated or deleted rejects the push rather than overwriting
that change. Prefer serial sync runs to avoid these failures. Tags are
never replaced: only missing tags are pushed, with absence required by the lease.
Any same-name/different-object tag, including a changed annotation, stops the
entire sync. Investigate conflicts; do not reseat published tags.

Without `--prune`, stale mirrored branches are reported and retained. With
`--prune`, only branches under `refs/heads/upstream/` absent from the source
snapshot are listed as `DELETE` and removed on apply, in the same atomic push as
updates. An empty source branch list is rejected, and a changed source snapshot
during fetch aborts before any push. Use the official upstream remote with full
branch visibility: the helper cannot distinguish hidden branches from deleted
ones. All tags are retained, including tags removed upstream; they share a
namespace with client-owned release tags. Other destination branches are never
pruned. A branch-name collision such as `upstream/foo` versus new
`upstream/foo/bar` may still require reviewed cleanup if the server cannot delete
and create those names in one transaction; there is no non-atomic fallback.

## Scope and integration

- Local branches, tags, index, working files and engine outputs are not changed.
  A dirty source checkout is fine. Repository-selection environment overrides
  such as `GIT_DIR` or `GIT_WORK_TREE` are rejected before running Git; unset the
  variables named in the error and retry. Existing Git objects are borrowed read-only
  from a non-shallow checkout to reduce transfer; missing objects use temporary
  storage. A shallow checkout needs an independent full upstream download.
  Temporary storage is removed on normal exit/error; allow room for missing
  history and do not concurrently prune the borrowed object store.
- This does **not** refresh your local `upstream/*` remote-tracking refs/tags.
  Continue using `git fetch upstream --tags` when preparing a local rebase.
- Run before the [upstream-update workflow](updating.md), or schedule separately
  once commissioned. No Jenkins changes, builds or schedule are created by the
  helper. Exclude `upstream/*` from Jenkins discovery/building; pushes can still
  notify external webhooks configured on the repository.
- Fetching newly mirrored tags can affect upstream's numeric fallback for
  untagged SDK versions. Exact WSC release tags remain the release identity;
  see [versioning](releases.md#version-and-channel-identity).
- Updating the unprefixed WSC channel refs belongs to the separately reviewed
  release/development flow, never this script.

Offline tests use disposable local repositories only:

```sh
python -m unittest discover -s dev/bots -p test_sync_upstream.py
```
