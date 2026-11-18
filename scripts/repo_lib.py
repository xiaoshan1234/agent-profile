"""Shared helpers for the Hermes skill repository."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

SCHEMA_VERSION = 1
PROFILE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
RESERVED_PROFILES = {"default", "hermes", "root", "sudo", "test", "tmp"}
COPY_IGNORE = ("__pycache__", ".DS_Store", "*.pyc", "*.pyo", ".git")


class RepoError(RuntimeError):
    """A user-facing repository or deployment error."""


def repo_root_from_script(script_file: str) -> Path:
    return Path(script_file).resolve().parent.parent


def load_json(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RepoError(f"Missing JSON file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RepoError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RepoError(f"Expected a JSON object in {path}")
    return value


def write_json_atomic(path: Path, value: Dict[str, Any]) -> bool:
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return write_text_atomic(path, text)


def write_text_atomic(path: Path, text: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temp, path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    return True


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def validate_profile_name(name: str) -> str:
    normalized = str(name).strip().lower()
    if not PROFILE_RE.fullmatch(normalized):
        raise RepoError(
            f"Invalid Hermes profile name {name!r}; use lowercase letters, "
            "digits, '-' or '_'."
        )
    if normalized in RESERVED_PROFILES:
        raise RepoError(f"Reserved Hermes profile name: {normalized}")
    return normalized


def validate_single_segment(value: str, label: str) -> str:
    text = str(value).strip()
    if not text or text in {".", ".."} or "/" in text or "\\" in text:
        raise RepoError(f"{label} must be a single non-empty path segment: {value!r}")
    return text


def validate_skill_id(value: str) -> tuple[str, str, str]:
    raw = str(value).strip().strip("/")
    parts = raw.split("/")
    if len(parts) != 2:
        raise RepoError(f"Skill id must be '<domain>/<name>': {value!r}")
    domain = validate_single_segment(parts[0], "skill domain")
    name = validate_single_segment(parts[1], "skill name")
    return domain, name, f"{domain}/{name}"


def safe_repo_path(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise RepoError(f"Path escapes the repository: {relative}") from exc
    return candidate


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def parse_frontmatter(skill_md: Path) -> Dict[str, Any]:
    try:
        text = skill_md.read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise RepoError(f"Missing skill entrypoint: {skill_md}") from exc
    if not text.startswith("---"):
        raise RepoError(f"SKILL.md has no frontmatter: {skill_md}")
    match = re.search(r"\n---\s*\n", text[3:])
    if not match:
        raise RepoError(f"Unclosed SKILL.md frontmatter: {skill_md}")
    header = text[3 : match.start() + 3]
    result: Dict[str, Any] = {}
    lines = header.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line or line[0].isspace() or ":" not in line:
            index += 1
            continue
        key, value = line.split(":", 1)
        if key.strip() in {"name", "description"}:
            value = value.strip()
            if value in {">", ">-", "|", "|-"}:
                block: List[str] = []
                index += 1
                while index < len(lines):
                    candidate = lines[index]
                    if candidate.strip() and not candidate[0].isspace():
                        break
                    block.append(candidate.strip())
                    index += 1
                separator = " " if value.startswith(">") else "\n"
                result[key.strip()] = separator.join(part for part in block if part)
                continue
            result[key.strip()] = _unquote(value)
        index += 1
    if not result.get("description"):
        raise RepoError(f"SKILL.md is missing description: {skill_md}")
    return result


def skill_metadata(skill_dir: Path) -> Dict[str, str]:
    metadata = parse_frontmatter(skill_dir / "SKILL.md")
    metadata["name"] = metadata.get("name") or skill_dir.name
    return metadata


def common_skill_ids(root: Path) -> List[str]:
    data = load_json(root / "catalog" / "common.json")
    values = data.get("skills", [])
    if not isinstance(values, list):
        raise RepoError("catalog/common.json skills must be a list")
    return [str(value) for value in values]


def catalog_skills(root: Path) -> Dict[str, Dict[str, Any]]:
    data = load_json(root / "catalog" / "skills.json")
    values = data.get("skills")
    if not isinstance(values, dict):
        raise RepoError("catalog/skills.json skills must be an object")
    return {str(key): dict(value) for key, value in values.items() if isinstance(value, dict)}


def role_manifest(root: Path, role: str) -> tuple[Path, Dict[str, Any]]:
    role_dir = (root / "roles" / role).resolve()
    try:
        role_dir.relative_to((root / "roles").resolve())
    except ValueError as exc:
        raise RepoError(f"Invalid role path: {role}") from exc
    if not role_dir.is_dir():
        raise RepoError(f"Role not found: {role}")
    data = load_json(role_dir / "role.json")
    if int(data.get("schema", 0)) not in {1, 2}:
        raise RepoError(f"Unsupported role schema in {role_dir / 'role.json'}")
    if data.get("name") != role_dir.name:
        raise RepoError(f"Role name does not match directory: {role_dir}")
    skills = data.get("skills", [])
    if not isinstance(skills, list):
        raise RepoError(f"Role skills must be a list: {role_dir / 'role.json'}")
    return role_dir, data


def selected_skill_ids(root: Path, role: str) -> List[str]:
    _, role = role_manifest(root, role)
    ordered: List[str] = []
    for value in [*common_skill_ids(root), *role.get("skills", [])]:
        skill_id = str(value)
        if skill_id not in ordered:
            ordered.append(skill_id)
    return ordered


def resolve_catalog_entry(
    root: Path, catalog: Dict[str, Dict[str, Any]], skill_id: str
) -> Dict[str, Any]:
    if skill_id not in catalog:
        raise RepoError(f"Skill is missing from catalog/skills.json: {skill_id}")
    entry = dict(catalog[skill_id])
    source = str(entry.get("source", "")).strip()
    if source not in {"local", "vendor", "file", "hermes"}:
        raise RepoError(f"Unsupported source {source!r} for skill {skill_id}")
    installed_as = validate_single_segment(
        str(entry.get("installed_as") or skill_id), f"installed_as for {skill_id}"
    )
    entry["installed_as"] = installed_as
    if source in {"local", "vendor", "file"}:
        relative = str(entry.get("path", "")).strip()
        if not relative:
            raise RepoError(f"Skill {skill_id} has no catalog path")
        skill_path = safe_repo_path(root, relative)
        if not (skill_path / "SKILL.md").is_file():
            raise RepoError(f"Skill {skill_id} has no SKILL.md at {skill_path}")
        entry["_path"] = str(skill_path)
    elif not str(entry.get("identifier", "")).strip():
        raise RepoError(f"Hermes registry skill {skill_id} has no identifier")
    return entry


def merged_role_manifest(root: Path, role: str) -> tuple[Path, Dict[str, Any]]:
    role_dir, manifest = role_manifest(root, role)
    merged = dict(manifest)
    merged["skills"] = selected_skill_ids(root, role)
    return role_dir, merged


def ensure_unique_installed_names(entries: Iterable[tuple[str, Dict[str, Any]]]) -> None:
    seen: Dict[str, str] = {}
    for skill_id, entry in entries:
        installed_as = str(entry["installed_as"])
        previous = seen.get(installed_as)
        if previous is not None:
            raise RepoError(
                f"Skills {previous} and {skill_id} both install as {installed_as!r}"
            )
        seen[installed_as] = skill_id


def relative_display_path(from_dir: Path, target: Path) -> str:
    return Path(os.path.relpath(target, from_dir)).as_posix()


def backup_path(profile_dir: Path, relative: str) -> Path:
    return profile_dir / ".role-deploy" / "backups" / utc_stamp() / relative

