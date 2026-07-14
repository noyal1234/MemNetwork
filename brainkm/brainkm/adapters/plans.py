"""Ingest `.cursor/plans/*.plan.md` — chunk by ## heading, distill per section."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from brainkm.adapters.distill import distill_rounds_with_timeout, get_distill_adapter
from brainkm.models.brain_config import BrainConfig
from brainkm.models.distill import DistilledNeuron, TranscriptMessage, TranscriptRound


@dataclass(frozen=True)
class PlanSection:
    heading: str
    body: str
    source_path: Path


_HEADING = re.compile(r"^##\s+(.+)$", re.MULTILINE)


def chunk_plan_file(path: Path) -> list[PlanSection]:
    text = path.read_text(encoding="utf-8")
    matches = list(_HEADING.finditer(text))
    if not matches:
        return [PlanSection(heading=path.stem, body=text.strip(), source_path=path)]

    sections: list[PlanSection] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            sections.append(
                PlanSection(
                    heading=match.group(1).strip(),
                    body=body,
                    source_path=path,
                )
            )
    return sections


def plan_rounds(sections: list[PlanSection]) -> list[TranscriptRound]:
    rounds: list[TranscriptRound] = []
    for index, section in enumerate(sections):
        rounds.append(
            TranscriptRound(
                round_index=index,
                messages=(
                    TranscriptMessage(
                        role="user",
                        text=f"# {section.heading}\n\n{section.body}",
                        line_no=0,
                    ),
                ),
            )
        )
    return rounds


def distill_plan_file(
    path: Path,
    *,
    config: BrainConfig,
    conn: sqlite3.Connection | None = None,
) -> list[DistilledNeuron]:
    sections = chunk_plan_file(path)
    adapter = get_distill_adapter(
        config,
        conn=conn,
        project_dir=path.parent,
        session_id=None,
    )
    rounds = plan_rounds(sections)
    round_chunk_ids = {round_.round_index: [f"plan:{path.name}:{round_.round_index}"] for round_ in rounds}
    distilled, _mode = distill_rounds_with_timeout(
        adapter,
        rounds,
        round_chunk_ids=round_chunk_ids,
        max_total=config.capture.max_neurons_per_plan,
        timeout_seconds=None,
        config=config,
    )
    return distilled


def discover_plan_files(project_dir: Path, glob_pattern: str) -> list[Path]:
    return sorted(project_dir.glob(glob_pattern))
