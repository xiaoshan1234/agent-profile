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
|       |-- role.json        Canonical role and skill selection
|       |-- PERSONA.md       Role identity
|       |-- USAGE.md         Usage guidance
|       |-- SKILLS.md        Generated human-readable index
|       `-- references/      Optional non-skill assets
|-- skills/
|   |-- local/               Self-authored skills
|   `-- vendor/              Pinned or snapshotted network skills
|-- souls/
|   `-- *.md                 Named reusable SOUL options
|-- scripts/
|   |-- deploy-hermes.sh     One-command deployment entrypoint
|   |-- deploy_hermes.py     Profile, skill, and SOUL deployment
|   |-- import_skill.py      Register local, GitHub, or Hermes registry skills
|   |-- rebuild_catalog.py   Generate the catalog and role indexes
|   |-- validate_repo.py     Validate manifests, sources, and generated files
|   `-- repo_lib.py          Shared implementation helpers
`-- tests/
    |-- test_hermes_deploy.py
    `-- test_import_skill.py
```

The role decision flow is:

```text
role.json + catalog/common.json
        -> selected skill ids
        -> catalog/skills.json
        -> local/vendor copy or Hermes registry install
```

## Deploy a role

```bash
./scripts/deploy-hermes.sh english-teacher
```

This creates the `english-teacher` profile only when it does not exist. The
default SOUL is composed from the role's `PERSONA.md` and `USAGE.md`.

Useful options:

```bash
# Deploy into a differently named profile
./scripts/deploy-hermes.sh doc-assistant --profile docs

# Do not modify SOUL.md
./scripts/deploy-hermes.sh doc-assistant --soul none

# Use a named SOUL from souls/
./scripts/deploy-hermes.sh stock-manager --soul base-hermes

# Use an arbitrary SOUL file
./scripts/deploy-hermes.sh fitness-coach --soul ./my-soul.md

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
  --id my-skill \
  --from-dir ./path/to/my-skill \
  --role english-teacher
```

Network-collected GitHub skill, snapshotted under `skills/vendor/`:

```bash
./scripts/import_skill.py \
  --id example-skill \
  --git owner/repo \
  --git-path path/to/example-skill \
  --ref main \
  --role doc-assistant
```

Skill pinned directly to a Hermes registry identifier:

```bash
./scripts/import_skill.py \
  --id registry-skill \
  --hermes-identifier official/category/registry-skill \
  --common
```

Use `--common` for skills needed by every role. Use `--role <name>` for a
single role. Then regenerate generated indexes:

```bash
./scripts/rebuild_catalog.py
./scripts/validate_repo.py --check-generated
```

## SOUL selection

Each `role.json` can define:

```json
{
  "soul": {
    "mode": "compose",
    "files": ["PERSONA.md", "USAGE.md"]
  }
}
```

Alternative modes:

```json
{"soul": {"mode": "file", "file": "SOUL.md"}}
{"soul": {"mode": "none"}}
```

CLI `--soul` overrides the role setting. `--soul role` uses the role
configuration, `--soul none` leaves SOUL untouched, and any other value is
resolved as a direct file path, `souls/<name>`, or `souls/<name>.md`.

## Verification

```bash
./scripts/validate_repo.py --check-generated
python3 -m unittest discover -s tests -v
```
