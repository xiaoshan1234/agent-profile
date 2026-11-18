---
name: skill-converter
description: Convert Codex, OpenClaw, or generic skills to Hermes format.
version: 0.1.0
author: Agent Profile Contributors, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [skills, conversion, codex, openclaw, hermes]
    related_skills: [skill-maker, find-skill-hermes]
---

# Skill Converter

Convert an existing skill directory into a Hermes-compatible skill package. The converter normalizes frontmatter and packaging deterministically; it preserves the original body and reports tool or platform assumptions that need review.

## When to Use

- Importing a Codex, OpenClaw, Claude, or generic `SKILL.md` skill.
- Normalizing an existing local skill to Hermes frontmatter.
- Moving a skill into the repository's domain layout.

Do not use this skill to silently rewrite workflow semantics. Tool-name changes and source-specific command behavior require review after conversion.

## Prerequisites

- Python 3.9 or newer.
- Run commands from the repository root.
- Inspect the source skill's scripts, references, and external actions before running it.

## Convert a Skill

```text
terminal(command="python3 skills/shared/skill-converter/scripts/convert_skill.py --source <source-dir> --domain <domain> --name <hermes-name>", timeout=120)
```

Preview without writing:

```text
terminal(command="python3 skills/shared/skill-converter/scripts/convert_skill.py --source <source-dir> --domain <domain> --name <hermes-name> --dry-run", timeout=120)
```

Common options:

- `--description`: override the source description.
- `--version`: set the converted version, default `0.1.0`.
- `--author`: preserve the original author attribution.
- `--license`: set the source license; default is `UNKNOWN`.
- `--platforms linux,macos,windows`: override platform detection.
- `--force`: replace an existing converted package after creating a repository-local backup.

## Procedure

1. Inspect the source directory and identify its format. Completion criterion: source `SKILL.md`, support files, scripts, and external dependencies are accounted for.
2. Run the converter with `--dry-run` and review the planned destination and platform choice. Completion criterion: the target `<domain>/<name>` is correct.
3. Run the real conversion. Completion criterion: the destination contains `SKILL.md`, copied support files, and `references/conversion-report.md`.
4. Read the conversion report. Review every warning about tool names, OpenClaw metadata, Codex UI metadata, platform-specific commands, and credentials.
5. Edit the converted body if needed so commands and tools are valid for Hermes. Completion criterion: all executable instructions use available Hermes tools or explicitly documented CLIs.
6. Run `python3 scripts/rebuild_catalog.py` and `python3 scripts/validate_repo.py --check-generated`. Completion criterion: the new skill is cataloged and validation passes.
7. Test the converted skill in an isolated task before adding it to common skills or a role.

## Conversion Boundaries

Automatically handled:

- Hermes-required frontmatter fields.
- Description shortening to the Hermes 60-character limit, with a warning.
- Codex `agents/openai.yaml` removal.
- Cache and VCS file exclusion.
- Obvious macOS, Linux, and Windows platform markers.
- Source format and provenance reporting.

Reported for manual review:

- Claude/Codex tool names such as `Bash`, `Read`, `Write`, `Edit`, `Glob`, and `Grep`.
- OpenClaw `metadata.openclaw` requirements and invocation fields.
- Commands tied to Codex, Claude, OpenClaw, or skills.sh ecosystems.
- Credentials, network access, and destructive operations.

## Pitfalls

- Do not copy `agents/openai.yaml`; it is Codex UI metadata, not a Hermes skill requirement.
- Keep support files inside `scripts/`, `references/`, `templates/`, or `assets/`.
- Do not introduce absolute machine paths.
- Do not claim the converted skill is verified merely because frontmatter is valid.

## Verification

The conversion is complete when the package validates, the report has been reviewed, and any source-specific commands or tool names have an explicit Hermes-compatible resolution.
