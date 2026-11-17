#!/usr/bin/env python3
"""Import a local or GitHub skill and register it in the repository catalog."""

from __future__ import annotations

import argparse
import fnmatch
import os
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from repo_lib import (
    COPY_IGNORE,
    RepoError,
    load_json,
    relative_display_path,
    repo_root_from_script,
    role_manifest,
    skill_metadata,
    utc_stamp,
    validate_single_segment,
    write_json_atomic,
)


def _ignore(directory: str, names: List[str]) -> set[str]:
    return {
        name
        for name in names
        if any(fnmatch.fnmatch(name, pattern) for pattern in COPY_IGNORE)
    }


def _validate_source_tree(source: Path) -> Dict[str, str]:
    if not source.is_dir():
        raise RepoError(f"Skill source is not a directory: {source}")
    if not (source / "SKILL.md").is_file():
        raise RepoError(f"Skill source has no SKILL.md: {source}")
    for path in source.rglob("*"):
        if path.is_symlink():
            raise RepoError(f"Skill import rejects symbolic links: {path}")
    return skill_metadata(source)


def _safe_extract(archive: zipfile.ZipFile, destination: Path) -> None:
    base = destination.resolve()
    for member in archive.infolist():
        target = (destination / member.filename).resolve()
        try:
            target.relative_to(base)
        except ValueError as exc:
            raise RepoError(f"Archive path escapes extraction directory: {member.filename}") from exc
    archive.extractall(destination)


