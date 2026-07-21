from __future__ import annotations

from pathlib import Path

import pytest

from video_crawler.infrastructure.browser import profiles


@pytest.mark.parametrize(
    "name",
    ["../x", "/absolute", "a/b", "a\\b", "", ".", "..", "x" * 101],
)
def test_profile_directory_rejects_unsafe_names(name: str) -> None:
    with pytest.raises(ValueError, match="profile directory"):
        profiles.validate_profile_directory(name)


@pytest.mark.parametrize("name", ["bilibili-main_01", "profile.v2", "A-1_b"])
def test_profile_directory_accepts_safe_names(name: str) -> None:
    assert profiles.validate_profile_directory(name) == name


def test_profile_path_resolves_inside_root(tmp_path: Path) -> None:
    root = tmp_path / "profiles"

    result = profiles.resolve_profile_path(root, "bilibili-main_01")

    assert result == root.resolve() / "bilibili-main_01"
    assert result.is_relative_to(root.resolve())


def test_profile_path_rejects_traversal_before_resolution(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="profile directory"):
        profiles.resolve_profile_path(tmp_path, "../outside")
