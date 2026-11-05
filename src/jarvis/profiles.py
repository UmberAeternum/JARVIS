"""Mark XIX - profiles: isolated config/memory/conversations per identity.

The pre-existing single-profile data IS the "default" profile: its directory
is unchanged, so migration is a no-op and no data can be lost. Additional
profiles live at <base>/profiles/<name>/ and are picked up automatically by
every module because all of them resolve config.config_dir() dynamically.

The active profile is recorded in <base>/profile (a plain text name). A
context manager, config.using_profile(), temporarily overrides it for
export/import and tests.
"""

from __future__ import annotations

import re

from . import config

NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-]{0,31}")
DEFAULT = "default"


def validate_name(name: str) -> str:
    name = (name or "").strip()
    if not NAME_PATTERN.fullmatch(name):
        raise ValueError(
            "profile name must be 1-32 chars: letters, digits, '-' or '_' "
            "(must start with a letter or digit)"
        )
    return name


def profile_dir(name: str):
    return config._base_dir() / "profiles" / name


def list_profiles() -> list[dict]:
    """All known profiles: default first, then alphabetical, active marked."""
    active = config.active_profile()
    entries = [{"name": DEFAULT, "active": active == DEFAULT, "path": config._base_dir()}]
    root = config._base_dir() / "profiles"
    if root.is_dir():
        for child in sorted(root.iterdir()):
            if child.is_dir():
                entries.append(
                    {"name": child.name, "active": active == child.name, "path": child}
                )
    return entries


def profile_exists(name: str) -> bool:
    return any(entry["name"] == name for entry in list_profiles())


def create_profile(name: str) -> dict:
    name = validate_name(name)
    target = profile_dir(name)
    if target.exists():
        raise ValueError(f"profile '{name}' already exists")
    target.mkdir(parents=True)
    return {"name": name, "path": target}


def use_profile(name: str) -> str:
    if name != DEFAULT:
        name = validate_name(name)
        if not profile_exists(name):
            raise ValueError(f"profile '{name}' does not exist - create it first")
    config.set_active_profile(name)
    return name


def _remove_tree(path) -> None:
    """Delete a directory tree without shutil.rmtree - explicit and auditable."""
    if not path.exists():
        return
    for child in sorted(path.iterdir(), reverse=True):
        if child.is_dir():
            _remove_tree(child)
        else:
            child.unlink()
    path.rmdir()


def delete_profile(name: str) -> str:
    name = validate_name(name)
    if name == DEFAULT:
        raise ValueError("the default profile is the original data and cannot be deleted")
    if config.active_profile() == name:
        raise ValueError(f"profile '{name}' is active - switch away from it first")
    target = profile_dir(name)
    if not target.exists():
        raise ValueError(f"profile '{name}' does not exist")
    _remove_tree(target)
    return name
