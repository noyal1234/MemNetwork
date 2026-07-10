"""Capture plan files into decision/context neurons."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from brainkm.adapters.plans import discover_plan_files, distill_plan_file
from brainkm.logging_config import get_logger
from brainkm.models.brain_config import BrainConfig
from brainkm.services.memory import create_neuron, new_ulid
from brainkm.services.quality import passes_quality_gate

logger = get_logger("services.plan_capture")


def capture_plan_files(
    conn: sqlite3.Connection,
    *,
    project_dir: Path,
    config: BrainConfig,
) -> int:
    if not config.capture.plan_files:
        return 0

    paths = discover_plan_files(project_dir, config.capture.plan_glob)
    neuron_count = 0
    for path in paths:
        distilled = distill_plan_file(path, config=config, conn=conn)
        for item in distilled:
            if not passes_quality_gate(item):
                continue
            create_neuron(
                conn,
                title=item.title,
                content=item.body,
                kind="memory",
                subtype=(
                    item.subtype
                    if item.subtype in {"decision", "context", "fact"}
                    else "decision"
                ),
                tags=item.tags + [f"plan:{path.name}"],
                source=f"plan:{path.name}",
                node_id=new_ulid(),
            )
            neuron_count += 1
            if neuron_count >= config.capture.max_neurons_per_plan * max(len(paths), 1):
                break
    return neuron_count
