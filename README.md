# Hermes Agent Profile Repository

This repository deploys role-specific Hermes Agent profiles from a single skill
catalog. Deployment is idempotent: it creates a missing profile, skips an existing
profile, installs shared and role-specific skills, and selects the requested SOUL.

## Directory layout

```text
.
|-- catalog/
|   |-- common.json          Skills required by every role
|   `-- skills.json          Generated inventory of every installable skill
|-- roles/
|   `-- <role>/
|       |-- role.json        Canonical SOUL path and skill selection
|       |-- SOUL.md          Deployable role identity
|       |-- SKILLS.md        Generated human-readable index
|       `-- references/      Optional non-skill assets
|-- skills/
|   |-- shared/              Cross-role skills such as find-skills
|   |-- documents/           Document and office skills
|   |-- education/           Education and IELTS skills
|   |-- finance/             Finance and stock skills
|   |-- design/              Interface design skills
|   |-- media/               Media-processing skills
|   |-- productivity/        Workspace and automation skills
|   `-- lifestyle/           Personal lifestyle skills
|-- souls/
|   `-- *.md                 Named reusable SOUL options
|-- schemas/
|   |-- role.schema.json     Role v1/v2 manifest contract
|   `-- skills.schema.json   Skill catalog contract
|-- scripts/
|   |-- deploy-hermes.sh     One-command deployment entrypoint
|   |-- deploy_hermes.py     Profile, skill, and SOUL deployment
|   |-- import_skill.py      Register local, GitHub, or Hermes registry skills
|   |-- rebuild_catalog.py   Generate the catalog and role indexes
|   |-- validate_repo.py     Validate manifests, sources, and generated files
|   `-- repo_lib.py          Shared implementation helpers
`-- tests/
    |-- test_hermes_deploy.py
    |-- test_import_skill.py
    `-- test_skill_converter.py
```

The role decision flow is:

```text
role.json + catalog/common.json
        -> selected skill ids
        -> catalog/skills.json
        -> domain skill copy or Hermes registry install
```

## Deploy a role

```bash
./scripts/deploy-hermes.sh english-teacher
```

This creates the profile only when it does not exist. Each role deploys its
single `SOUL.md` plus the selected shared and domain skills.

Useful options:

```bash
# Deploy only SOUL or only skills
./scripts/deploy-hermes.sh doc-assistant --parts soul
./scripts/deploy-hermes.sh doc-assistant --parts skills

# Deploy skills into an existing profile; fail if it does not exist
./scripts/deploy-hermes.sh doc-assistant \
  --profile existing-profile \
  --parts skills \
  --existing-only

# Deploy into a differently named profile
./scripts/deploy-hermes.sh doc-assistant --profile docs

# Override the role SOUL with a named SOUL or file
./scripts/deploy-hermes.sh stock-manager --parts soul --soul base-hermes
./scripts/deploy-hermes.sh fitness-coach --parts soul --soul ./my-soul.md

# Replace changed skill copies; the previous copies are backed up in the profile
./scripts/deploy-hermes.sh english-teacher --update-skills

# Inspect the complete plan without writing anything
./scripts/deploy-hermes.sh stock-manager --dry-run
```

`HERMES_HOME` selects a custom Hermes root. `HERMES_BIN` selects the Hermes
executable. Existing profiles are never recreated; skills that already exist
with different content are preserved unless `--update-skills` is explicit.

## Add skills

Self-authored skill:

```bash
./scripts/import_skill.py \
  --id education/my-skill \
  --from-dir ./path/to/my-skill \
  --role english-teacher
```

Network-collected GitHub skill, snapshotted under `skills/<domain>/` with Git provenance:

```bash
./scripts/import_skill.py \
  --id documents/example-skill \
  --git owner/repo \
  --git-path path/to/example-skill \
  --ref main \
  --role doc-assistant
```

Skill pinned directly to a Hermes registry identifier:

```bash
./scripts/import_skill.py \
  --id shared/registry-skill \
  --hermes-identifier official/category/registry-skill \
  --common
```

Use `--common` for skills needed by every role. Use `--role <name>` for a
single role. Then regenerate generated indexes:

```bash
./scripts/rebuild_catalog.py
./scripts/validate_repo.py --check-generated
```

## Convert an external skill

The shared converter normalizes Codex, OpenClaw, Claude, or generic skill
frontmatter into Hermes format and writes a manual-review report:

```bash
python3 skills/shared/skill-converter/scripts/convert_skill.py \
  --source /path/to/source-skill \
  --domain documents \
  --name converted-skill \
  --author "Original Author, Hermes Agent" \
  --license MIT
```

Run with `--dry-run` first. The converter preserves the body while reporting
tool names, OpenClaw metadata, platform assumptions, and Codex-only files that
need review.

## SOUL selection

Each `role.json` can define:

```json
{
  "schema": 2,
  "name": "doc-assistant",
  "soul": "SOUL.md",
  "skills": ["documents/docx", "documents/pdf"]
}
```

CLI `--parts` decides which side is deployed. `--soul` overrides the role's
SOUL selection, `--soul none` leaves SOUL untouched, and any other value is
resolved as a direct file path, `souls/<name>`, or `souls/<name>.md`.

## Verification

```bash
./scripts/validate_repo.py --check-generated
python3 -m unittest discover -s tests -v
```
