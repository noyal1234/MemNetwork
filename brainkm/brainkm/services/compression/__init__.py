"""brainkm compression stack — content-class pipeline, metrics, dual-store."""

from brainkm.services.compression.classify import classify_content
from brainkm.services.compression.cohort import assign_session_cohort, get_session_engine_version
from brainkm.services.compression.metrics import (
    HitBands,
    bump_window_seconds,
    context_rot_stats,
    hit_bands_from_gaps,
    mode_a_lifetime_cost,
    mode_a_write_cost,
    mode_s_expected_cost,
    warm_credit_tokens,
)
from brainkm.services.compression.pipeline import compress_text
from brainkm.services.compression.net_session import estimate_net_session, should_auto_disable_terse
from brainkm.services.compression.polarity import grade_egress, meets_answerability_bar
from brainkm.services.compression.types import ENGINE_VERSION, CompositionMode, PipelineResult

__all__ = [
    "ENGINE_VERSION",
    "CompositionMode",
    "HitBands",
    "PipelineResult",
    "assign_session_cohort",
    "bump_window_seconds",
    "classify_content",
    "compress_text",
    "context_rot_stats",
    "estimate_net_session",
    "get_session_engine_version",
    "grade_egress",
    "hit_bands_from_gaps",
    "meets_answerability_bar",
    "mode_a_lifetime_cost",
    "mode_a_write_cost",
    "mode_s_expected_cost",
    "should_auto_disable_terse",
    "warm_credit_tokens",
]