def _download_github_skill(repo: str, ref: str, subpath: str, temp_dir: Path) -> Path:
    if "/" not in repo or repo.startswith("/") or ".." in Path(repo).parts:
        raise RepoError(f"Invalid GitHub repo: {repo}")
    normalized_path = Path(subpath)
    if normalized_path.is_absolute() or ".." in normalized_path.parts:
        raise RepoError(f"Invalid GitHub skill path: {subpath}")
    quoted_ref = urllib.parse.quote(ref, safe="")
    url = f"https://codeload.github.com/{repo}/zip/{quoted_ref}"
    archive_path = temp_dir / "repo.zip"
    request = urllib.request.Request(url, headers={"User-Agent": "agent-profile-skill-import"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response, archive_path.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    except OSError as exc:
        raise RepoError(f"GitHub download failed for {repo}@{ref}: {exc}") from exc

    extract_dir = temp_dir / "archive"
    extract_dir.mkdir()
    try:
        with zipfile.ZipFile(archive_path) as archive:
            _safe_extract(archive, extract_dir)
    except zipfile.BadZipFile as exc:
        raise RepoError(f"GitHub returned an invalid archive for {repo}@{ref}") from exc
    roots = [path for path in extract_dir.iterdir() if path.is_dir()]
    if len(roots) != 1:
        raise RepoError(f"Unexpected GitHub archive layout for {repo}@{ref}")
    return roots[0] / normalized_path


def _replace_with_copy(source: Path, destination: Path, repo_root: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.importing-{os.getpid()}"
    if temporary.exists():
        shutil.rmtree(temporary)
    try:
        shutil.copytree(source, temporary, ignore=_ignore)
        moved_backup: Optional[Path] = None
        if destination.exists():
            backup = (
                repo_root
                / ".cache"
                / "import-backups"
                / utc_stamp()
                / destination.parent.name
                / destination.name
            )
            if backup.exists():
                backup = backup.with_name(f"{backup.name}.{os.getpid()}")
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(destination), str(backup))
            moved_backup = backup
        try:
            os.replace(temporary, destination)
        except BaseException:
            if destination.exists():
                shutil.rmtree(destination, ignore_errors=True)
            if moved_backup is not None and moved_backup.exists():
                shutil.move(str(moved_backup), str(destination))
            raise
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)


def _register(
    repo_root: Path,
    skill_id: str,
    entry: Dict[str, Any],
    *,
    common: bool,
    role: Optional[str],
) -> None:
    catalog_path = repo_root / "catalog" / "skills.json"
    catalog_doc = load_json(catalog_path)
    catalog = catalog_doc.get("skills")
    if not isinstance(catalog, dict):
        catalog = {}
    catalog[skill_id] = entry
    catalog_doc["schema"] = 1
    catalog_doc["skills"] = dict(sorted(catalog.items()))
    write_json_atomic(catalog_path, catalog_doc)

    if common and role:
        raise RepoError("--common and --role are mutually exclusive")
    if common:
        common_path = repo_root / "catalog" / "common.json"
        common_doc = load_json(common_path)
        values = [str(value) for value in common_doc.get("skills", [])]
        if skill_id not in values:
            values.append(skill_id)
        common_doc["skills"] = sorted(set(values))
        write_json_atomic(common_path, common_doc)
    elif role:
        role_dir, manifest = role_manifest(repo_root, role)
        values = [str(value) for value in manifest.get("skills", [])]
        if skill_id not in values:
            values.append(skill_id)
        manifest["skills"] = values
        write_json_atomic(role_dir / "role.json", manifest)


def import_skill(
    repo_root: Path,
    *,
    skill_id: str,
    from_dir: Optional[str],
    git: Optional[str],
    ref: str,
    git_path: Optional[str],
    hermes_identifier: Optional[str],
    kind: Optional[str],
    install_as: Optional[str],
    force: bool,
    common: bool,
    role: Optional[str],
) -> None:
    skill_id = validate_single_segment(skill_id, "skill id")
    modes = sum(bool(value) for value in (from_dir, git, hermes_identifier))
    if modes != 1:
        raise RepoError("Choose exactly one source: --from-dir, --git, or --hermes-identifier")
    if common and role:
        raise RepoError("--common and --role are mutually exclusive")
    if role:
        role_manifest(repo_root, role)

    explicit_install_as = (
        validate_single_segment(install_as, "installed_as") if install_as else None
    )
    catalog = load_json(repo_root / "catalog" / "skills.json").get("skills", {})
    if skill_id in catalog and not force:
        raise RepoError(f"Catalog id already exists: {skill_id}; pass --force to replace it")

    if hermes_identifier:
        entry: Dict[str, Any] = {
            "source": "hermes",
            "identifier": hermes_identifier.strip(),
            "installed_as": explicit_install_as or skill_id,
            "description": "Remote Hermes registry skill.",
        }
        _register(repo_root, skill_id, entry, common=common, role=role)
        print(f"registered Hermes registry skill {skill_id}: {hermes_identifier}")
        return

    selected_kind = kind or ("local" if from_dir else "vendor")
    if selected_kind not in {"local", "vendor"}:
        raise RepoError("--kind must be local or vendor")
    destination = repo_root / "skills" / selected_kind / skill_id

    with tempfile.TemporaryDirectory(prefix="skill-import-") as temp_name:
        temp_dir = Path(temp_name)
        if from_dir:
            source = Path(from_dir).expanduser().resolve()
        else:
            if not git_path:
                raise RepoError("--git requires --git-path")
            source = _download_github_skill(str(git), ref, git_path, temp_dir)
        metadata = _validate_source_tree(source)
        if destination.exists() and not force:
            raise RepoError(f"Skill directory already exists: {destination}")
        if source == destination:
            raise RepoError("Source and destination are the same directory")
        _replace_with_copy(source, destination, repo_root)

    entry = {
        "source": selected_kind,
        "path": relative_display_path(repo_root, destination),
        "installed_as": explicit_install_as or metadata["name"],
        "description": metadata["description"],
    }
    if git:
        entry["origin"] = {"repo": git, "ref": ref, "path": git_path}
    _register(repo_root, skill_id, entry, common=common, role=role)
    print(f"imported {skill_id} -> {destination}")
    print("Run ./scripts/rebuild-catalog.py to refresh generated role indexes.")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import a self-authored directory or GitHub skill into the repository."
    )
    parser.add_argument("--id", required=True, help="Stable catalog id")
    parser.add_argument("--from-dir", help="Self-authored local skill directory")
    parser.add_argument("--git", help="GitHub repository as owner/repo")
    parser.add_argument("--ref", default="main", help="Git ref for --git")
    parser.add_argument("--git-path", help="Skill directory inside the GitHub repository")
    parser.add_argument("--hermes-identifier", help="Pin a skill by Hermes registry identifier")
    parser.add_argument("--kind", choices=["local", "vendor"], help="Local source bucket")
    parser.add_argument("--install-as", help="Installed directory name")
    parser.add_argument("--force", action="store_true", help="Replace an existing catalog id")
    parser.add_argument("--common", action="store_true", help="Add to every role")
    parser.add_argument("--role", help="Add to one role's role.json")
    args = parser.parse_args(argv)
    try:
        import_skill(
            repo_root_from_script(__file__),
            skill_id=args.id,
            from_dir=args.from_dir,
            git=args.git,
            ref=args.ref,
            git_path=args.git_path,
            hermes_identifier=args.hermes_identifier,
            kind=args.kind,
            install_as=args.install_as,
            force=args.force,
            common=args.common,
            role=args.role,
        )
        return 0
    except (RepoError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
