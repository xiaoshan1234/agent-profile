# Roles

Each directory defines one deployable Hermes role.

```text
roles/<role>/
|-- role.json       Canonical SOUL path and skill selection
|-- SOUL.md         Deployable role identity
|-- SKILLS.md       Generated skill index; do not edit manually
`-- references/     Optional non-skill role assets
```

`role.json` is the source of truth for deployment. The common skills in
`catalog/common.json` are merged into every role, followed by the role-specific
`skills` array.

Schema-v2 roles reference their SOUL directly:

```json
{
  "schema": 2,
  "soul": "SOUL.md"
}
```

After changing a role manifest or the skill catalog, regenerate indexes:

```bash
./scripts/rebuild_catalog.py
```

Deploy a role with:

```bash
./scripts/deploy-hermes.sh english-teacher
```

See the repository [README](../README.md) for deployment options.
