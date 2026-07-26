# Paperless release-driven image publishing

## Goal

Publish the Paperless plugin image only when either:

1. paperless-ngx publishes a new stable or pre-release container version, or
2. this plugin changes on the default branch.

The published image tag must exactly match the official paperless-ngx container
tag, without the leading `v` used by GitHub Releases.

## Release discovery

An hourly GitHub Actions job polls the official paperless-ngx GitHub Releases
API. It selects the newest non-draft release, including pre-releases, and removes
one leading `v` from `tag_name`.

Before testing or building, the workflow verifies that
`ghcr.io/paperless-ngx/paperless-ngx:<version>` exists and resolves its manifest
digest. A missing upstream image is treated as a temporary release-publication
delay, not as a plugin failure.

For scheduled runs, the workflow checks whether
`ghcr.io/maxinger15/paperless-paddleocr:<version>` already exists. If it does,
the workflow exits successfully without rebuilding. Default-branch plugin
changes and manual default-branch runs rebuild the current Paperless version
even when that tag already exists.

## Compatibility gate

The resolved Paperless version and manifest digest are the single source of
truth for tests and builds. The workflow must not test `latest` and publish a
different version or digest.

Before publication it performs:

1. plugin installation and parser-discovery smoke testing inside the exact
   upstream Paperless image;
2. a candidate image build using `PAPERLESS_TAG=<version>`;
3. the deterministic Paperless-to-PaddleX-stub E2E against that candidate,
   covering parser discovery, OCRmyPDF, hOCR, searchable PDF/A, stored content,
   and rotation;
4. an ARM64 candidate build and import/parser smoke under QEMU.

Any failed test blocks publication. The separate real PP-OCRv6 service smoke
remains independent because a Paperless release does not change the pinned
PaddleX service runtime.

## Publication

After all compatibility jobs pass, Buildx publishes one multi-platform manifest
for:

- `linux/amd64`
- `linux/arm64`

The immutable build input is
`ghcr.io/paperless-ngx/paperless-ngx:<version>@sha256:<digest>`. Published tags
are:

- `<version>`, matching the official Paperless container tag;
- `latest`, updated only after the versioned build passes.

Plugin changes intentionally replace `<version>` with a new image containing
the updated plugin but the same pinned Paperless base. OCI labels record the
plugin commit and upstream Paperless version. SBOM and provenance attestations
remain enabled.

The PaddleOCR service image keeps its independent publication policy and is not
rebuilt by Paperless release polling.

## Triggers and authorization

- `schedule`: discover releases and publish only a missing Paperless tag;
- default-branch `push`: test and rebuild the newest Paperless version;
- default-branch `workflow_dispatch`: force a test and rebuild;
- non-default branches and Git tags: no package-write publication.

The workflow keeps `contents: read` and `packages: write`, uses SHA-pinned
actions, and cancels superseded runs for the same publication channel.

## Failure behavior

- GitHub API failure: fail without publishing.
- Draft release: ignore.
- Upstream release exists but its container tag does not: exit successfully
  with a clear notice so the next scheduled poll retries.
- Existing downstream tag during a scheduled run: exit successfully without
  testing or building.
- Compatibility test or build failure: fail without updating either version or
  `latest` tags.
- Registry authentication or push failure: fail and retain previously
  published tags.

## Documentation

The README will describe release-driven builds, stable and pre-release support,
exact Paperless version tags, the mutable nature of a tag after plugin changes,
the `latest` alias, test gates, and manual source-build pinning.
