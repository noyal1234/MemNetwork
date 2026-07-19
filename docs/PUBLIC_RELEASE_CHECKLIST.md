# Public release checklist

Use this before flipping the repository public or claiming a PyPI name.

## Already done (Phase A)

- [x] Apache-2.0 [LICENSE](../LICENSE) + [NOTICE](../NOTICE)
- [x] `brainkm/pyproject.toml` license `Apache-2.0`, author Noyal Bastin Benny
- [x] [CLA.md](../CLA.md) + [CONTRIBUTING.md](../CONTRIBUTING.md)
- [x] Docs note deferred public/`uvx` install
- [x] `.github/workflows/publish.yml` (Trusted Publishing template; does not publish until configured + tagged)

## Blocked until decided

- [ ] **Final installable name** (PyPI + CLI). Keep `brainkm` in code until then. Do **not** claim PyPI under a temporary name.
- [ ] Rename package/CLI/MCP identifiers to that name (Phase A2)
- [ ] Wire publish workflow / docs one-liner to the final name

## Secret scrub (before visibility flip)

- [ ] No API keys, tokens, or `.env` files in git history or working tree
- [ ] No private absolute paths or machine-specific secrets in docs/fixtures
- [ ] Review recent commits and release artifacts for credentials
- [ ] Confirm `.brain/` and local DBs remain gitignored
- [ ] Rotate any credentials that were ever committed

## Phase B (only when name stable + explicitly greenlit)

- [ ] Claim final PyPI project name (not a placeholder)
- [ ] Configure PyPI Trusted Publisher → this GitHub repo + `publish.yml`
- [ ] Flip GitHub repository to **public**
- [ ] Tag a release (`vX.Y.Z`) and confirm wheel/sdist upload
- [ ] Update README / INSTALL one-liner to `uvx <pkg> install` / `pip install "<pkg>[tui]"`
- [ ] Set Implementation status **Public distribution** → Done in [AI_PROJECT_BRIEF.md](AI_PROJECT_BRIEF.md)
- [ ] Optional: MCP Registry listing, Cursor deeplink
