from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.resolve_paperless_release import (
    ReleaseResolutionError,
    main,
    official_container_tag,
    resolve_release_json,
)


def test_selects_newest_stable_release() -> None:
    resolved = resolve_release_json(
        json.dumps(
            [
                {"draft": False, "tag_name": "v2.20.3", "published_at": "2026-07-25T11:00:00Z"},
                {"draft": False, "tag_name": "v2.20.2", "published_at": "2026-07-24T11:00:00Z"},
            ]
        )
    )

    assert resolved.github_tag == "v2.20.3"
    assert resolved.paperless_tag == "2.20.3"


def test_includes_newest_prerelease() -> None:
    resolved = resolve_release_json(
        json.dumps(
            [
                {
                    "draft": False,
                    "prerelease": True,
                    "tag_name": "v3.0.0-rc.1",
                    "published_at": "2026-07-25T11:00:00Z",
                },
                {
                    "draft": False,
                    "prerelease": False,
                    "tag_name": "v2.20.3",
                    "published_at": "2026-07-24T11:00:00Z",
                },
            ]
        )
    )

    assert resolved.paperless_tag == "3.0.0-rc.1"


def test_skips_newest_draft_release() -> None:
    resolved = resolve_release_json(
        json.dumps(
            [
                {"draft": True, "tag_name": "v3.0.0", "published_at": "2026-07-26T11:00:00Z"},
                {"draft": False, "tag_name": "v2.20.3", "published_at": "2026-07-25T11:00:00Z"},
            ]
        )
    )

    assert resolved.paperless_tag == "2.20.3"


def test_selects_newest_release_when_entries_are_out_of_order() -> None:
    resolved = resolve_release_json(
        json.dumps(
            [
                {"draft": False, "tag_name": "v2.20.2", "published_at": "2026-07-24T11:00:00Z"},
                {"draft": False, "tag_name": "v2.20.3", "published_at": "2026-07-25T11:00:00Z"},
            ]
        )
    )

    assert resolved.paperless_tag == "2.20.3"


def test_uses_created_at_when_published_at_is_null() -> None:
    resolved = resolve_release_json(
        json.dumps(
            [
                {
                    "draft": False,
                    "tag_name": "v2.20.3",
                    "published_at": None,
                    "created_at": "2026-07-25T11:00:00Z",
                },
                {"draft": False, "tag_name": "v2.20.2", "published_at": "2026-07-24T11:00:00Z"},
            ]
        )
    )

    assert resolved.paperless_tag == "2.20.3"


def test_strips_exactly_one_leading_v() -> None:
    assert official_container_tag("vv2.20.3") == "v2.20.3"


def test_preserves_tag_without_leading_v() -> None:
    assert official_container_tag("2.20.3") == "2.20.3"


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "not json",
        "{}",
        "[]",
        '[{"draft": false}]',
        '[{"draft": "false", "tag_name": "v2.20.3"}]',
        '[{"draft": false, "tag_name": "v2.20.3"}]',
        '[{"draft": false, "tag_name": "v2.20.3", "published_at": "not-a-date"}]',
        '[{"draft": false, "tag_name": "v2.20.3", "published_at": null}]',
        '[{"draft": false, "tag_name": "v2.20.3", "published_at": null, "created_at": "not-a-date"}]',
    ],
)
def test_rejects_empty_or_malformed_input(payload: str) -> None:
    with pytest.raises(ReleaseResolutionError):
        resolve_release_json(payload)


@pytest.mark.parametrize(
    "github_tag",
    [
        "",
        "v",
        "v tag",
        "v2.20.3/latest",
        "v2.20.3@sha256",
        "v" + "a" * 129,
    ],
)
def test_rejects_empty_or_unsafe_oci_tags(github_tag: str) -> None:
    with pytest.raises(ReleaseResolutionError):
        official_container_tag(github_tag)


def test_cli_outputs_deterministic_json_and_line_format(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture = tmp_path / "releases.json"
    fixture.write_text(
        '[{"draft": false, "tag_name": "v2.20.3", "published_at": "2026-07-25T11:00:00Z"}]',
        encoding="utf-8",
    )

    assert main(["--input", str(fixture)]) == 0
    assert capsys.readouterr().out == '{"github_tag":"v2.20.3","paperless_tag":"2.20.3"}\n'

    assert main(["--input", str(fixture), "--format", "line"]) == 0
    assert capsys.readouterr().out == "2.20.3\n"


@pytest.mark.parametrize(
    "fixture_name, contents, expected_error",
    [
        ("missing.json", None, "Input file does not exist."),
        ("malformed.json", "not json", "GitHub Releases payload is not valid JSON."),
    ],
)
def test_cli_reports_missing_or_malformed_input(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fixture_name: str,
    contents: str | None,
    expected_error: str,
) -> None:
    fixture = tmp_path / fixture_name
    if contents is not None:
        fixture.write_text(contents, encoding="utf-8")

    assert main(["--input", str(fixture)]) == 2
    assert capsys.readouterr().err == f"Release resolution failed: {expected_error}\n"
