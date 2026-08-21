"""Playback of a recorded run, for the demo take.

The demo plays back a trace the agent actually produced. Nothing is narrated
that is not in the audit trail — if a line appears on screen during the
recording, it is in the trace, and the trace is what a judge can check.

That constraint is the whole design. A demo script that prints a nicely
worded story alongside the real run would be a story, and the first question
from anyone who works in the domain would be which half they were watching.

Pacing is cosmetic and applied at playback. The run itself is deterministic:
scripted tool failures, a fixed clock, and a model seam that answers from a
script, so the same take can be recorded twice and match frame for frame.
"""

from dataclasses import dataclass
from typing import Any

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
RED = "\033[31m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
CYAN = "\033[36m"

# Step types that are scaffolding rather than story. Shown only in full mode —
# a recording that narrates every state change loses the thread.
QUIET_TYPES = frozenset({"state_change", "model_call"})


@dataclass(frozen=True, slots=True)
class Beat:
    """One line of the recording, with the trace step it came from."""

    at_s: float
    label: str
    text: str
    colour: str = ""
    detail: tuple[str, ...] = ()

    def render(self, colour_enabled: bool = True) -> str:
        colour = self.colour if colour_enabled else ""
        reset = RESET if colour_enabled and colour else ""
        dim = DIM if colour_enabled else ""
        undim = RESET if colour_enabled else ""
        head = f"  {dim}T+{self.at_s:05.1f}s{undim}  {colour}{self.label:<11}{reset} {self.text}"
        lines = [head]
        lines.extend(f"               {dim}{line}{undim}" for line in self.detail)
        return "\n".join(lines)


def _wrap(text: str, width: int = 62) -> tuple[str, ...]:
    words, lines, current = text.split(), [], ""
    for word in words:
        if len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return tuple(lines)


def _label_and_colour(step: Any) -> tuple[str, str]:
    kind = step.type
    payload = step.payload
    if kind == "observation":
        return "OBSERVE", ""
    if kind == "tool_call":
        status = payload.get("status", "")
        if status in ("timeout", "error"):
            return "TOOL FAIL", RED
        return "TOOL", ""
    if kind == "error":
        return "RECOVER", YELLOW
    if kind == "confidence":
        return "CONFIDENCE", CYAN
    if kind == "decision":
        return "DECIDE", BOLD
    if kind == "lock":
        held = payload.get("status") == "held"
        return ("LOCK" if held else "LOCK LOST"), ("" if held else YELLOW)
    if kind == "gate":
        if payload.get("escalated"):
            return "ESCALATE", YELLOW
        return "GATE", ""
    if kind == "external_gate":
        return "CUSTOMER", CYAN
    return kind.upper()[:11], ""


def _text_for(step: Any) -> tuple[str, tuple[str, ...]]:
    """What this step says, and any indented supporting lines."""
    kind, payload = step.type, step.payload

    if kind == "observation":
        return str(payload.get("summary", "")), ()
    if kind == "tool_call":
        status = payload.get("status")
        note = f"{payload.get('tool')} — {status}"
        if payload.get("latency_ms"):
            note += f" ({payload['latency_ms']:,}ms)"
        return note, ()
    if kind == "error":
        return (
            f"{payload.get('tool')} {payload.get('error_class')}, "
            f"{payload.get('retries')} retry",
            (f"recovery: {payload.get('recovery')}",),
        )
    if kind == "confidence":
        return (
            f"computed {payload.get('computed')} — not self-reported",
            _wrap(str(payload.get("derivation", ""))),
        )
    if kind == "decision":
        chosen = "chosen" if payload.get("chosen") else "advisory only"
        head = f"{payload.get('rung')} ({chosen}), confidence {payload.get('confidence')}"
        return head, _wrap(str(payload.get("rationale", "")))
    if kind == "lock":
        head = (
            f"{payload.get('resource')} — {payload.get('status')} "
            f"(ours {payload.get('our_priority')}"
        )
        if payload.get("winner_priority") is not None:
            head += f", winner {payload.get('winner_priority')}"
        return head + ")", (str(payload.get("action", "")),) if payload.get("action") else ()
    if kind == "gate":
        head = f"{payload.get('required_role')} — {payload.get('status')}"
        reason = payload.get("escalation_reason")
        return head, (f"because {reason}",) if reason else ()
    if kind == "external_gate":
        return (
            f"{payload.get('options_sent')} options to the line, "
            f"{payload.get('window_min')}m window",
            (f"outcome: {payload.get('outcome')}",),
        )
    if kind == "state_change":
        return f"{payload.get('from_state')} -> {payload.get('to_state')}", ()
    if kind == "model_call":
        return (
            f"{payload.get('model')} ({payload.get('purpose')}) "
            f"${payload.get('usd', 0):.4f}",
            (),
        )
    return kind, ()


def beats_from_trace(trace: Any, seconds_per_step: float = 5.0, full: bool = False) -> list[Beat]:
    """Turn a completed trace into a timed script.

    Timings are cosmetic spacing for a recording, not measured latencies —
    calling them latencies on screen would be a small lie in a demo whose
    entire argument is that it does not tell them.
    """
    beats: list[Beat] = []
    clock = 0.0
    for step in trace.steps:
        if not full and step.type in QUIET_TYPES:
            continue
        label, colour = _label_and_colour(step)
        text, detail = _text_for(step)
        if not text:
            continue
        beats.append(Beat(clock, label, text, colour, detail))
        clock += seconds_per_step
    return beats


def outcome_panel(trace: Any, width: int = 76) -> str:
    """The closing frame: what happened, and what it cost."""
    payload = trace.as_dict()["outcome"]
    cost = trace.as_dict()["cost"]
    served = payload.get("service_success")
    verdict = (
        f"{GREEN}SERVICE{RESET}" if served else f"{RED}SERVICE FAILURE{RESET}"
    )
    lines = [
        "─" * width,
        f"  outcome     {payload['resolution']}   {verdict}",
        f"  boxes       {payload['boxes']}",
    ]
    if payload.get("decision_lead_time_h") is not None:
        lines.append(
            f"  lead time   {payload['decision_lead_time_h']}h from detection "
            f"to options reaching the line"
        )
    lines.append(
        f"  cost        ${cost['usd']:.4f} across {cost['model_calls']} model call(s)"
    )
    lines.append("─" * width)
    return "\n".join(lines)
