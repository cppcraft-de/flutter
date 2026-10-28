# Maintain the Flutter fork

This repository is a fork of Flutter. Its patches aim to make text rendering
and layout match Worksheet Crafter, the existing Qt application. It also adds
rendering diagnostics and CanvasKit PDF support, and includes the build pipeline
for distributing the patched Flutter SDK.

These guides are for developers who maintain those patches, update Flutter, and
build SDKs for the team. You need a working knowledge of Git and Flutter; the
guides explain the conventions specific to this repository. Applications use
the resulting SDK through the usual Flutter commands.

Existing filenames, settings, and release tags use the `wsc` prefix, short for
Worksheet Crafter. In these guides, **the fork** means this Flutter repository;
**upstream Flutter** means the official Flutter project.

## Update to a new Flutter version

**Start with [Update to a new Flutter version](updating.md).** It covers stable,
beta, and main, including updates that skip intermediate releases.

The workflow is:

1. Choose the Flutter version to update to.
2. Run the update helper to rebase the patches in your current folder.
3. Run dependency setup, resolve any patch conflicts, and run the checks and tests.
4. Build SDKs with Jenkins and check their rendering.
5. Release the tested version.

## Other common tasks

| I need to... | Start here |
| --- | --- |
| Copy upstream branches and tags into the fork | [Synchronize upstream history](upstream-sync.md) |
| Fix a Skia or FreeType patch after an update | [Prepare and fix dependency patches](dependency-patches.md) |
| Work on the engine locally | [Local engine development](engine-identity.md#local-engine-development) |
| Configure Jenkins or build an SDK for testing | [Build and distribute SDKs](../../DEPLOYMENT.MD) |
| Tag a release or update main, beta, or stable | [Release procedure](releases.md#release-procedure) |
| Review a rendering comparison from Jenkins | [Rendering results and acceptance](rendering-regression.md#outcomes-evidence-and-acceptance) |
| Run the font rendering tester (FRT) myself | [FRT README](https://bitbucket.org/schoolcraftteam/font_rendering_tester/src/master/README.md) |
| Diagnose missing downloads or a publication failure | [Artifacts and SDK packaging](artifacts.md) |

## Reference

- [Release versions and tags](releases.md#version-and-channel-identity): how the
  SDK identifies the Flutter version and the fork's patches.
- [Engine versions and downloads](engine-identity.md): how source commits,
  content hashes, and downloaded binaries fit together.
- [Local testing exceptions](local-testing.md): settings for the maintainer's
  workstation. You do not need these for the shared build setup.

Use the same `Jenkinsfile.testing` pipeline for test builds and releases.
Keep previous SDKs, their artifacts, and persistent build workspaces available
while validating an update.
