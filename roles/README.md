# Roles

Each directory defines one deployable Hermes role.

```text
roles/<role>/
|-- role.json       Canonical profile, skill, and SOUL selection
|-- PERSONA.md      Role identity
|-- USAGE.md        Usage guidance appended to the role SOUL by default
|-- SKILLS.md       Generated skill index; do not edit manually
`-- references/     Optional non-skill role assets
```

`role.json` is the source of truth for deployment. The common skills in
`catalog/common.json` are merged into every role, followed by the role-specific
`skills` array.

The default SOUL mode composes the files listed under `soul.files`. A role can
later switch to a single role-specific file by setting:

```json
{
  "soul": {
    "mode": "file",
    "file": "SOUL.md"
  }
}
```

After changing a role manifest or the skill catalog, regenerate indexes:

```bash
./scripts/rebuild-catalog.py
```

Deploy a role with:

```bash
./scripts/deploy-hermes.sh english-teacher
```

See the repository [README](../README.md) for deployment options.
