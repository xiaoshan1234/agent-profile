#!/usr/bin/env python3
"""Convert an existing skill directory into a Hermes-compatible package."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from repo_lib import (  # noqa: E402
    COPY_IGNORE,
    RepoError,
    parse_frontmatter,
    utc_stamp,
    validate_single_segment,
)

TOOL_PATTERNS = {
    r"\bBash\b": "terminal",
    r"\bRead\b": "read_file",
    r"\bWrite\b": "write_file",
    r"\bEdit\b": "patch",
    r"\bGrep\b|\bGlob\b": "search_files",
}


def _frontmatter_and_body(path: Path) -> tuple[str, str]:
    text = path.read_text(encoding="utf-8-sig")
    if not text.startswith("---"):
        return "", text
    match = re.search(r"\n---\s*\n", text[3:])
    if not match:
        raise RepoError(f"Unclosed SKILL.md frontmatter: {path}")
    header_end = 3 + match.start()
    body_start = 3 + match.end()
    return text[3:header_end], text[body_start:]


def _source_format(source: Path, frontmatter: str) -> str:
    if (source / "agents" / "openai.yaml").is_file():
        return "codex"
    if "metadata:" in frontmatter and "openclaw:" in frontmatter:
        return "openclaw"
    if (source / ".claude-plugin").exists() or (source / ".claude").exists():
        return "claude"
    return "generic"


def _description(value: str) -> tuple[str, bool]:
    text = " ".join(value.split()).strip()
    if not text:
        text = "Converted reusable workflow."
    changed = False
    if not text.endswith("."):
        text += "."
    if len(text) > 60:
        changed = True
        words = text[:-1].split()
        shortened: List[str] = []
        for word in words:
            candidate = " ".join([*shortened, word])
            if len(candidate) + 1 > 60:
                break
            shortened.append(word)
        text = (" ".join(shortened[:8]) or words[0][:58]).rstrip(".,;:") + "."
    return text, changed


def _platforms(body: str, override: Optional[str]) -> tuple[List[str], List[str]]:
    if override:
        values = [value.strip() for value in override.split(",") if value.strip()]
        invalid = set(values) - {"linux", "macos", "windows"}
        if invalid:
            raise RepoError(f"Invalid platform values: {', '.join(sorted(invalid))}")
        return values, []
    lower = body.lower()
    warnings: List[str] = []
    if "osascript" in lower or "pmset" in lower:
        warnings.append("macOS-specific command markers detected.")
        return ["macos"], warnings
    if "powershell" in lower or "pwsh" in lower:
        warnings.append("Windows command markers detected.")
        return ["windows"], warnings
    if "systemctl" in lower or re.search(r"\bapt(?:-get)?\b", lower):
        warnings.append("Linux-specific package or service command markers detected.")
        return ["linux"], warnings
    return ["linux", "macos", "windows"], warnings


def _ignore(directory: str, names: List[str]) -> set[str]:
    ignored = {
        name
        for name in names
        if any(fnmatch.fnmatch(name, pattern) for pattern in COPY_IGNORE)
    }
    if "agents" in names:
        ignored.add("agents")
    return ignored


def _replace_directory(source: Path, destination: Path) -> None:
    temporary = destination.parent / f".{destination.name}.converting-{os.getpid()}"
    if temporary.exists():
        shutil.rmtree(temporary)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(source, temporary, ignore=_ignore)
        moved_backup: Optional[Path] = None
        if destination.exists():
            backup = (
                REPO_ROOT
                / ".cache"
                / "conversion-backups"
                / utc_stamp()
                / destination.name
            )
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


def _report(
    source: Path,
    source_format: str,
    description_changed: bool,
    platform_warnings: List[str],
    body: str,
    has_openclaw_metadata: bool,
) -> str:
    warnings = list(platform_warnings)
    if description_changed:
        warnings.append("Description was shortened to satisfy the Hermes limit.")
    if (source / "agents" / "openai.yaml").is_file():
        warnings.append("Codex agents/openai.yaml was excluded from the converted package.")
    for pattern, replacement in TOOL_PATTERNS.items():
        count = len(re.findall(pattern, body))
        if count:
            warnings.append(
                f"Found {count} occurrence(s) of tool-like name matching `{pattern}`; "
                f"review whether `{replacement}` is appropriate."
            )
    if has_openclaw_metadata or "metadata.openclaw" in body:
        warnings.append("Review OpenClaw-style dependency metadata manually.")
    if not warnings:
        warnings.append("No automatic conversion warnings.")
    lines = [
        "# Conversion Report",
        "",
        f"- Source: `{source}`",
        f"- Detected format: `{source_format}`",
        f"- Converted at: `{utc_stamp()}`",
        "",
        "## Manual review",
        "",
    ]
    lines.extend(f"- {warning}" for warning in warnings)
    return "\n".join(lines) + "\n"


def convert(
    *,
    source_value: str,
    domain: str,
    name: str,
    description: Optional[str],
    version: str,
    author: str,
    license_name: str,
    platforms_value: Optional[str],
    force: bool,
    dry_run: bool,
) -> Path:
    source = Path(source_value).expanduser().resolve()
    if source.is_file():
        source_dir = source.parent
    elif source.is_dir():
        source_dir = source
    else:
        raise RepoError(f"Source not found: {source}")
    source_skill = source_dir / "SKILL.md"
    if not source_skill.is_file():
        raise RepoError(f"Source has no SKILL.md: {source_dir}")

    domain = validate_single_segment(domain, "domain")
    name = validate_single_segment(name, "name")
    destination = REPO_ROOT / "skills" / domain / name
    if destination == source_dir:
        raise RepoError("Source and destination are the same skill directory")
    if destination.exists() and not force:
        raise RepoError(f"Destination already exists: {destination}")

    frontmatter, body = _frontmatter_and_body(source_skill)
    metadata = parse_frontmatter(source_skill)
    source_format = _source_format(source_dir, frontmatter)
    final_description, description_changed = _description(
        description or metadata.get("description", "")
    )
    platforms, platform_warnings = _platforms(body, platforms_value)

    rendered = "\n".join(
        [
            "---",
            f"name: {json.dumps(name, ensure_ascii=False)}",
            f"description: {json.dumps(final_description, ensure_ascii=False)}",
            f"version: {json.dumps(version, ensure_ascii=False)}",
            f"author: {json.dumps(author, ensure_ascii=False)}",
            f"license: {json.dumps(license_name, ensure_ascii=False)}",
            f"platforms: [{', '.join(platforms)}]",
            "metadata:",
            "  hermes:",
            f"    tags: [{domain}, converted, {source_format}]",
            "    related_skills: []",
            f"    upstream_format: {json.dumps(source_format, ensure_ascii=False)}",
            "---",
            "",
            body.lstrip(),
        ]
    )
    if not rendered.endswith("\n"):
        rendered += "\n"

    print(f"Source:       {source_dir}")
    print(f"Format:       {source_format}")
    print(f"Destination:  {destination}")
    print(f"Description:  {final_description}")
    print(f"Platforms:    {', '.join(platforms)}")
    if dry_run:
        return destination

    _replace_directory(source_dir, destination)
    (destination / "SKILL.md").write_text(rendered, encoding="utf-8")
    references = destination / "references"
    references.mkdir(exist_ok=True)
    (references / "conversion-report.md").write_text(
        _report(
            source_dir,
            source_format,
            description_changed,
            platform_warnings,
            body,
            "openclaw:" in frontmatter,
        ),
        encoding="utf-8",
    )
    return destination


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Convert a skill into Hermes format.")
    parser.add_argument("--source", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--description")
    parser.add_argument("--version", default="0.1.0")
    parser.add_argument("--author", default="Original Skill Authors, Hermes Agent")
    parser.add_argument("--license", dest="license_name", default="UNKNOWN")
    parser.add_argument("--platforms", help="Comma-separated Hermes platform list")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        convert(
            source_value=args.source,
            domain=args.domain,
            name=args.name,
            description=args.description,
            version=args.version,
            author=args.author,
            license_name=args.license_name,
            platforms_value=args.platforms,
            force=args.force,
            dry_run=args.dry_run,
        )
        return 0
    except (RepoError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
