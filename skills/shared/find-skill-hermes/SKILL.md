---
name: find-skill
description: Find and install skills from configured registries.
version: 0.1.0
author: Agent Profile Contributors, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [skills, discovery, installation, registries]
    related_skills: []
---

# Find Skill

Locate installable skills for the current Hermes Agent profile and help the user install a suitable result. This skill covers discovery and installation, not executing the discovered capability.

## When to Use

- The user asks for a skill for a domain or workflow.
- The user asks whether an installable skill can do a task.
- The user wants to extend Hermes Agent with reusable instructions or tooling.
- An existing capability may solve the request more reliably than a one-off implementation.

Do not use this skill for ordinary work that Hermes Agent can complete directly. In that case, continue with the normal task.

## Prerequisites

- The `terminal` tool is available.
- The `hermes` CLI is on `PATH`.
- Registry search and installation require network access.
- Commands target the active Hermes profile. To inspect another profile, place its flag before the subcommand, for example `hermes -p <profile> skills list`.

## How to Run

Check installed skills first:

```text
terminal(command="hermes skills list --enabled-only", timeout=60)
```

Search all configured registries:

```text
terminal(command="hermes skills search 'document extraction' --limit 10", timeout=90)
```

Use `--json` when exact identifiers or structured filtering matter:

```text
terminal(command="hermes skills search 'document extraction' --limit 10 --json", timeout=90)
```

Limit the source when the user asks for a specific ecosystem:

```text
terminal(command="hermes skills search 'stock research' --source official --limit 10", timeout=90)
terminal(command="hermes skills search 'browser automation' --source skills-sh --limit 10", timeout=90)
terminal(command="hermes skills search 'openclaw workflow' --source clawhub --limit 10", timeout=90)
```

Preview a result before recommending installation:

```text
terminal(command="hermes skills inspect '<identifier>'", timeout=90)
```

After the user explicitly approves a result, install it:

```text
terminal(command="hermes skills install '<identifier>' --yes", timeout=300)
```

## Procedure

1. Reduce the request to a domain, concrete task, and one or two discriminating keywords. Completion criterion: the query would distinguish this capability from adjacent skills.
2. Check the active profile's enabled skills. Completion criterion: either an installed match is identified or the gap is established.
3. Search the configured Hermes registries with the most specific query. Completion criterion: collect up to five plausible identifiers, sources, and descriptions.
4. If results are weak, retry with task synonyms or a narrower source such as `official`, `skills-sh`, or `clawhub`. Completion criterion: search coverage is sufficient to avoid claiming that no skill exists after one generic query.
5. Inspect the strongest candidates. Completion criterion: verify the identifier, publisher or source, prerequisites, safety signals, and whether it does what the user needs.
6. Present the best matches with their purpose, source, identifier, and a short fit assessment. Do not recommend solely because a result appeared in search.
7. Ask for approval before installing anything. Completion criterion: the user has authorized the exact skill or set of skills.
8. Install approved identifiers, then verify them with `hermes skills list --enabled-only` or `hermes skills inspect`. Completion criterion: the installed state is visible and matches the approved selection.

## Pitfalls

- Do not substitute `npx skills`, ClawHub-only commands, or a web search for Hermes' configured registries.
- `hermes skills search` takes one query string; quote multi-word queries in the shell command.
- The default `all` source combines official, skills.sh, GitHub taps, ClawHub, and other configured registries. Search output can be broader than an official-only catalog.
- Installation modifies the active profile. Confirm the target profile before a user-sensitive install.
- Search results describe candidates, not guarantees. Inspect before installation and do not bypass blocked scan verdicts merely to complete the request.
- If no suitable skill exists, say so and offer to complete the task directly or create a local skill.

## Verification

The task is complete when the user has a short evidence-backed recommendation, or when each explicitly approved skill is installed and visible in the active Hermes profile.
