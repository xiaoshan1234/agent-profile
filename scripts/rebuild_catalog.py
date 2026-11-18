#!/usr/bin/env python3
"""Scan skill sources, update the catalog, and render role skill indexes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from repo_lib import (
    SCHEMA_VERSION,
    RepoError,
    common_skill_ids,
    load_json,
    relative_display_path,
    repo_root_from_script,
    role_manifest,
    skill_metadata,
    write_json_atomic,
    write_text_atomic,
)


def _catalog_entry(root: Path, source: str, skill_dir: Path) -> Dict[str, Any]:
    metadata = skill_metadata(skill_dir)
    return {
        "source": source,
        "path": relative_display_path(root, skill_dir),
        "installed_as": metadata["name"],
        "description": metadata["description"],
    }


def _domain_catalog_entry(
    root: Path,
    domain: str,
    skill_dir: Path,
    existing: Dict[str, Dict[str, Any]],
    legacy: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    metadata = skill_metadata(skill_dir)
    previous = existing.get(f"{domain}/{skill_dir.name}", {})
    origin = previous.get("origin")
    if not isinstance(origin, dict):
        legacy_source = str((legacy or {}).get("source", ""))
        origin_type = "vendor" if legacy_source in {"vendor", "file"} else "local"
        origin = {"type": origin_type, "note": "Migrated into the domain layout."}
    return {
        "source": "file",
        "domain": domain,
        "path": relative_display_path(root, skill_dir),
        "installed_as": str(previous.get("installed_as") or metadata["name"]),
        "description": metadata["description"],
        "origin": origin,
    }


def _scan_sources(root: Path, existing: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    catalog: Dict[str, Dict[str, Any]] = {}
    for key, value in existing.items():
        source = str(value.get("source", ""))
        path_value = str(value.get("path", "")).strip()
        if source in {"local", "vendor", "file"} and path_value:
            if not (root / path_value / "SKILL.md").is_file():
                continue
        catalog[key] = dict(value)
    seen_paths: Dict[str, Path] = {}
    for source in ("local", "vendor"):
        base = root / "skills" / source
        if not base.is_dir():
            continue
        for skill_dir in sorted(path for path in base.iterdir() if path.is_dir()):
            if not (skill_dir / "SKILL.md").is_file():
                continue
            skill_id = skill_dir.name
            previous_path = seen_paths.get(skill_id)
            if previous_path is not None:
                raise RepoError(
                    f"Duplicate skill id {skill_id!r}: {previous_path} and {skill_dir}"
                )
            previous_entry = catalog.get(skill_id)
            if previous_entry and previous_entry.get("source") == "hermes":
                raise RepoError(
                    f"Skill id {skill_id!r} is already registered as a Hermes remote skill"
                )
            seen_paths[skill_id] = skill_dir
            discovered = _catalog_entry(root, source, skill_dir)
            merged = dict(catalog.get(skill_id, {}))
            for key, value in discovered.items():
                merged.setdefault(key, value)
            merged["source"] = source
            merged["path"] = discovered["path"]
            merged.setdefault("installed_as", discovered["installed_as"])
            merged["description"] = discovered["description"]
            catalog[skill_id] = merged
    for domain_dir in sorted(path for path in (root / "skills").iterdir() if path.is_dir()):
        domain = domain_dir.name
        if domain in {"local", "vendor"}:
            continue
        for skill_dir in sorted(path for path in domain_dir.iterdir() if path.is_dir()):
            if not (skill_dir / "SKILL.md").is_file():
                continue
            skill_id = f"{domain}/{skill_dir.name}"
            previous_path = seen_paths.get(skill_id)
            if previous_path is not None:
                raise RepoError(
                    f"Duplicate skill id {skill_id!r}: {previous_path} and {skill_dir}"
                )
            seen_paths[skill_id] = skill_dir
            legacy = catalog.get(skill_dir.name)
            catalog[skill_id] = _domain_catalog_entry(
                root,
                domain,
                skill_dir,
                existing,
                legacy,
            )
    return dict(sorted(catalog.items()))


def _render_index(
    root: Path, role: str, catalog: Dict[str, Dict[str, Any]]
) -> str:
    role_dir, manifest = role_manifest(root, role)
    common = common_skill_ids(root)
    specific = [str(value) for value in manifest.get("skills", [])]
    def item(skill_id: str) -> str:
        entry = catalog.get(skill_id)
        if entry is None:
            raise RepoError(f"Role {role} references unknown skill: {skill_id}")
        description = str(entry.get("description", "")).strip()
        source = str(entry.get("source", "")).strip()
        if source in {"local", "vendor", "file"}:
            target = (root / str(entry["path"])).resolve()
            link = relative_display_path(role_dir, target)
            label = f"[{skill_id}]({link})"
        else:
            label = f"`{skill_id}`"
        suffix = f" — {description}" if description else ""
        source_note = f" ({source})" if source == "hermes" else ""
        return f"- {label}{suffix}{source_note}"

    lines = [
        "# Skill Index",
        "",
        "Generated by `scripts/rebuild_catalog.py`; edit `role.json` or the skill catalog instead.",
        "",
        "## Shared",
        "",
    ]
    lines.extend(item(skill_id) for skill_id in common)
    lines.extend(["", "## Role-specific", ""])
    if specific:
        lines.extend(item(skill_id) for skill_id in specific)
    else:
        lines.append("_No role-specific skills._")
    return "\n".join(lines) + "\n"


def rebuild(root: Path, *, check: bool) -> int:
    catalog_path = root / "catalog" / "skills.json"
    existing = load_json(catalog_path)
    existing_skills = existing.get("skills", {})
    if not isinstance(existing_skills, dict):
        raise RepoError("catalog/skills.json skills must be an object")
    catalog = _scan_sources(root, existing_skills)
    new_catalog = {"schema": SCHEMA_VERSION, "skills": catalog}

    changed: List[str] = []
    if check:
        desired_catalog = json.dumps(new_catalog, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        current_catalog = catalog_path.read_text(encoding="utf-8")
        if current_catalog != desired_catalog:
            changed.append(str(catalog_path.relative_to(root)))
    elif write_json_atomic(catalog_path, new_catalog):
        changed.append(str(catalog_path.relative_to(root)))

    role_dirs = sorted(
        path for path in (root / "roles").iterdir() if path.is_dir() and (path / "role.json").is_file()
    )
    for role_dir in role_dirs:
        index_path = role_dir / "SKILLS.md"
        desired = _render_index(root, role_dir.name, catalog)
        if check:
            current = index_path.read_text(encoding="utf-8") if index_path.is_file() else None
            if current != desired:
                changed.append(str(index_path.relative_to(root)))
        elif write_text_atomic(index_path, desired):
            changed.append(str(index_path.relative_to(root)))

    if check:
        if changed:
            print("Catalog/index drift detected:")
            for path in changed:
                print(f"  {path}")
            return 1
        print(f"Catalog and {len(role_dirs)} role indexes are up to date.")
        return 0

    if changed:
        for path in changed:
            print(f"updated {path}")
    else:
        print("Catalog and role indexes are already up to date.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan local/vendor skills, update catalog/skills.json, and render role indexes."
    )
    parser.add_argument("--check", action="store_true", help="Fail when generated files are stale")
    args = parser.parse_args(argv)
    try:
        return rebuild(repo_root_from_script(__file__), check=args.check)
    except RepoError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
