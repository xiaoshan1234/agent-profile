#!/usr/bin/env python3
"""Scout role-relevant skills from GitHub / ClawHub / skills.sh and import them with provenance.

Dry-run by default: it only prints what it would import. `--apply` copies the
selected skills into `skills/<domain>/<name>` and records where they came from
(catalog origin + catalog/skill-sources.jsonl).

Discovery goes through `hermes skills search <single-keyword> --json`, which
already fans out to ClawHub, skills.sh, GitHub and the official registries.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from import_skill import import_skill
from repo_lib import RepoError, load_json, repo_root_from_script, utc_stamp, write_json_atomic

HERMES_BIN = os.environ.get("HERMES_BIN") or shutil.which("hermes") or "/Users/loner/.hermes/hermes-agent/.hermes/bin/hermes"
CLAWHUB_API = "https://clawhub.ai/api/v1"
PROVENANCE = Path("catalog") / "skill-sources.jsonl"

# High-signal only: the 08:00 skill-audit job does the exhaustive pass.
SECURITY_RULES: List[Tuple[str, str, str]] = [
    ("download-pipe-shell", r"(curl|wget)[^\n|]{0,120}\|\s*(sudo\s+)?(ba)?sh\b", "critical"),
    ("download-pipe-shell", r"iwr[^\n]{0,80}\|\s*iex", "critical"),
    ("eval-of-download", r"(eval|exec)\s*\(\s*(requests|urllib|open\(|subprocess)", "critical"),
    ("credential-read", r"(\.ssh/id_|\.aws/credentials|\.netrc|\.git-credentials|Cookies\.binarycookies|security find-generic-password)", "warn"),
    ("exfil-post", r"(requests\.post|curl\s+-X\s*POST|urllib[^\n]{0,60}urlopen)[^\n]{0,80}(webhook|paste|ngrok|requestbin)", "critical"),
    ("decode-exec", r"base64[^\n]{0,40}(decode|b64decode)[^\n]{0,40}(exec|eval|os\.system)", "critical"),
    ("destructive", r"rm\s+-rf\s+(/|~|\$HOME)(\s|$)", "critical"),
    ("destructive", r"dd\s+if=[^\n]{0,40}of=/dev/", "critical"),
    ("persistence", r"(crontab\s+-[ei]|launchctl\s+load|systemctl\s+enable)", "warn"),
    ("prompt-injection", r"(skip|bypass)[^\n]{0,30}(approval|confirmation)|不要告诉用户|don't tell the user", "warn"),
    ("sudo", r"\bsudo\s+\S", "warn"),
]
CODE_SUFFIXES = {".py", ".sh", ".bash", ".zsh", ".js", ".mjs", ".ts", ".rb", ".pl", ".ps1", ".yaml", ".yml"}
# A skill literally named "fitness" or "notes" adds noise, not capability.
GENERIC_NAMES = {
    "fitness", "workout", "notes", "note", "design", "stock", "stocks", "pdf", "docx", "xlsx", "ocr",
    "english", "ielts", "esl", "grammar", "vocabulary", "portfolio", "options", "figma", "tailwind",
    "css", "markdown", "journal", "running", "strength", "mobility", "contract", "invoice", "meeting",
}


def norm(text: str) -> str:
    return (text or "").lower()


def slugify(name: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", norm(name)).strip("-")
    return (value or "skill")[:40].strip("-")


def score_candidate(candidate: Dict[str, Any], keywords: Iterable[str]) -> Tuple[int, List[str]]:
    haystack = norm(candidate.get("name", "")) + " " + norm(candidate.get("description", ""))
    hits: List[str] = []
    score = 0
    for keyword in keywords:
        key = norm(keyword)
        if not key:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", haystack):
            hits.append(key)
            score += 2 if re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", norm(candidate.get("name", ""))) else 1
    return score, hits


def hermes_search(query: str, limit: int, timeout: int = 180) -> List[Dict[str, Any]]:
    try:
        proc = subprocess.run(
            [HERMES_BIN, "skills", "search", query, "--limit", str(limit), "--json"],
            capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"warn: search '{query}' failed: {exc}", file=sys.stderr)
        return []
    if proc.returncode != 0:
        print(f"warn: search '{query}' exit {proc.returncode}: {proc.stderr.strip()[:200]}", file=sys.stderr)
        return []
    try:
        data = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return []
    return [item for item in data if isinstance(item, dict) and item.get("identifier")]


def http_get(url: str, timeout: int = 60) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "agent-profile-role-scout"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def fetch_github_skill(owner: str, repo: str, wanted: str, hints: List[str], dest: Path, ref: str = "main") -> Optional[Path]:
    """Download one GitHub repo snapshot and return the skill directory inside it."""
    archive = dest / "repo.zip"
    if not archive.exists():
        try:
            archive.write_bytes(http_get(f"https://codeload.github.com/{owner}/{repo}/zip/{urllib.parse.quote(ref, safe='')}", timeout=180))
        except OSError as exc:
            print(f"warn: github {owner}/{repo}@{ref} download failed: {exc}", file=sys.stderr)
            return None
    extract = dest / "repo"
    if not extract.exists():
        extract.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(extract)
        except zipfile.BadZipFile:
            return None
    roots = [p for p in extract.iterdir() if p.is_dir()]
    if not roots:
        return None
    base = roots[0]
    candidates: List[Path] = []
    for skill_md in base.rglob("SKILL.md"):
        directory = skill_md.parent
        rel_parts = directory.relative_to(base).parts
        if hints and "/".join(rel_parts) == "/".join(hints):
            return directory
        if norm(directory.name) == norm(wanted):
            candidates.append(directory)
    return sorted(candidates, key=lambda p: len(p.parts))[0] if candidates else None


def fetch_clawhub_skill(slug: str, dest: Path) -> Optional[Path]:
    try:
        meta = json.loads(http_get(f"{CLAWHUB_API}/skills/{urllib.parse.quote(slug)}"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"warn: clawhub {slug} metadata failed: {exc}", file=sys.stderr)
        return None
    version = (meta.get("latestVersion") or {}).get("version")
    if not version:
        return None
    owner = (meta.get("owner") or {}).get("handle") or (slug.split("/")[0] if "/" in slug else None)
    params = {"slug": slug.split("/")[-1], "version": version}
    if owner:
        params["owner"] = owner
    url = f"{CLAWHUB_API}/download?{urllib.parse.urlencode(params)}"
    archive = dest / "skill.zip"
    try:
        archive.write_bytes(http_get(url, timeout=120))
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(dest / "files")
    except (OSError, zipfile.BadZipFile) as exc:
        print(f"warn: clawhub {slug} download failed: {exc}", file=sys.stderr)
        return None
    return dest / "files" if (dest / "files" / "SKILL.md").is_file() else None


def normalize_frontmatter_name(skill_dir: Path, name: str) -> None:
    """Make `name:` match the directory/claw slug so Hermes indexing and the 08:00 audit agree."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return
    text = skill_md.read_text(errors="ignore")
    if not text.startswith("---"):
        return
    end = text.find("\n---", 3)
    if end == -1:
        return
    head, body = text[:end], text[end:]
    lines = head.splitlines()
    replaced = False
    for index, line in enumerate(lines):
        if re.match(r"\s*name\s*:", line):
            lines[index] = f"name: {name}"
            replaced = True
            break
    if not replaced:
        lines.insert(1, f"name: {name}")
    skill_md.write_text("\n".join(lines) + body, encoding="utf-8")


