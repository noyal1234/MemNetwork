# Installable rename (Phase A2) — blocked

Do not run this until a final PyPI/CLI name is chosen. Until then the in-tree name stays `brainkm`.

## When renaming to `<pkg>`

Touch at least:

| Area | What to change |
|------|----------------|
| [brainkm/pyproject.toml](../brainkm/pyproject.toml) | `name`, `[project.scripts]` entry |
| Python package dir | `brainkm/brainkm/` → import path (or keep import + ship CLI alias) |
| MCP server name | client configs / install adapters |
| Hooks / rules / skills | templates under `brainkm/brainkm/hooks/` |
| Docs / AGENTS / README | install commands, status tables |
| Tests | any hard-coded `brainkm` CLI or package asserts |
| [.github/workflows/publish.yml](../.github/workflows/publish.yml) | PyPI environment URL comment |

Do **not** claim the old or temporary name on PyPI “just in case” unless you intentionally want a redirect stub later.

After rename: proceed with [PUBLIC_RELEASE_CHECKLIST.md](PUBLIC_RELEASE_CHECKLIST.md) Phase B only when greenlit.
