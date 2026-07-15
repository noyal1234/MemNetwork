"""Tests for BrainConfig validation."""

import json
from pathlib import Path

import pytest

from brainkm.models.brain_config import BrainConfig, RecallConfig


def test_brain_config_defaults() -> None:
    cfg = BrainConfig()
    assert cfg.version == 1
    assert cfg.project_roots == ["."]
    assert cfg.budget.total_tokens == 1500
    assert cfg.budget.dynamic_reallocation is True
    assert cfg.budget.session_start.pinned_rules == 300
    assert cfg.capture.distill_mode == "cursor"
    assert cfg.recall.abstain_mode == "percentile"
    assert cfg.recall.abstain_percentile == 0.10
    assert cfg.recall.min_recall_score is None
    assert cfg.handover.precompact_distill_timeout_seconds == 30
    assert cfg.injection.max_recalls_per_turn == 3
    assert cfg.graph.max_bfs_fanout_per_hop == 50
    assert cfg.graphify.code_only is True
    assert cfg.graphify.graph_json == "graphify-out/graph.json"
    assert cfg.graphify.sync_on_install is True
    assert cfg.graphify.auto_sync.enabled is True
    assert cfg.graphify.auto_sync.debounce_seconds == 60.0
    assert cfg.graphify.auto_sync.watch_filesystem is False
    assert cfg.semantic_enabled() is False
    assert cfg.semantic_config().enabled is False
    assert cfg.compression.summary_first is True
    assert cfg.recall.activation == "ppr"
    assert cfg.ollama.auto_select_model is False
    assert cfg.ollama.model == "qwen2.5:3b"
    assert cfg.groq.model == "llama-3.3-70b-versatile"
    assert cfg.groq.base_url == "https://api.groq.com/openai/v1"


def test_brain_config_auto_select_model() -> None:
    cfg = BrainConfig(ollama={"auto_select_model": True})
    assert cfg.ollama.auto_select_model is True


def test_brain_config_from_example_json() -> None:
    example_path = Path(__file__).resolve().parents[1] / "brainkm" / "config.example.json"
    data = json.loads(example_path.read_text(encoding="utf-8"))
    cfg = BrainConfig.model_validate(data)
    assert cfg.budget.total_tokens == 1500
    assert cfg.capture.plan_files is True
    assert cfg.capture.distill_mode == "cursor"
    assert cfg.recall.abstain_mode == "percentile"
    assert cfg.project_roots == ["."]
    assert cfg.ollama.model == "qwen2.5:3b"
    assert cfg.groq.model == "llama-3.3-70b-versatile"


def test_brain_config_accepts_ollama_distill_mode() -> None:
    cfg = BrainConfig(capture={"distill_mode": "ollama"})
    assert cfg.capture.distill_mode == "ollama"


def test_brain_config_accepts_groq_distill_mode() -> None:
    cfg = BrainConfig(capture={"distill_mode": "groq"})
    assert cfg.capture.distill_mode == "groq"


def test_brain_config_rejects_invalid_distill_mode() -> None:
    with pytest.raises(ValueError):
        BrainConfig(capture={"distill_mode": "openai"})

def test_brain_config_rejects_empty_project_roots() -> None:
    with pytest.raises(ValueError):
        BrainConfig(project_roots=[])


def test_brain_config_monorepo_project_roots() -> None:
    cfg = BrainConfig(project_roots=[".", "packages/api", "packages/web"])
    assert len(cfg.project_roots) == 3


def test_absolute_abstention_requires_min_recall_score() -> None:
    with pytest.raises(ValueError):
        RecallConfig(abstain_mode="absolute")


def test_absolute_abstention_accepts_threshold() -> None:
    recall = RecallConfig(abstain_mode="absolute", min_recall_score=1.5)
    assert recall.min_recall_score == 1.5
