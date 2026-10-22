# Copy official Flutter history into the fork

Use this guide when you want the official Flutter branches and tags available
in the Bitbucket repository. The [sync helper](../../dev/bots/sync_upstream.py)
copies that history without applying our patches or changing the fork's main,
beta, or stable branches.

To update the patches to a newer Flutter version, use
[Update to a new Flutter version](updating.md) instead. You can fetch directly
from official Flutter for that task; copying its history to Bitbucket is optional.

## Understand the branch names

There are two repositories: `upstream` is the official Flutter repository on
GitHub, and `origin` is this fork on Bitbucket. The sync helper stores copies of
official branches on Bitbucket with `upstream/` at the start of their names.
For example, it copies official `stable` to the branch named `upstream/stable`.
That prefix keeps the copy separate from our patched `stable` branch.

After fetching both repositories, Git shows these names locally:

| Name | Remote repository | Branch in that repository |
| --- | --- | --- |
| `upstream/stable` | `upstream` (official Flutter) | `stable` |
| `origin/upstream/stable` | `origin` (this fork) | `upstream/stable`, the unmodified Flutter copy |
| `origin/stable` | `origin` (this fork) | `stable`, the patched version |

In `origin/upstream/stable`, only `origin` names a remote. The remaining
`upstream/stable` is one branch name, not another remote or a folder. The same
pattern applies to beta, main, and other mirrored branches.

The script currently fixes this prefix to `upstream/`. Renaming those branches
requires a change to the script and a migration of the existing copies.

Tags keep their original names and Git objects. The helper preserves our
release tags and all branches outside `upstream/*`. It copies Git history,
not GitHub pull requests, engine dependencies, or build outputs.

## Preview and apply a sync

You need Python 3.10 or newer, Git 2.31 or newer, and read access to both
repositories. Applying the sync also needs write access to the fork.

Check the configured repository addresses:

```sh
git remote -v
```

`upstream` should point to `https://github.com/flutter/flutter.git` and `origin`
to the Bitbucket fork. Use your normal Git credential helper or SSH setup;
keep credentials out of URLs. The helper uses a temporary repository, so
repository-local authentication settings are not carried over.

Preview the changes:

```sh
python dev/bots/sync_upstream.py
```

Read the proposed branch and tag updates. Once reviewed, apply them:

```sh
python dev/bots/sync_upstream.py --apply
```

The apply command checks the repositories again; it does not reuse a saved
preview. Unchanged branches and tags are skipped. If official Flutter changes
while the helper is fetching, it stops before pushing. Run a fresh preview.

### Remove copies of deleted branches

Normally, the helper reports branches deleted from official Flutter but keeps
their Bitbucket copies. To remove those copies, preview with `--prune`:

```sh
python dev/bots/sync_upstream.py --prune
```

Review every `DELETE` entry before applying it:

```sh
python dev/bots/sync_upstream.py --prune --apply
```

Only mirrored branches under `upstream/*` can be deleted. Tags and the fork's
other branches are kept. Use the official repository with access to all its
branches: the helper cannot distinguish a hidden branch from a deleted one.

## If the sync fails

Run a fresh preview before retrying. A push or connection error does not prove
that nothing changed on the server. The helper requests an atomic push, but
some server policies can still accept only part of it. It reports failure and
does not undo changes already accepted by the server.

- **Another sync changed a branch:** the push checks that each affected branch
  still has the commit seen during planning. Fetching a newer plan and reviewing
  it resolves this; avoid running syncs concurrently.
- **A tag has the same name but different contents:** investigate the conflict.
  The helper refuses to replace tags, including changed tag annotations.
- **A branch name blocks another:** for example, `upstream/foo` can conflict
  with `upstream/foo/bar`. Review any required cleanup before retrying. The
  helper will not fall back to a sequence of unprotected pushes.
- **Authentication or server policy rejects the push:** fix that problem, then
  preview again. Changes that already reached the server will be skipped.

The helper verifies the remote branches and tags after pushing, with bounded
read retries. It never retries a push automatically. A server without atomic
push support is rejected.

## Options and local setup

- `--repo PATH`: read the remote configuration from that checkout. The default
  is the repository containing the script.
- `--source NAME` and `--destination NAME`: use different configured remote
  names. The destination's push URL must support reading branches and tags,
  fetching objects, and pushing. A write-only endpoint is insufficient;
  multiple URLs are rejected.
- Your local branches, tags, working files, and engine outputs stay unchanged.
  You can run the helper with uncommitted edits. If it reports a Git environment
  override such as `GIT_DIR`, unset the named variable and retry.
- Allow temporary disk space for missing Git history. A full local checkout
  lets the helper reuse existing objects; avoid pruning them during the sync.
- The helper does not refresh your local view of either repository. Use
  `git fetch upstream --tags` or `git fetch origin --tags` afterward as needed.
- Exclude the mirrored `upstream/*` branches from Jenkins build discovery.
  Pushes can trigger repository webhooks even though the helper starts no builds.

Fetching new tags can affect Flutter's version display for untagged builds.
The fork's release tags remain the way to identify releases; see
[versions and tags](releases.md#version-and-channel-identity).

## Test the helper

These tests use temporary local repositories:

```sh
python -m unittest discover -s dev/bots -p test_sync_upstream.py
```