def scan_tree(skill_dir: Path) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in CODE_SUFFIXES:
            continue
        try:
            lines = path.read_text(errors="ignore").splitlines()
        except OSError:
            continue
        for number, line in enumerate(lines, 1):
            for rule, pattern, severity in SECURITY_RULES:
                if re.search(pattern, line, re.IGNORECASE):
                    findings.append({"rule": rule, "severity": severity,
                                     "file": path.relative_to(skill_dir).as_posix(), "line": number})
    return findings


def plan_import(candidate: Dict[str, Any], preferred_name: str) -> Tuple[str, Dict[str, Any]]:
    """Work out how to fetch a candidate: ('github'|'clawhub', detail)."""
    identifier = str(candidate.get("identifier", ""))
    source = str(candidate.get("source", "")).lower()
    if source.startswith("clawhub") or (("/" not in identifier and not source.startswith("skill")) and source not in {"github", "skills.sh", "official"}):
        return "clawhub", {"slug": identifier.lstrip("@")}
    parts = [p for p in identifier.split("/") if p]
    if identifier.startswith("skills-sh/") and len(parts) >= 4:
        return "github", {"owner": parts[1], "repo": parts[2], "name": preferred_name,
                          "hints": [[*parts[3:-1], parts[-1]], ["skills", parts[-1]], [parts[-1]]]}
    if len(parts) >= 3:
        return "github", {"owner": parts[0], "repo": parts[1], "name": preferred_name,
                          "hints": [parts[2:], ["skills", *parts[2:]]]}
    return "unknown", {"identifier": identifier}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Find and import role-relevant skills with provenance.")
    parser.add_argument("--apply", action="store_true", help="Actually import (default: dry-run)")
    parser.add_argument("--max", type=int, help="Max imports this run (default: config max_per_day)")
    parser.add_argument("--max-per-role", type=int, help="Max imports per role")
    parser.add_argument("--roles", help="Comma separated subset of roles")
    parser.add_argument("--min-score", type=int)
    parser.add_argument("--ref", default="main", help="Git ref for GitHub downloads")
    parser.add_argument("--json", action="store_true", help="Print machine-readable summary")
    args = parser.parse_args(argv)

    repo_root = repo_root_from_script(__file__)
    config = load_json(repo_root / "catalog" / "scout-queries.json")
    roles: Dict[str, Any] = config.get("roles", {})
    if args.roles:
        wanted = {item.strip() for item in args.roles.split(",") if item.strip()}
        roles = {k: v for k, v in roles.items() if k in wanted}
        missing = wanted - set(roles)
        if missing:
            print(f"error: unknown roles: {sorted(missing)}", file=sys.stderr)
            return 2
    min_score = args.min_score if args.min_score is not None else int(config.get("min_score", 3))
    max_total = args.max if args.max is not None else int(config.get("max_per_day", 6))
    max_per_role = args.max_per_role if args.max_per_role is not None else int(config.get("max_per_role", 2))
    search_limit = int(config.get("search_limit", 10))

    catalog = load_json(repo_root / "catalog" / "skills.json").get("skills", {})
    taken_names = {str(entry.get("installed_as", "")).lower() for entry in catalog.values()}
    taken_names |= {Path(entry.get("path", "")).name.lower() for entry in catalog.values()}
    seen_identifiers = set()
    provenance_path = repo_root / PROVENANCE
    if provenance_path.is_file():
        for line in provenance_path.read_text(errors="ignore").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("decision") == "imported":
                seen_identifiers.add(record.get("identifier"))

    per_role: Dict[str, List[Dict[str, Any]]] = {}
    rejected: List[Dict[str, Any]] = []
    for role_name, role_config in roles.items():
        keywords = role_config.get("keywords", [])
        domain = role_config.get("domain", "shared")
        collected: Dict[str, Dict[str, Any]] = {}
        for query in role_config.get("queries", []):
            for candidate in hermes_search(str(query), search_limit):
                identifier = str(candidate["identifier"])
                if identifier in seen_identifiers or identifier in collected:
                    continue
                score, hits = score_candidate(candidate, keywords)
                if score < min_score:
                    continue
                slug = slugify(candidate.get("name", ""))
                if slug in GENERIC_NAMES or len(slug) < 5:
                    rejected.append({"role": role_name, "identifier": identifier, "name": candidate.get("name"),
                                     "reason": "名字过于宽泛/过短", "score": score})
                    continue
                if slug in taken_names:
                    rejected.append({"role": role_name, "identifier": identifier, "name": candidate.get("name"),
                                     "reason": "同名技能已在仓库", "score": score})
                    continue
                collected[identifier] = {**candidate, "role": role_name, "domain": domain,
                                         "score": score, "hits": hits}
        picked = sorted(collected.values(), key=lambda item: (-item["score"], str(item["identifier"])))
        per_role[role_name] = picked[:max_per_role]

    ordered = sorted((c for items in per_role.values() for c in items), key=lambda item: -item["score"])
    selected = ordered[:max_total]

    results: List[Dict[str, Any]] = []
    imported = 0
    for candidate in selected:
        identifier = str(candidate["identifier"])
        name = slugify(candidate.get("name", ""))
        skill_id = f"{candidate['domain']}/{name}"
        outcome = {"role": candidate["role"], "identifier": identifier, "name": name, "skill_id": skill_id,
                   "score": candidate["score"], "source": candidate.get("source"),
                   "trust": candidate.get("trust_level"), "description": (candidate.get("description") or "")[:160],
                   "decision": "planned", "note": ""}
        if skill_id in catalog or name in taken_names:
            outcome.update(decision="skipped", note="id/name 冲突")
            results.append(outcome)
            continue

        kind, detail = plan_import(candidate, name)
        if kind == "unknown":
            outcome.update(decision="skipped", note="无法解析 identifier")
            results.append(outcome)
            continue

        with tempfile.TemporaryDirectory(prefix="scout-") as temp_name:
            temp = Path(temp_name)
            if kind == "clawhub":
                staged = fetch_clawhub_skill(detail["slug"], temp)
                origin_url = f"https://clawhub.ai/skills/{detail['slug']}"
            else:
                staged = None
                for hint in detail.get("hints", []):
                    staged = fetch_github_skill(detail["owner"], detail["repo"], detail["name"], list(hint), temp, args.ref)
                    if staged:
                        break
                origin_url = f"https://github.com/{detail['owner']}/{detail['repo']}"
            if not staged:
                outcome.update(decision="skipped", note="内容拉取失败")
                results.append(outcome)
                continue
            findings = scan_tree(staged)
            criticals = [f for f in findings if f["severity"] == "critical"]
            warns = [f for f in findings if f["severity"] == "warn"]
            outcome["security"] = criticals + warns
            if criticals:
                outcome.update(decision="rejected", note=f"{len(criticals)} 条高危，未导入")
                results.append(outcome)
                continue
            if args.apply:
                normalize_frontmatter_name(staged, name)
                try:
                    import_skill(repo_root, skill_id=skill_id, from_dir=str(staged), git=None, ref=args.ref,
                                 git_path=None, hermes_identifier=None,
                                 origin_kind="vendor", install_as=name, force=False, common=False, role=None,
                                 origin_note=f"scout:{identifier}", origin_url=origin_url,
                                 origin_via=str(candidate.get("source") or kind))
                except (RepoError, OSError) as exc:
                    outcome.update(decision="failed", note=str(exc)[:160])
                    results.append(outcome)
                    continue
                imported += 1
                taken_names.add(name)
                outcome.update(decision="imported", note=(f"{len(warns)} 条可疑（未阻断）" if warns else ""))
            else:
                outcome.update(decision="would-import", note=(f"{len(warns)} 条可疑（未阻断）" if warns else ""))
        results.append(outcome)

    if args.apply and imported:
        stamp = utc_stamp()
        provenance_path.parent.mkdir(parents=True, exist_ok=True)
        with provenance_path.open("a", encoding="utf-8") as handle:
            for item in results:
                if item["decision"] != "imported":
                    continue
                handle.write(json.dumps({"at": stamp, **item}, ensure_ascii=False) + "\n")

    summary = {"mode": "apply" if args.apply else "dry-run", "roles": list(roles),
               "checked": len(roles), "selected": len(selected), "imported": imported,
               "rejected": rejected[:20], "results": results}
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"{summary['mode']}: roles={len(roles)} selected={len(selected)} imported={imported}")
        for item in results:
            mark = {"imported": "✅", "would-import": "→", "rejected": "⛔", "skipped": "·", "failed": "!"}.get(item["decision"], "?")
            print(f"  {mark} [{item['role']}] {item['identifier']}  score={item['score']} -> {item['skill_id']}"
                  + (f"  ({item['note']})" if item["note"] else ""))
        if rejected:
            print(f"  同名跳过 {len(rejected)} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
