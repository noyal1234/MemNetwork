# Contributing to MemNetwork (brainkm)

Thanks for helping improve the local project brain for agent IDEs.

## License and CLA (required)

- The project is licensed under the **Apache License 2.0** — see [LICENSE](LICENSE)
  and [NOTICE](NOTICE). Copyright: **Noyal Bastin Benny**.
- Licensing may evolve (for example to a source-available license such as
  PolyForm Noncommercial, or dual-licensing). Do **not** assume the license is
  frozen forever.
- **Before we merge your first PR**, you must agree to the
  [Contributor License Agreement](CLA.md). Include in the PR description:

  ```text
  I have read and agree to the CLA in CLA.md.
  ```

  The CLA lets you keep copyright while granting the project rights to
  redistribute and, if needed, relicense your Contribution as part of the
  project.

## Development setup

```bash
bash brainkm/scripts/setup_dev.sh
source .venv/bin/activate
pip install -e "./brainkm[dev,tui]"
pytest
brainkm version
```

Python **3.11** or **3.12** recommended. Prefer `brainkm configure` for local
host wiring. See [docs/INSTALL.md](docs/INSTALL.md) and [AGENTS.md](AGENTS.md).

## Pull requests

1. Keep changes focused; match existing style and layering
   (MCP tool → service → adapter → SQLite).
2. Add or update tests under `brainkm/tests/` when behavior changes.
3. Do not commit secrets, `.brain/` databases, or personal API keys.
4. Update docs when you change user-facing CLI, MCP tools, or install steps.
5. Agree to the CLA (above) on your first contribution.

## Architecture notes

- Config: `get_settings()` for env; `BrainConfig` for `.brain/config.json`.
- Agent-facing packs: hard ~1500-token cap.
- Capture: hooks + `capture.auto_observe`; MCP `remember` is pin/correct only.

More detail: [docs/AI_PROJECT_BRIEF.md](docs/AI_PROJECT_BRIEF.md).

## Public distribution

PyPI / `uvx` one-liner install is **deferred** until the installable package
name is finalized and the repository is made public. Local editable install
remains the supported path for contributors.
