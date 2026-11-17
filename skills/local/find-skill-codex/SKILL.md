---
name: find-skill
description: Find Codex skills across local and public registries.
metadata:
  short-description: Discover installable Codex skills
---

# Find Skill

Discover skills that can extend Codex, then help install a suitable result after approval. Search installed skills first, then Codex's official catalogs, then the broader skills.sh ecosystem.

## When to Use

- The user asks for a skill for a specific domain or workflow.
- The user asks whether an existing skill can provide a capability.
- The user wants to extend Codex with reusable instructions, scripts, or references.
- A repeatable workflow may already be packaged as a skill.

Do not use this skill to route unrelated requests through a catalog. If no installable skill is needed, complete the task normally.

## Sources

Search in this order:

1. Skills already installed under `${CODEX_HOME:-$HOME/.codex}/skills`.
2. OpenAI's curated and experimental catalogs in `openai/skills`.
3. The public skills.sh registry, whose entries normally resolve to GitHub repositories.

The registry is not exhaustive. Do not claim that a skill does not exist unless both the official catalogs and skills.sh have been checked.

## Procedure

1. Extract the domain, concrete task, and discriminating keywords. For example, turn "make my PDFs searchable" into `pdf OCR text extraction`.
2. Search installed skills:

```bash
SKILLS_ROOT="${CODEX_HOME:-$HOME/.codex}/skills"
rg -i -n --glob 'SKILL.md' 'pdf|ocr|text extraction' "$SKILLS_ROOT"
```

Read the matching `SKILL.md` descriptions and prefer an already installed skill over a duplicate.

3. List the official Codex catalogs:

```bash
INSTALLER="${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-installer/scripts"
python3 "$INSTALLER/list-skills.py" --path skills/.curated --format json
python3 "$INSTALLER/list-skills.py" --path skills/.experimental --format json
```

Match against skill names and inspect the selected catalog path before installing.

4. Search the public ecosystem:

```bash
npx skills find "<domain> <task>"
```

Always pass a specific query in non-interactive agent use. Consider install count, source repository, publisher, and whether the skill targets Codex.

5. Inspect the strongest candidates before recommending them. Use the skills.sh detail page and the underlying GitHub repository to verify the author, contents, install target, scripts, network access, and required credentials.

6. Present two to five useful options with the skill name, purpose, source, install command or catalog identifier, and a short fit assessment. Do not rank by search position alone.

7. Ask for approval before installing. After approval, use the matching path:

```bash
# OpenAI catalog skill
python3 "$INSTALLER/install-skill-from-github.py" \
  --repo openai/skills \
  --path skills/.curated/<skill-name>

# Other GitHub skill directory
python3 "$INSTALLER/install-skill-from-github.py" \
  --repo <owner>/<repo> \
  --path <path/to/skill>

# skills.sh result
npx skills add <owner/repo@skill> -g -a codex -y
```

For a skills.sh result whose GitHub path is known, the installer script is usually the more predictable way to place the skill in `$CODEX_HOME/skills`.

8. Verify the installed directory contains `SKILL.md`, inspect the frontmatter, and confirm that scripts or supporting files were installed. State that the skill becomes available on the next turn.

## Pitfalls

- Do not install the whole repository when the user asked for one skill.
- Do not use `-y` until the user has approved the exact package; it suppresses the CLI confirmation.
- A skills.sh result can target multiple agent products. Verify the Codex installation path instead of assuming the package was placed in `$CODEX_HOME/skills`.
- Do not treat install count or GitHub stars as proof of safety. Review scripts, network calls, credentials, and broad filesystem access.
- Do not recommend a duplicate when an installed skill already covers the request.
- If no suitable skill exists, say so, offer direct completion, and suggest creating a local skill if the workflow recurs.

## Verification

Finish when the user has an evidence-backed set of options, or when each approved skill is installed under `$CODEX_HOME/skills`, validated as a skill directory, and ready for the next turn.
