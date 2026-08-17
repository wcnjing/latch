"""Tunables, model selection, and pricing.

Every threshold the agent's behaviour depends on lives here rather than
inline, so the submission can state them and the evaluation can freeze them.
"""

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
}

# Deliberation walks a ladder and orchestrates tools; it is the one place we
# want real reasoning. Triage only has to answer "is this worth waking the
# expensive model for", so it runs without thinking.
DELIBERATION_EFFORT: Final = "high"
TRIAGE_MAX_TOKENS: Final = 512
DELIBERATION_MAX_TOKENS: Final = 16_000


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
AUTO_APPROVE_MAX_COST_SGD: Final = 2_000.0


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
