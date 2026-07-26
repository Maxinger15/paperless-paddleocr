#!/usr/bin/env python3
"""Resolve the newest published Paperless release into an OCI image tag.

The script deliberately has no network client.  GitHub Actions can fetch the
release payload with its own authenticated client and pass a saved response via
``--input``.  Keeping resolution pure makes the release-selection rules easy to
test and avoids credential handling in this utility.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


OCI_TAG_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")


class ReleaseResolutionError(ValueError):
    """Raised when a GitHub Releases payload cannot produce a usable tag."""


@dataclass(frozen=True)
class ResolvedRelease:
    """The upstream GitHub tag and its matching official container tag."""

    github_tag: str
    paperless_tag: str

    def as_dict(self) -> dict[str, str]:
        return {
            "github_tag": self.github_tag,
            "paperless_tag": self.paperless_tag,
        }


def official_container_tag(github_tag: str) -> str:
    """Remove one leading ``v`` and validate the resulting OCI tag."""
    if not isinstance(github_tag, str):
        raise ReleaseResolutionError("Release tag_name must be a string.")

    container_tag = github_tag.removeprefix("v")
    if not OCI_TAG_PATTERN.fullmatch(container_tag):
        raise ReleaseResolutionError(
            "Release tag_name does not produce a safe OCI tag after removing one leading 'v'."
        )
    return container_tag


def release_timestamp(release: dict[str, object]) -> datetime:
    """Return a validated release timestamp, preferring ``published_at``."""
    timestamp = release.get("published_at")
    field_name = "published_at"
    if timestamp is None:
        timestamp = release.get("created_at")
        field_name = "created_at"

    if not isinstance(timestamp, str):
        raise ReleaseResolutionError(
            f"Every non-draft GitHub release must contain an ISO 8601 {field_name} timestamp."
        )

    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError as error:
        raise ReleaseResolutionError(
            f"GitHub release {field_name} must be an ISO 8601 timestamp."
        ) from error
    if parsed.tzinfo is None:
        raise ReleaseResolutionError(f"GitHub release {field_name} timestamp must include a timezone.")
    return parsed


def resolve_releases(releases: object) -> ResolvedRelease:
    """Select the newest non-draft release, including prereleases."""
    if not isinstance(releases, list):
        raise ReleaseResolutionError("GitHub Releases payload must be a JSON array.")

    candidates: list[tuple[datetime, ResolvedRelease]] = []
    for release in releases:
        if not isinstance(release, dict):
            raise ReleaseResolutionError("Every GitHub release must be a JSON object.")

        draft = release.get("draft")
        if not isinstance(draft, bool):
            raise ReleaseResolutionError("Every GitHub release must contain a boolean draft field.")
        if draft:
            continue

        tag_name = release.get("tag_name")
        if not isinstance(tag_name, str):
            raise ReleaseResolutionError("Every non-draft GitHub release must contain a string tag_name.")
        candidates.append(
            (
                release_timestamp(release),
                ResolvedRelease(
                    github_tag=tag_name,
                    paperless_tag=official_container_tag(tag_name),
                ),
            )
        )

    if not candidates:
        raise ReleaseResolutionError("GitHub Releases payload contains no non-draft release.")

    return max(candidates, key=lambda candidate: (candidate[0], candidate[1].github_tag))[1]


def resolve_release_json(payload: str) -> ResolvedRelease:
    """Decode a GitHub Releases JSON response and resolve its container tag."""
    try:
        releases: Any = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ReleaseResolutionError("GitHub Releases payload is not valid JSON.") from error
    return resolve_releases(releases)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Path to a GitHub Releases API JSON response fixture or downloaded response.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "line"),
        default="json",
        help="Emit deterministic JSON (default) or only the resolved Paperless tag.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        resolved = resolve_release_json(args.input.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print("Release resolution failed: Input file does not exist.", file=sys.stderr)
        return 2
    except (OSError, ReleaseResolutionError) as error:
        print(f"Release resolution failed: {error}", file=sys.stderr)
        return 2

    if args.format == "line":
        print(resolved.paperless_tag)
    else:
        print(json.dumps(resolved.as_dict(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
