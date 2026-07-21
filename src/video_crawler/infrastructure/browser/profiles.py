from __future__ import annotations

import re
from pathlib import Path

_PROFILE_DIRECTORY_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,100}")


def validate_profile_directory(name: str) -> str:
    """Return a safe browser Profile directory name.

    Profile references are single directory names, never paths. Keeping this
    validation independent of the host OS also rejects Windows separators when
    API validation runs in a Linux container.
    """

    if name in {".", ".."} or _PROFILE_DIRECTORY_PATTERN.fullmatch(name) is None:
        raise ValueError(
            "profile directory must be 1-100 characters using only letters, "
            "numbers, '.', '_', or '-'"
        )
    return name


def resolve_profile_path(root: Path, name: str) -> Path:
    """Resolve a validated Profile directory below the configured root."""

    safe_name = validate_profile_directory(name)
    resolved_root = root.resolve()
    resolved_profile = (resolved_root / safe_name).resolve()
    if not resolved_profile.is_relative_to(resolved_root):
        raise ValueError("profile directory must resolve inside the Profile root")
    return resolved_profile
