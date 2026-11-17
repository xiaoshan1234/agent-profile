#!/usr/bin/env python3
"""Validate the role catalog and every deployable skill source."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from rebuild_catalog import rebuild
from repo_lib import (
    PROFILE_RE,
    RepoError,
    catalog_skills,
    common_skill_ids,
    ensure_unique_installed_names,
    repo_root_from_script,
    resolve_catalog_entry,
    role_manifest,
    selected_skill_ids,
)


def validate(root: Path, *, check_generated: bool) -> int:
    errors: List[str] = []
    catalog = catalog_skills(root)
    common = common_skill_ids(root)
    if len(common) != len(set(common)):
        errors.append("catalog/common.json contains duplicate skill ids")

    for skill_id, raw in sorted(catalog.items()):
        try:
            entry = resolve_catalog_entry(root, catalog, skill_id)
            if entry["source"] == "hermes" and raw.get("installed_as") is None:
                errors.append(f"{skill_id}: Hermes registry skills should set installed_as")
        except RepoError as exc:
            errors.append(str(exc))

    role_count = 0
    for role_json in sorted((root / "roles").glob("*/role.json")):
        role_count += 1
        role = role_json.parent.name
        try:
            role_dir, manifest = role_manifest(root, role)
            if not PROFILE_RE.fullmatch(role):
                errors.append(f"{role}: invalid profile id")
            for skill_id in [*common, *manifest.get("skills", [])]:
                if str(skill_id) not in catalog:
                    errors.append(f"{role}: unknown skill id {skill_id}")
            selected = selected_skill_ids(root, role)
            entries = [
                (skill_id, resolve_catalog_entry(root, catalog, skill_id))
                for skill_id in selected
                if skill_id in catalog
            ]
            ensure_unique_installed_names(entries)
            soul = manifest.get("soul", {})
            if not isinstance(soul, dict):
                errors.append(f"{role}: soul must be an object")
            elif soul.get("mode") == "file":
                path = role_dir / str(soul.get("file", ""))
                if not path.is_file():
                    errors.append(f"{role}: missing SOUL file {path}")
            elif soul.get("mode") == "compose":
                for file_value in soul.get("files", []):
                    path = role_dir / str(file_value)
                    if not path.is_file():
                        errors.append(f"{role}: missing SOUL input {path}")
        except RepoError as exc:
            errors.append(str(exc))

    if check_generated and not errors:
        return rebuild(root, check=True)

    if errors:
        print("Validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print(
        f"Validated {role_count} roles, {len(catalog)} catalog skills, "
        f"and {len(common)} shared skills."
    )
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate roles, catalog entries, and skill sources.")
    parser.add_argument(
        "--check-generated",
        action="store_true",
        help="Also fail if catalog/skills.json or role SKILLS.md files are stale",
    )
    args = parser.parse_args(argv)
    try:
        return validate(repo_root_from_script(__file__), check_generated=args.check_generated)
    except RepoError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
