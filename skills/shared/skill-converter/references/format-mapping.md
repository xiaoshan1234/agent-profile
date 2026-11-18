# Skill Format Mapping

## Core structure

All supported formats use a directory containing `SKILL.md` plus optional
resources. Hermes requires `name` and `description`; repository conventions also
set `version`, `author`, `license`, `platforms`, and `metadata.hermes`.

## Product-specific metadata

| Source | Metadata | Conversion decision |
|---|---|---|
| Codex | `agents/openai.yaml` | Do not copy; report UI fields that may need recreation |
| OpenClaw | `metadata.openclaw` | Report dependency and invocation constraints for manual mapping |
| Claude | `.claude-plugin`, `agents/` | Copy only runtime resources needed by the skill |
| Generic | None | Normalize frontmatter and preserve the body |

## Tool names

Hermes equivalents commonly are:

| Source convention | Hermes convention |
|---|---|
| `Bash` | `terminal` |
| `Read` | `read_file` |
| `Write` | `write_file` |
| `Edit` | `patch` |
| `Glob` / `Grep` | `search_files` |

Do not rewrite these blindly. The same word can appear in prose, examples, or a
script where replacement would be incorrect.
