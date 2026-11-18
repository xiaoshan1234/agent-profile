#!/usr/bin/env python3
"""Idempotently deploy a role's skills and SOUL to a Hermes profile."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from repo_lib import (
    COPY_IGNORE,
    RepoError,
    backup_path,
    catalog_skills,
    ensure_unique_installed_names,
    merged_role_manifest,
    repo_root_from_script,
    resolve_catalog_entry,
    utc_stamp,
    validate_profile_name,
)


@dataclass
class DeployOptions:
    role: str
    profile: Optional[str] = None
    description: Optional[str] = None
    soul: str = "role"
    no_alias: bool = False
    update_skills: bool = False
    dry_run: bool = False
    parts: str = "all"
    existing_only: bool = False


def _hermes_root() -> Path:
    raw = os.environ.get("HERMES_HOME", "").strip()
    home = Path(raw).expanduser() if raw else Path.home() / ".hermes"
    if not home.is_absolute():
        raise RepoError("HERMES_HOME must be an absolute path")
    if home.parent.name == "profiles":
        return home.parent.parent
    return home


def _resolve_executable(value: str) -> Optional[str]:
    candidate = Path(value).expanduser()
    if candidate.parent != Path(".") or candidate.is_absolute():
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
        return None
    return shutil.which(value)


def _profile_command(profile: str, hermes_bin: str, *args: str) -> List[str]:
    command = [hermes_bin]
    if profile != "default":
        command.extend(["-p", profile])
    command.extend(args)
    return command


def _run(command: List[str], *, dry_run: bool, cwd: Path) -> None:
    print("  $ " + " ".join(command))
    if dry_run:
        return
    subprocess.run(command, cwd=str(cwd), check=True)


def _ignore(directory: str, names: List[str]) -> set[str]:
    import fnmatch

    ignored = set()
    for name in names:
        if any(fnmatch.fnmatch(name, pattern) for pattern in COPY_IGNORE):
            ignored.add(name)
    return ignored


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.is_dir():
        return ""
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part in COPY_IGNORE for part in relative.parts):
            continue
        if any(part == "__pycache__" for part in relative.parts):
            continue
        if path.is_dir():
            continue
        if path.suffix in {".pyc", ".pyo"}:
            continue
        digest.update(relative.as_posix().encode("utf-8") + b"\0")
        mode = stat.S_IMODE(path.stat().st_mode)
        digest.update(str(mode & 0o111).encode("ascii") + b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _backup_existing(profile_dir: Path, target: Path, relative: str) -> Path:
    backup = backup_path(profile_dir, relative)
    backup.parent.mkdir(parents=True, exist_ok=True)
    if backup.exists():
        backup = backup.with_name(f"{backup.name}.{os.getpid()}")
    shutil.move(str(target), str(backup))
    return backup


def _install_skill_tree(
    source: Path,
    destination: Path,
    profile_dir: Path,
    *,
    update: bool,
) -> str:
    source_digest = _tree_digest(source)
    if destination.exists():
        if destination.is_dir() and _tree_digest(destination) == source_digest:
            return "unchanged"
        if not update:
            return "preserved"

    temporary = destination.parent / f".{destination.name}.installing-{os.getpid()}"
    if temporary.exists():
        shutil.rmtree(temporary)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(source, temporary, ignore=_ignore)
        moved_backup: Optional[Path] = None
        if destination.exists():
            moved_backup = _backup_existing(
                profile_dir, destination, f"skills/{destination.name}/{utc_stamp()}"
            )
        try:
            os.replace(temporary, destination)
        except BaseException:
            if destination.exists():
                shutil.rmtree(destination, ignore_errors=True)
            if moved_backup is not None and moved_backup.exists():
                shutil.move(str(moved_backup), str(destination))
            raise
        return "updated" if moved_backup is not None else "installed"
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)


def _role_soul_files(role_dir: Path, manifest: Dict[str, Any]) -> Tuple[Optional[str], List[Path]]:
    soul = manifest.get("soul", {})
    if not isinstance(soul, dict):
        raise RepoError(f"Role soul configuration must be an object: {role_dir}")
    mode = str(soul.get("mode", "compose"))
    if mode == "none":
        return None, []
    if mode == "file":
        file_value = str(soul.get("file", "")).strip()
        if not file_value:
            raise RepoError(f"Role soul mode 'file' requires a file: {role_dir}")
        files = [role_dir / file_value]
        label = file_value
    elif mode == "compose":
        values = soul.get("files", [])
        if not isinstance(values, list) or not values:
            raise RepoError(f"Role soul mode 'compose' requires files: {role_dir}")
        files = [role_dir / str(value) for value in values]
        label = " + ".join(str(value) for value in values)
    else:
        raise RepoError(f"Unsupported role soul mode {mode!r}: {role_dir}")
    for path in files:
        if not path.is_file():
            raise RepoError(f"SOUL source file not found: {path}")
    return label, files


def _resolve_soul(
    repo_root: Path, role_dir: Path, manifest: Dict[str, Any], value: str
) -> Tuple[Optional[str], Optional[str]]:
    if value == "none":
        return None, None
    if value == "role":
        configured = manifest.get("soul")
        if isinstance(configured, str):
            source = role_dir / configured
            if not source.is_file():
                raise RepoError(f"SOUL source file not found: {source}")
            return configured, source.read_text(encoding="utf-8-sig").rstrip() + "\n"
        label, files = _role_soul_files(role_dir, manifest)
        if not files:
            return None, None
        chunks = [path.read_text(encoding="utf-8-sig").rstrip() for path in files]
        return label, "\n\n---\n\n".join(chunks) + "\n"

    candidates = [
        Path(value).expanduser(),
        repo_root / "souls" / value,
        repo_root / "souls" / f"{value}.md",
        repo_root / value,
    ]
    source = next((path.resolve() for path in candidates if path.is_file()), None)
    if source is None:
        raise RepoError(
            f"SOUL not found: {value}. Use 'role', 'none', a file path, "
            "or a name under souls/."
        )
    return str(source), source.read_text(encoding="utf-8-sig").rstrip() + "\n"


def _write_soul(profile_dir: Path, content: Optional[str]) -> str:
    if content is None:
        return "unchanged"
    target = profile_dir / "SOUL.md"
    if target.is_file() and target.read_text(encoding="utf-8-sig") == content:
        return "unchanged"
    state = "updated" if target.exists() else "installed"
    moved_backup: Optional[Path] = None
    if target.exists():
        moved_backup = _backup_existing(profile_dir, target, f"SOUL.md/{utc_stamp()}")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".SOUL.md.", dir=profile_dir)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temp, target)
    except BaseException:
        if target.exists():
            target.unlink()
        if moved_backup is not None and moved_backup.exists():
            shutil.move(str(moved_backup), str(target))
        raise
    finally:
        temp.unlink(missing_ok=True)
    return state


def _description(options: DeployOptions, manifest: Dict[str, Any]) -> str:
    if options.description and options.description.strip():
        return options.description.strip()
    value = str(manifest.get("description", "")).strip()
    return value or f"Hermes role profile: {options.role}"


def deploy(repo_root: Path, options: DeployOptions) -> int:
    catalog = catalog_skills(repo_root)
    role_dir, manifest = merged_role_manifest(repo_root, options.role)
    profile_name = validate_profile_name(options.profile or options.role)
    profile_dir = _hermes_root() / "profiles" / profile_name
    profile_exists = profile_dir.is_dir()
    if options.existing_only and not profile_exists:
        raise RepoError(f"Profile does not exist: {profile_dir}")
    if options.parts not in {"all", "soul", "skills"}:
        raise RepoError(f"Unsupported deployment parts: {options.parts}")
    description = _description(options, manifest)
    deploy_soul = options.parts in {"all", "soul"}
    deploy_skills = options.parts in {"all", "skills"}
    if deploy_soul:
        soul_label, soul_content = _resolve_soul(
            repo_root, role_dir, manifest, options.soul
        )
    else:
        soul_label, soul_content = None, None

    resolved: List[Tuple[str, Dict[str, Any]]] = [
        (skill_id, resolve_catalog_entry(repo_root, catalog, skill_id))
        for skill_id in (manifest["skills"] if deploy_skills else [])
    ]
    ensure_unique_installed_names(resolved)

    hermes_bin_value = os.environ.get("HERMES_BIN", "hermes")
    hermes_bin = _resolve_executable(hermes_bin_value)
    needs_hermes = not profile_exists or any(
        entry["source"] == "hermes" for _, entry in resolved
    )
    if needs_hermes and hermes_bin is None:
        raise RepoError(f"Hermes executable not found: {hermes_bin_value}")

    print(f"Role:      {options.role}")
    print(f"Profile:   {profile_name}")
    print(f"Home:      {profile_dir}")
    print(f"Profile:   {'exists; creation skipped' if profile_exists else 'will be created'}")
    print(f"SOUL:      {soul_label or 'do not change'}")
    print(f"Parts:     {options.parts}")
    print(f"Skills:    {len(resolved)} selected")

    if options.dry_run:
        if not profile_exists:
            command = [
                str(hermes_bin or hermes_bin_value),
                "profile",
                "create",
                profile_name,
                "--no-skills",
                "--description",
                description,
            ]
            if options.no_alias:
                command.append("--no-alias")
            print("  $ " + " ".join(command))
        for skill_id, entry in resolved:
            target = profile_dir / "skills" / entry["installed_as"]
            action = "exists" if target.exists() else "install"
            print(f"  {action:<8} {skill_id} -> {entry['installed_as']}")
        return 0

    if not profile_exists:
        command = [
            str(hermes_bin),
            "profile",
            "create",
            profile_name,
            "--no-skills",
            "--description",
            description,
        ]
        if options.no_alias:
            command.append("--no-alias")
        _run(command, dry_run=False, cwd=repo_root)
        if not profile_dir.is_dir():
            raise RepoError(
                f"Hermes reported success but the profile directory is missing: {profile_dir}"
            )

    summary: Dict[str, int] = {}
    if deploy_skills:
        skills_root = profile_dir / "skills"
        skills_root.mkdir(parents=True, exist_ok=True)
        for skill_id, entry in resolved:
            destination = skills_root / entry["installed_as"]
            if entry["source"] in {"local", "vendor", "file"}:
                status = _install_skill_tree(
                    Path(entry["_path"]),
                    destination,
                    profile_dir,
                    update=options.update_skills,
                )
            else:
                if destination.is_dir() and not options.update_skills:
                    status = "preserved"
                elif destination.is_dir():
                    command = _profile_command(
                        profile_name,
                        str(hermes_bin),
                        "skills",
                        "update",
                        entry["installed_as"],
                        "--force",
                    )
                    _run(command, dry_run=False, cwd=repo_root)
                    status = "updated"
                else:
                    command = _profile_command(
                        profile_name,
                        str(hermes_bin),
                        "skills",
                        "install",
                        str(entry["identifier"]),
                        "--name",
                        entry["installed_as"],
                        "--yes",
                    )
                    if entry.get("category"):
                        command.extend(["--category", str(entry["category"])])
                    _run(command, dry_run=False, cwd=repo_root)
                    status = "installed"
            summary[status] = summary.get(status, 0) + 1
            print(f"  {status:<9} {skill_id} -> {destination}")

    soul_status = _write_soul(profile_dir, soul_content) if deploy_soul else "untouched"
    print(f"  soul      {soul_status}")
    print(
        "Summary: "
        + ", ".join(f"{key}={value}" for key, value in sorted(summary.items()))
        + f", soul={soul_status}"
    )
    return 0


def parse_args(argv: Optional[List[str]] = None) -> DeployOptions:
    parser = argparse.ArgumentParser(
        description="Create a Hermes profile if needed, deploy a role's skills, and select its SOUL."
    )
    parser.add_argument("role", help="Role directory name under roles/")
    parser.add_argument("--profile", help="Hermes profile name (default: role name)")
    parser.add_argument(
        "--parts",
        choices=["all", "soul", "skills"],
        default="all",
        help="Deploy SOUL, skills, or both (default: all)",
    )
    parser.add_argument(
        "--existing-only",
        action="store_true",
        help="Fail instead of creating a missing profile",
    )
    parser.add_argument("--soul", default="role", help="role, none, a soul name, or a file path")
    parser.add_argument("--description", help="Override the profile description at creation")
    parser.add_argument("--no-alias", action="store_true", help="Do not create a Hermes command alias")
    parser.add_argument(
        "--update-skills",
        action="store_true",
        help="Replace changed installed skills after backing them up",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the deployment plan only")
    args = parser.parse_args(argv)
    return DeployOptions(
        role=args.role,
        profile=args.profile,
        description=args.description,
        soul=args.soul,
        no_alias=args.no_alias,
        update_skills=args.update_skills,
        dry_run=args.dry_run,
        parts=args.parts,
        existing_only=args.existing_only,
    )


def main(argv: Optional[List[str]] = None) -> int:
    try:
        options = parse_args(argv)
        repo_root = repo_root_from_script(__file__)
        return deploy(repo_root, options)
    except (RepoError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
