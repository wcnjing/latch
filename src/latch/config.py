"""Tunables, model selection, and pricing.

Every threshold the agent's behaviour depends on lives here rather than
inline, so the submission can state them and the evaluation can freeze them.
"""

import os
from typing import Final

# --- Models -----------------------------------------------------------------
# Declared in the submission per the competition's third-party AI requirement.

TRIAGE_MODEL: Final = "claude-haiku-4-5"
DELIBERATION_MODEL: Final = "claude-opus-5"

# USD per million tokens, first-party Anthropic API rates.
PRICING: Final[dict[str, tuple[float, float]]] = {
    # model: (input $/MTok, output $/MTok)
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-opus-5": (5.00, 25.00),
    # Not a model: a deterministic policy that always takes the top candidate.
    # Named distinctly so a trace never claims a model call that did not happen.
    "policy-baseline": (0.00, 0.00),
    # Local inference: zero marginal cost, not zero cost. See LOCAL_MODEL below.
    "qwen3:8b": (0.00, 0.00),
    "qwen3:4b": (0.00, 0.00),
    "qwen3:1.7b": (0.00, 0.00),
    "qwen2.5:7b-instruct": (0.00, 0.00),
}

# Deliberation walks a ladder and orchestrates tools; it is the one place we
# want real reasoning. Triage only has to answer "is this worth waking the
# expensive model for", so it runs without thinking.
DELIBERATION_EFFORT: Final = "medium"
TRIAGE_MAX_TOKENS: Final = 512
DELIBERATION_MAX_TOKENS: Final = 3_000


# --- Watcher ----------------------------------------------------------------

POLL_INTERVAL_SEC: Final = 300  # 5-minute cadence against OCEANS-X

# A risk is raised on slack consumed, not on delay magnitude. Six hours late
# with thirty hours of slack is not an event; ninety minutes late with two
# hours of slack is.
SLACK_CONSUMED_TRIGGER: Final = 0.60


# --- Gate Controller --------------------------------------------------------
# The agent proposes; policy disposes. The model never decides its own
# permissions, so these are plain constants and not prompt text.

CONFIDENCE_ESCALATION_THRESHOLD: Final = 0.70
AUTO_APPROVE_MAX_BOXES: Final = 40

# The cost gate exists to catch a move that is expensive *for its size* —
# premium haulage, an awkward routing — not to re-detect volume. At SGD 2,000
# it fired at roughly 42 road boxes, which the 40-box volume gate already
# catches, so the two criteria were one signal wearing two hats and every
# large move escalated two steps instead of one. SGD 8,000 is about 166 road
# boxes: genuinely unusual, and independent of the volume check.
AUTO_APPROVE_MAX_COST_SGD: Final = 8_000.0


# --- Lock Table -------------------------------------------------------------

LOCK_TTL_SEC: Final = 180  # a claim nobody commits is released, not leaked


# --- Rung 4 -----------------------------------------------------------------

CUSTOMER_WINDOW_MIN: Final = 180  # what we commit to when options are sent


# --- Confidence engine ------------------------------------------------------
# Weights are frozen before evaluation and reported in the submission. They
# are here, not in the model's context, because a system that lets the agent
# set its own confidence cannot also claim the agent cannot self-certify.

CONFIDENCE_SOURCE_FACTOR: Final[dict[str, float]] = {
    "live_api": 1.00,
    "cache": 0.85,
    "assumed_default": 0.60,
}
CONFIDENCE_TOOL_FACTOR: Final[dict[str, float]] = {
    "ok": 1.00,
    "retried": 0.90,
    "failed": 0.70,
}
CONFIDENCE_AGE_SCALE_MIN: Final = 120.0  # decay scale applied to stale inputs
CONFIDENCE_UNVERIFIED_PENALTY: Final = 0.05  # linear, per unverified input
CONFIDENCE_FLOOR: Final = 0.05


# --- model capabilities -----------------------------------------------------
# `effort` is rejected by models that predate it, so the deliberation call
# gates on this rather than sending it hopefully and catching a 400.

EFFORT_CAPABLE_MODELS: Final[frozenset[str]] = frozenset(
    {"claude-opus-5", "claude-opus-4-8", "claude-sonnet-5"}
)


# --- Triage -----------------------------------------------------------------
# The funnel is free at both ends. A SAFE event and an obviously-critical one
# are both decided deterministically; the small model is spent only on the
# ambiguous middle, which is where a judgement is actually being made.

TRIAGE_FAST_TRACK_BOXES: Final = 40  # large volume, already blown: skip the ask
TRIAGE_MIN_BOXES: Final = 5  # below this the move costs more than the miss


# --- local models -----------------------------------------------------------
# Run through Ollama (MIT) against an Apache-2.0 model, so nothing here is
# copyleft and everything is declarable under the competition T&Cs.
#
# Priced at zero because the *marginal* cost of a local call is zero. That is
# not the same as free — it costs the laptop's time and power — so the trace
# labels these calls rather than letting a $0.00 total imply no cost at all.

# Overridable so the model can be swapped without a code change — useful when
# download time, not capability, is the binding constraint.
LOCAL_MODEL: Final = os.environ.get("LATCH_LOCAL_MODEL", "qwen3:8b")
LOCAL_MODEL_LICENCE: Final = "Apache-2.0"
OLLAMA_HOST: Final = "http://127.0.0.1:11434"
LOCAL_TIMEOUT_SEC: Final = 180.0
