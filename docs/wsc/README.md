# Maintain the WSC Flutter fork

These guides are for developers who maintain this fork and build its SDKs.
They assume you know Flutter and Git. WSC adds font and text-layout changes,
rendering diagnostics, and CanvasKit PDF support. Its pipeline builds and
distributes the patched engine with a Flutter SDK.

Applications use the packaged SDK through the usual Flutter commands.
The guides below cover the work specific to maintaining this fork.

## Update to a new Flutter version

**Start with [Updating the WSC fork](updating.md)** to move to a stable release,
a beta release, or a selected commit on main. The guide takes you through
choosing the base, replaying WSC changes, fixing dependency patches, checking
the candidate, and handing it to CI.

The workflow is:

```text
Choose upstream base -> replay WSC changes -> check patches and source
                    -> build candidate SDKs -> review results -> release
```

## Other common tasks

| I need to... | Start here |
| --- | --- |
| Copy upstream branches and tags into the fork | [Synchronize upstream history](upstream-sync.md) |
| Fix a Skia or FreeType patch after an update | [Port dependency patches](dependency-patches.md) |
| Work on the engine locally | [Local engine development](engine-identity.md#local-engine-development) |
| Configure Jenkins or run a candidate build | [CI runbook](../../DEPLOYMENT.MD) |
| Tag a release or update a WSC channel | [Release procedure](releases.md#release-procedure) |
| Review a rendering comparison from Jenkins | [Rendering results and acceptance](rendering-regression.md#outcomes-evidence-and-acceptance) |
| Run the font rendering tester (FRT) myself | [FRT README](https://bitbucket.org/schoolcraftteam/font_rendering_tester/src/master/README.md) |
| Diagnose missing downloads or a publication failure | [Artifacts and SDK packaging](artifacts.md) |

## Reference

- [Release identity](releases.md#version-and-channel-identity): versions, tags,
  engine pins, and the implementation map.
- [Engine versions and downloads](engine-identity.md): how source commits,
  content hashes, and downloaded binaries fit together.
- [Local testing exceptions](local-testing.md): settings for the maintainer's
  workstation. Client CI does not need these.

Use the same `Jenkinsfile.testing` pipeline for candidates and releases.
Keep previous SDKs, their artifacts, and persistent build workspaces available
while validating an update.
