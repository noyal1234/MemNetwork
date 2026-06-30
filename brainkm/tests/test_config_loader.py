"""Tests for BrainConfig loading from disk."""

import json

from brainkm.models.brain_config import BrainConfig
from brainkm.services.config_loader import load_brain_config


def test_load_brain_config_defaults_when_missing(tmp_path) -> None:
    cfg = load_brain_config(tmp_path)
    assert isinstance(cfg, BrainConfig)
    assert cfg.project_roots == ["."]


def test_load_brain_config_from_file(tmp_path) -> None:
    brain = tmp_path / ".brain"
    brain.mkdir()
    data = {
        "version": 1,
        "project_roots": [".", "apps/web"],
        "recall": {
            "abstain_mode": "absolute",
            "min_recall_score": 2.0,
        },
    }
    (brain / "config.json").write_text(json.dumps(data), encoding="utf-8")

    cfg = load_brain_config(tmp_path)
    assert cfg.project_roots == [".", "apps/web"]
    assert cfg.recall.abstain_mode == "absolute"
    assert cfg.recall.min_recall_score == 2.0
