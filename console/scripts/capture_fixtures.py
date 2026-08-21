"""Capture console fixtures by running B's real pipeline.

Workstream C. This script imports A and B read-only and modifies nothing in
`src/latch`. It exists because hand-written JSON drifts from the code it claims
to represent — `fixtures/traces.json` already has (see CONTRACTS.md section 10),
and the console must not inherit that.

Every fixture here is the output of `runner.handle()` on a real `RiskEvent`,
with deterministic failure injection from B's own `ScriptedFailures` and a
cache entry built from B's own `build_itt_inventory`. The confidence numbers,
the gate escalations and the excluded options are all computed by B's code. If
`gates.py` or `confidence.py` changes and this script still runs, the fixtures
are still true.

    uv run python console/scripts/capture_fixtures.py
    PYTHONPATH=src python console/scripts/capture_fixtures.py

Two honest caveats, both recorded in each fixture's `provenance` block and both
surfaced in the UI rather than buried here:

  1. No model is consulted. `ScriptedDeliberator` below stands in for the model
     seam, exactly as B's own `FakeModel` does, using B's token-count formula.
     The traces therefore measure the pipeline, not the agent.

  2. Trace step timestamps are wall-clock at record time (`trace.py::_now`), so
     they change on every regeneration and are NOT scenario time. Nothing reads
     them for ordering; `seq` is the order and `latency_ms` is the duration.
     See CONTRACTS.md section 12.3.

Two fixtures are marked `authored: true` — SUPERSEDED and STALE. Neither state
is reachable through `runner.handle()` (CONTRACTS.md sections 8 and 9), so
their state changes are written by C through B's real `transition()`, which
raises on an illegal move. The supersession fixture's `AdmissionDecision` is
genuine `CaseRegistry` output.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CONSOLE = HERE.parent
PROJECT = CONSOLE.parent

# Normally A and B sit beside the console at `../src`. LATCH_SRC points the
# capture at a different checkout of them, which is what makes it possible to
# re-capture against a newer B without moving the console first.
import os  # noqa: E402

sys.path.insert(0, os.environ.get("LATCH_SRC", str(PROJECT / "src")))

from latch.cases import CaseRegistry  # noqa: E402
from latch.connections import ConnectionParams  # noqa: E402
from latch.config import (  # noqa: E402
    CONFIDENCE_ESCALATION_THRESHOLD,
    DELIBERATION_MODEL,
    TRIAGE_MODEL,
)
from latch.console import case_view  # noqa: E402
from latch.events import Assumptions, ConnectionType, RiskEvent  # noqa: E402
from latch.gates import LADDERS  # noqa: E402
from latch.llm import ModelResponse  # noqa: E402
from latch.locks import LockTable  # noqa: E402
from latch.models import Resolution, Rung, Terminal  # noqa: E402
from latch.runner import (  # noqa: E402
    AutoApprove,
    CustomerDeclinesAll,
    CustomerSilent,
    NeverApproves,
    handle,
)
from latch.serde import risk_to_dict  # noqa: E402
from latch.state import RiskState, transition  # noqa: E402
from latch.tools import CacheEntry, ScriptedFailures, ToolStatus  # noqa: E402
from latch.tools.stubs import build_itt_inventory  # noqa: E402
from latch.trace import Trace, TraceStore  # noqa: E402

OUT = CONSOLE / "fixtures"

# A's frozen synthetic parameters, read (never set) so the assumption text on
# screen matches what the live Watcher would have written.
CONNECTION_PARAMS = ConnectionParams()

# Anchor for the synthetic connection windows. Only affects the scenario, never
# the trace step timestamps, which B stamps with wall clock.
T0 = datetime(2026, 8, 30, 4, 17, tzinfo=UTC)


# --- the model seam ---------------------------------------------------------


class ScriptedDeliberator:
    """Stands in for the model. Deterministic, and it never invents an option.

    B's design is that code enumerates and the model only ranks. That makes a
    scripted stand-in honest as long as it ranks by B's own stated policy
    rather than by whatever flatters the demo. The policy in
    `deliberation.DELIBERATION_SYSTEM` is:

        If any Rung 3 option resolves the connection, choose it. Rung 4 is for
        when nothing available resolves it internally.

    and, where Rung 3 options differ, say which tradeoff was made. That is what
    this implements: prefer Rung 3, break ties on emissions, and state the
    tradeoff. Candidate ids are parsed out of the prompt B built, so an id that
    was not enumerated cannot be returned.

    Token counts use B's `FakeModel` formula verbatim so cost accounting in the
    fixtures matches what B's own tooling produces.
    """

    CANDIDATE = re.compile(
        r"^\s{2}(?P<id>\S+)\s\[(?P<rung>\S+)\]\s(?P<detail>.*?)"
        r"\s\|\scost SGD (?P<cost>[\d,]+)\s\|\s(?P<co2>[\d,]+) kg CO2e\s*$"
    )

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def complete_json(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        schema: dict[str, Any],
        max_tokens: int,
        purpose: str,
    ) -> ModelResponse:
        self.calls.append((purpose, model))
        if purpose == "triage":
            data = self._triage(prompt)
        elif purpose.startswith("deliberation"):
            data = self._deliberate(prompt)
        else:
            raise KeyError(f"no scripted behaviour for purpose {purpose!r}")

        return ModelResponse(
            data=data,
            model=model,
            input_tokens=len(system) // 4 + len(prompt) // 4,
            output_tokens=len(json.dumps(data)) // 4,
        )

    @staticmethod
    def _triage(prompt: str) -> dict[str, Any]:
        """Keep anything the prefilter did not already decide.

        The prefilter (`triage.prefilter`) has already dismissed SAFE and
        under-volume events deterministically. What reaches the model is the
        ambiguous middle, and B's system prompt says a connection past its
        window always warrants deliberation.
        """
        slack = re.search(r"Slack under the current plan: (-?[\d.]+)h", prompt)
        hours = float(slack.group(1)) if slack else 0.0
        if hours <= 0:
            return {
                "worth_deliberating": True,
                "reason": (
                    "Already past the window; options exist and differ, so there "
                    "is a real decision to make."
                ),
            }
        return {
            "worth_deliberating": True,
            "reason": (
                f"{hours:.1f}h of margin left against a transfer on the critical "
                "path; close enough that the choice between options matters."
            ),
        }

    def _deliberate(self, prompt: str) -> dict[str, Any]:
        candidates = [
            m.groupdict() for line in prompt.splitlines() if (m := self.CANDIDATE.match(line))
        ]
        if not candidates:
            raise ValueError("deliberation prompt carried no parseable candidates")

        moves = [c for c in candidates if c["rung"] == Rung.MOVE.value]
        offers = [c for c in candidates if c["rung"] == Rung.OFFER.value]

        def co2(c: dict[str, str]) -> float:
            return float(c["co2"].replace(",", ""))

        def sgd(c: dict[str, str]) -> float:
            return float(c["cost"].replace(",", ""))

        if moves:
            ranked = sorted(moves, key=lambda c: (co2(c), sgd(c), c["id"])) + offers
            chosen = ranked[0]
            alternatives = [c for c in moves if c["id"] != chosen["id"]]
            if alternatives:
                cheapest = min(alternatives, key=sgd)
                if sgd(cheapest) < sgd(chosen):
                    rationale = (
                        f"Takes the lower-emissions leg at {co2(chosen):,.0f} kg CO2e "
                        f"against {co2(cheapest):,.0f}, accepting SGD "
                        f"{sgd(chosen) - sgd(cheapest):,.0f} more than the cheapest "
                        "option. The assumed transit still arrives before the "
                        "modelled cutoff, so the margin is not what is being traded."
                    )
                else:
                    rationale = (
                        f"Lowest on both emissions ({co2(chosen):,.0f} kg CO2e) and "
                        f"cost (SGD {sgd(chosen):,.0f}) among the legs that arrive "
                        "before the modelled cutoff; no tradeoff to make."
                    )
            else:
                rationale = (
                    "The only transfer leg whose assumed transit arrives before the "
                    "modelled cutoff. Resolves the connection inside PSA rather than "
                    "spending the line's attention on a decision we can make."
                )
        else:
            ranked = offers + moves
            chosen = ranked[0]
            rationale = (
                "No transfer leg arrives before the modelled cutoff, so nothing "
                "resolves this internally. Putting the remaining outbound services "
                "to the line while the choice is still real."
            )

        return {
            "chosen_plan_id": chosen["id"],
            "ranking": [c["id"] for c in ranked],
            "rationale": rationale,
        }


class RejectsApproval:
    """Says no. Implements B's `ApprovalPolicy` protocol.

    B ships `AutoApprove` (yes) and `NeverApproves` (silence) but nothing that
    actively declines, and `runner.handle()` has a distinct branch for it. The
    console's decline button has to lead somewhere real, so this captures it.
    """

    def decide(self, role: Any, plan: Any) -> bool | None:
        return False


# --- event construction -----------------------------------------------------


def event(
    connection_id: str,
    *,
    state: str,
    slack: float,
    no_itt: float,
    boxes: int,
    avoidable: bool = True,
    confidence: str = "MEDIUM",
    codes: tuple[str, ...] = ("INBOUND_ETA_SLIP", "INTER_TERMINAL_TRANSFER_TIME"),
    inbound_terminal: Terminal = Terminal.TUAS,
    outbound_terminal: Terminal = Terminal.PASIR_PANJANG,
    inbound_vessel: str = "SYNTHETIC MAERSK",
    outbound_vessel: str = "SYNTHETIC FEEDER",
    offset_min: float = 0.0,
) -> RiskEvent:
    """Build a RiskEvent through B's own decoder, so it cannot be malformed.

    `from_dict` raises on an unknown reason code and on a bad severity, which is
    what makes this safer than constructing the dataclass directly.

    It also cannot set `assumptions` — neither `to_dict` nor `from_dict` carries
    that block (CONTRACTS.md section 4a), so every event rebuilt from JSON claims
    `SAME_TERMINAL` no matter what its terminals say. The `replace` below
    reattaches the assumptions the live Watcher would have set
    (`watcher.py::to_risk_event`), so a fixture cannot contradict itself on
    screen. This is a workaround for a real gap, not a fix: B's own
    `latch --events` path still misreports it.
    """
    decoded = RiskEvent.from_dict(
        {
            "connection_id": connection_id,
            "state": state,
            "current_plan_slack_hours": slack,
            "no_itt_slack_hours": no_itt,
            "avoidable_by_terminal_prevention": avoidable,
            "affected_boxes": boxes,
            "confidence": confidence,
            "reason_codes": list(codes),
            "detected_at": (T0 + timedelta(minutes=offset_min)).isoformat(),
            "ucid": f"UCID-SYNTH-{connection_id}",
            "inbound_terminal": inbound_terminal.value,
            "outbound_terminal": outbound_terminal.value,
            "terminal_resolution": "simulated",
            "inbound_vessel": inbound_vessel,
            "outbound_vessel": outbound_vessel,
            "source": "ais_replay+synthetic_connection",
        }
    )
    return replace(
        decoded,
        assumptions=Assumptions(
            connection_type=(
                ConnectionType.INTER_TERMINAL
                if inbound_terminal is not outbound_terminal
                else ConnectionType.SAME_TERMINAL
            ),
            transfer_scenario=(
                "configured reference transfer scenario "
                f"({CONNECTION_PARAMS.planned_transfer_h:.1f}h assumed transfer)"
            ),
        ),
    )


# --- capture ----------------------------------------------------------------


def derived_block(evt: RiskEvent) -> dict[str, Any]:
    """B's own RiskEvent properties, serialised.

    These are computed by `events.py`, not by C. `itt_is_the_problem` in
    particular is the rescue flag the console must use — the raw
    `avoidable_by_terminal_prevention` is only a statement that a transfer is
    on the critical path. See CONTRACTS.md section 5.
    """
    return {
        "is_actionable": evt.is_actionable,
        "slack_deficit_hours": round(evt.slack_deficit_hours, 3),
        "itt_cost_hours": round(evt.itt_cost_hours, 3),
        "itt_is_the_problem": evt.itt_is_the_problem,
        "priority": round(evt.priority, 3),
        "watcher_confidence_factor": evt.confidence_factor,
    }


def gate_block(gate: Any) -> dict[str, Any] | None:
    """The Gate Controller's approval object, plus the counterfactual.

    `GateDecision` has no serialiser in B (CONTRACTS.md section 7), so this is
    C capturing what `handle()` returned. `would_have_been` is `LADDERS[rung][0]`
    read from `gates.py` — the role the gate requires when nothing trips — which
    is what makes "escalated from X to Y" renderable rather than asserted.
    """
    if gate is None:
        return None
    ladder = [role.value for role in LADDERS[gate.rung]]
    return {
        "rung": gate.rung.value,
        "required_role": gate.required_role.value,
        "escalated": gate.escalated,
        "escalation_reason": gate.escalation_reason,
        "auto_approved": gate.auto_approved,
        "blocks": gate.blocks,
        "needs_customer": gate.needs_customer,
        "ladder": ladder,
        "would_have_been": ladder[0],
        "confidence_threshold": CONFIDENCE_ESCALATION_THRESHOLD,
    }


def capture(
    fixture_id: str,
    title: str,
    what_it_shows: str,
    evt: RiskEvent,
    *,
    failures: dict[str, list[ToolStatus]] | None = None,
    itt_cache: CacheEntry | None = None,
    approvals: Any = None,
    customer: Any = None,
    locks: LockTable | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one event end to end and package everything the console needs."""
    client = ScriptedDeliberator()
    store = TraceStore()
    outcome = handle(
        evt,
        client=client,
        store=store,
        locks=locks or LockTable(),
        failures=ScriptedFailures(failures) if failures else None,
        itt_cache=itt_cache,
        approvals=approvals or AutoApprove(),
        customer=customer or CustomerSilent(),
        now=T0,
    )
    risk = evt.to_connection_risk()

    bundle: dict[str, Any] = {
        "fixture_id": fixture_id,
        "title": title,
        "what_it_shows": what_it_shows,
        "provenance": {
            "produced_by": "runner.handle()",
            "authored": False,
            "model_responses": "scripted",
            "model_disclosure": (
                "No model was consulted. Responses come from C's "
                "ScriptedDeliberator, which ranks by the policy in B's own "
                "deliberation system prompt. Token counts use B's FakeModel "
                "formula and are priced at config.PRICING. These traces measure "
                "the pipeline, not the agent."
            ),
            "data_basis": (
                "real vessel movement data + derived arrival estimates + "
                "synthetic transhipment connections"
            ),
            "timestamps": (
                "Trace step `at` values are wall clock at record time and change "
                "on every regeneration. Order by `seq`; duration is `latency_ms`."
            ),
            "tool_inventory": "synthetic (tools/stubs.py, frozen constants)",
        },
        "event": evt.to_dict()
        | {
            # Keys `to_dict()` drops but `from_dict()` reads. Written here so the
            # console has terminals and vessel names at all. CONTRACTS.md section 4.
            "inbound_terminal": evt.inbound_terminal.value,
            "outbound_terminal": evt.outbound_terminal.value,
            "terminal_resolution": evt.terminal_resolution.value,
            "inbound_vessel": evt.inbound_vessel,
            "outbound_vessel": evt.outbound_vessel,
            "source": evt.source,
        },
        "derived": derived_block(evt),
        "assumptions": evt.assumptions.as_dict(),
        "risk": risk_to_dict(risk),
        "trace": outcome.trace.as_dict(),
        "case_view": case_view(outcome.trace),
        "result": {
            "state": outcome.state.value,
            "resolution": outcome.resolution.value,
            "service_success": outcome.resolution.is_service_success,
        },
        "gate": gate_block(outcome.gate),
        "model_calls": [{"purpose": p, "model": m} for p, m in client.calls],
    }
    if extra:
        bundle.update(extra)
    return bundle


def write(name: str, payload: Any) -> None:
    path = OUT / name
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"  console/fixtures/{name}")


# --- the fixtures -----------------------------------------------------------


def fx_safe() -> dict[str, Any]:
    """1. SAFE. Dismissed by the prefilter; no model call at either end."""
    evt = event(
        "SG-CONN-4471",
        state="SAFE",
        slack=9.6,
        no_itt=13.8,
        boxes=12,
        confidence="HIGH",
        codes=("INBOUND_ETA_SLIP",),
        inbound_vessel="SYNTHETIC EVER",
        outbound_vessel="SYNTHETIC KOTA",
    )
    return capture(
        "01-safe",
        "SAFE — dismissed at triage",
        "The funnel working. A SAFE event never reaches a model: "
        "triage.prefilter dismisses it deterministically, so the trace carries "
        "no model_call step and the run costs nothing.",
        evt,
    )


def fx_watch() -> dict[str, Any]:
    """2. WATCH. Real decision, cheap, auto-approved under policy."""
    evt = event(
        "SG-CONN-4482",
        state="WATCH",
        slack=3.1,
        no_itt=7.4,
        boxes=22,
        confidence="HIGH",
        offset_min=2,
        inbound_vessel="SYNTHETIC MSC",
        outbound_vessel="SYNTHETIC FEEDER II",
    )
    return capture(
        "02-watch",
        "WATCH — margin thinning, resolved inside policy",
        "Small volume, live data, confidence above threshold: the gate "
        "auto-approves and no signature is required. The contrast case for "
        "everything that follows.",
        evt,
    )


def fx_at_risk_rescuable() -> dict[str, Any]:
    """3. AT_RISK, rescuable by removing the inter-terminal move."""
    evt = event(
        "SG-CONN-4490",
        state="AT_RISK",
        slack=-1.8,
        no_itt=2.4,
        boxes=84,
        confidence="MEDIUM",
        offset_min=4,
        inbound_vessel="SYNTHETIC CMA",
        outbound_vessel="SYNTHETIC FEEDER III",
    )
    return capture(
        "03-at-risk-rescuable",
        "AT RISK — the transfer is the problem",
        "itt_is_the_problem is true: 2.4h of margin without the transfer, "
        "-1.8h with it. B emits a Rung 1 advisory alongside the Rung 3 move, "
        "never instead of it, and the barge legs are excluded because their "
        "assumed transit misses the modelled cutoff.",
        evt,
    )


def fx_at_risk_not_rescuable() -> dict[str, Any]:
    """4. AT_RISK, nothing available resolves it."""
    evt = event(
        "SG-CONN-4503",
        state="AT_RISK",
        slack=-3.2,
        no_itt=-0.9,
        boxes=61,
        avoidable=False,
        confidence="HIGH",
        codes=("INBOUND_ETA_SLIP", "OUTBOUND_CUTOFF_ADVANCED", "BERTH_CONGESTION"),
        offset_min=6,
        inbound_vessel="SYNTHETIC ONE",
        outbound_vessel="SYNTHETIC FEEDER IV",
    )
    return capture(
        "04-at-risk-not-rescuable",
        "AT RISK — no internal option, and the line never answers",
        "Negative margin even without the transfer, so every leg is excluded "
        "and Rung 4 is the floor rather than the failure case. The line is "
        "asked and does not reply: WINDOW_LAPSED_NO_RESPONSE, the one exit "
        "that is a service failure.",
        evt,
        customer=CustomerSilent(),
    )


def fx_failure_injection() -> dict[str, Any]:
    """5. The centrepiece. Timeout, retry, stale cache, gate tightens."""
    evt = event(
        "SG-CONN-4518",
        state="AT_RISK",
        slack=-0.5,
        no_itt=6.0,
        boxes=34,
        confidence="HIGH",
        offset_min=8,
        inbound_vessel="SYNTHETIC HAPAG",
        outbound_vessel="SYNTHETIC FEEDER V",
    )
    # Real inventory, served stale. An empty cache would make this a Rung 4
    # case and lose the escalation the fixture exists to show.
    cache = CacheEntry(
        value=build_itt_inventory(T0, Terminal.TUAS, Terminal.PASIR_PANJANG),
        age_min=8.0,
    )
    return capture(
        "05-failure-injection",
        "Confidence degrades, the gate tightens on its own",
        "query_itt_slot times out, retries, times out again, and falls back to "
        "inventory read from cache 8 minutes ago. Nobody lowers the confidence "
        "— it falls out of the cache read, and gates.evaluate() escalates the "
        "approval from auto to a named human. The human approves.",
        evt,
        failures={"query_itt_slot": [ToolStatus.TIMEOUT, ToolStatus.TIMEOUT]},
        itt_cache=cache,
        approvals=AutoApprove(),
    )


def fx_declined_approval() -> dict[str, Any]:
    """5b. The same run as fixture 5, declined instead of approved.

    Identical event, identical failure injection, identical confidence and gate.
    The only difference is what the human said. Captured so the console's
    decline control leads to a recorded branch rather than to a caption
    describing one.
    """
    evt = event(
        "SG-CONN-4518",
        state="AT_RISK",
        slack=-0.5,
        no_itt=6.0,
        boxes=34,
        confidence="HIGH",
        offset_min=8,
        inbound_vessel="SYNTHETIC HAPAG",
        outbound_vessel="SYNTHETIC FEEDER V",
    )
    cache = CacheEntry(
        value=build_itt_inventory(T0, Terminal.TUAS, Terminal.PASIR_PANJANG),
        age_min=8.0,
    )
    return capture(
        "05b-approval-declined",
        "The same run, declined",
        "Vessel Operations declines the escalated transfer. B fires the "
        "default action and records CUSTOMER_DECLINED_ALL. Same event, same "
        "0.6672 confidence, same escalation — the only variable is the human.",
        evt,
        failures={"query_itt_slot": [ToolStatus.TIMEOUT, ToolStatus.TIMEOUT]},
        itt_cache=cache,
        approvals=RejectsApproval(),
        extra={"branch_of": "05-failure-injection", "branch_label": "declined"},
    )


def fx_lapsed_approval() -> dict[str, Any]:
    """5c. The same run again, with nobody signing.

    Completes the branch set for the demo: approve, decline, and let it lapse
    are all recorded runs of one event, so the console's approval panel never
    has to narrate an outcome it did not capture.
    """
    evt = event(
        "SG-CONN-4518",
        state="AT_RISK",
        slack=-0.5,
        no_itt=6.0,
        boxes=34,
        confidence="HIGH",
        offset_min=8,
        inbound_vessel="SYNTHETIC HAPAG",
        outbound_vessel="SYNTHETIC FEEDER V",
    )
    cache = CacheEntry(
        value=build_itt_inventory(T0, Terminal.TUAS, Terminal.PASIR_PANJANG),
        age_min=8.0,
    )
    return capture(
        "05c-approval-lapsed",
        "The same run, unsigned",
        "Nobody answers the escalation. B moves the case to LAPSED and fires "
        "the default action, recording WINDOW_LAPSED_NO_RESPONSE even though "
        "the shipping line was never contacted.",
        evt,
        failures={"query_itt_slot": [ToolStatus.TIMEOUT, ToolStatus.TIMEOUT]},
        itt_cache=cache,
        approvals=NeverApproves(),
        extra={"branch_of": "05-failure-injection", "branch_label": "lapsed"},
    )


def fx_lapsed() -> dict[str, Any]:
    """6. LAPSED. The internal approval never came."""
    evt = event(
        "SG-CONN-4526",
        state="AT_RISK",
        slack=-1.1,
        no_itt=5.5,
        boxes=96,
        confidence="MEDIUM",
        offset_min=10,
        inbound_vessel="SYNTHETIC YANG MING",
        outbound_vessel="SYNTHETIC FEEDER VI",
    )
    return capture(
        "06-lapsed",
        "LAPSED — nobody signed, the default action fired",
        "96 boxes trips the volume gate, so a signature is required. None "
        "arrives. B moves the case to LAPSED and fires the default action "
        "anyway, because doing nothing is also a decision and is traced as one.",
        evt,
        approvals=NeverApproves(),
    )


def fx_declined() -> dict[str, Any]:
    """7. The exit that looks like failure and is not."""
    evt = event(
        "SG-CONN-4534",
        state="AT_RISK",
        slack=-2.6,
        no_itt=-0.4,
        boxes=29,
        avoidable=False,
        confidence="HIGH",
        offset_min=12,
        inbound_vessel="SYNTHETIC OOCL",
        outbound_vessel="SYNTHETIC FEEDER VII",
    )
    return capture(
        "07-customer-declined",
        "The line declined every option — and was served",
        "The box rolls, exactly as in fixture 4. The difference is that the "
        "line was asked, had real options, and said no. Resolution."
        "is_service_success is true here and false there, and making that "
        "difference legible is the most valuable thing on the screen.",
        evt,
        customer=CustomerDeclinesAll(),
    )


def fx_contention() -> list[dict[str, Any]]:
    """10 and 11. Two connections, one slot. Both are real runs.

    The pair shares a single `LockTable`, so the contention is genuine rather
    than described: the first connection claims the slot and commits it, and
    the second finds it taken and has to do something else.

    One limitation, stated because it would otherwise look like the Lock Table
    only handles the easy case. `runner.handle()` runs a risk from detection to
    resolution without yielding, so two deliberations never interleave in one
    process. That means the reachable contention here is
    `incumbent_committed` — capacity that has already been consumed and must
    not be booked twice. Priority preemption, where a more urgent risk takes an
    uncommitted reservation from a less urgent one, needs concurrent
    deliberation and is exercised by B's own tests instead. Neither is
    simulated here.
    """
    table = LockTable()

    first = event(
        "SG-CONN-4562",
        state="AT_RISK",
        slack=-1.2,
        no_itt=6.0,
        boxes=38,
        confidence="HIGH",
        offset_min=18,
        inbound_vessel="SYNTHETIC EVERGREEN",
        outbound_vessel="SYNTHETIC FEEDER X",
    )
    second = event(
        "SG-CONN-4571",
        state="AT_RISK",
        slack=-0.7,
        no_itt=6.0,
        boxes=24,
        confidence="HIGH",
        offset_min=20,
        inbound_vessel="SYNTHETIC WAN HAI",
        outbound_vessel="SYNTHETIC FEEDER XI",
    )

    winner = capture(
        "10-contention-winner",
        "Took the contested slot",
        "Claims the transfer slot uncontested, books it, and commits. A "
        "committed reservation is consumed capacity and is never preempted — "
        "the physical move has begun.",
        first,
        locks=table,
    )
    loser = capture(
        "11-contention-loser",
        "Lost the slot, and still had something to offer",
        "Finds the same slot already committed to another connection. Rather "
        "than dying quietly it re-deliberates with that option removed, and "
        "falls to Rung 4 — losing a slot is not the same as having nothing to "
        "offer.",
        second,
        locks=table,
        extra={"contends_with": "SG-CONN-4562"},
    )
    return [winner, loser]


def fx_superseded() -> dict[str, Any]:
    """8. SUPERSEDED. Authored closure, real admission decision.

    `runner.handle()` is atomic and never yields a trace mid-flight, so a real
    run cannot produce a case that is superseded while deliberating
    (CONTRACTS.md section 9). What is real here is the `AdmissionDecision`: two
    events for the same connection go through B's actual `CaseRegistry`, and it
    decides the second one supersedes the first.

    The trace is built with B's own `Trace` recorder and every state move goes
    through B's `transition()`, which raises on an illegal move. So the shape is
    enforced by B even though the sequence is C's.
    """
    v1 = event(
        "SG-CONN-4541",
        state="AT_RISK",
        slack=-0.9,
        no_itt=4.2,
        boxes=41,
        confidence="MEDIUM",
        offset_min=14,
        inbound_vessel="SYNTHETIC COSCO",
        outbound_vessel="SYNTHETIC FEEDER VIII",
    )
    v2 = event(
        "SG-CONN-4541",
        state="WATCH",
        slack=3.6,
        no_itt=4.2,
        boxes=41,
        confidence="MEDIUM",
        offset_min=27,
        inbound_vessel="SYNTHETIC COSCO",
        outbound_vessel="SYNTHETIC FEEDER VIII",
    )

    registry = CaseRegistry()
    first = registry.admit(v1)

    risk = v1.to_connection_risk()
    trace = Trace.for_risk(risk)
    registry.opened(v1.connection_id, trace.trace_id)

    state = RiskState.DETECTED
    trace.observation(
        f"{v1.assumptions.qualifier}: {v1.state.value}, {v1.affected_boxes} boxes, "
        f"{v1.current_plan_slack_hours:+.1f}h remaining margin "
        f"({v1.no_itt_slack_hours:+.1f}h if the transfer requirement were removed)",
        connection_type=v1.assumptions.connection_type.value,
        reason_codes=[c.value for c in v1.reason_codes],
        watcher_confidence=v1.watcher_confidence.value,
        priority=round(v1.priority, 2),
    )
    trace.observation("assumption basis for every figure in this trace", **v1.assumptions.as_dict())
    trace.model_call(TRIAGE_MODEL, 1_612, 74, purpose="triage")
    trace.observation(
        "0.9h past the window with a transfer on the critical path; deliberating",
        triage_route="model_kept",
    )
    state = transition(state, RiskState.TRIAGED)
    trace.state_change("detected", state.value, "model_kept")
    state = transition(state, RiskState.DELIBERATING)
    trace.state_change("triaged", state.value, "walking the ladder")
    trace.tool_call("query_itt_slot", status="ok", latency_ms=420, attempts=1)

    second = registry.admit(v2)

    trace.observation(
        "inbound arrival estimate improved 270m mid-deliberation; "
        f"margin restored to {v2.current_plan_slack_hours:+.1f}h",
        superseding_event=v2.connection_id,
        admission=second.admission.value,
    )
    state = transition(state, RiskState.SUPERSEDED)
    trace.state_change("deliberating", state.value, second.reason)
    trace.close(Resolution.SUPERSEDED)

    return {
        "fixture_id": "08-superseded",
        "title": "SUPERSEDED — the risk evaporated mid-deliberation",
        "what_it_shows": (
            "The arrival estimate improved while the agent was still working, so "
            "the case is abandoned cleanly rather than acted on. Excluded from "
            "the north-star denominator, because it was never a connection "
            "genuinely at risk of failing."
        ),
        "provenance": {
            "produced_by": "CaseRegistry.admit() + Trace/transition()",
            "authored": True,
            "authored_because": (
                "runner.handle() is atomic and has no supersession path "
                "(CONTRACTS.md section 9), so no real run yields a trace that is "
                "superseded mid-flight. The AdmissionDecision below is genuine "
                "CaseRegistry output; the trace sequence is C's, but every state "
                "move goes through B's transition() and would raise if illegal."
            ),
            "model_responses": "scripted",
            "data_basis": (
                "real vessel movement data + derived arrival estimates + "
                "synthetic transhipment connections"
            ),
        },
        "event": v1.to_dict()
        | {
            "inbound_terminal": v1.inbound_terminal.value,
            "outbound_terminal": v1.outbound_terminal.value,
            "terminal_resolution": v1.terminal_resolution.value,
            "inbound_vessel": v1.inbound_vessel,
            "outbound_vessel": v1.outbound_vessel,
            "source": v1.source,
        },
        "superseding_event": v2.to_dict(),
        "admission": [asdict(first), asdict(second)],
        "derived": derived_block(v1),
        "assumptions": v1.assumptions.as_dict(),
        "risk": risk_to_dict(risk),
        "trace": trace.as_dict(),
        "case_view": case_view(trace),
        "result": {
            "state": state.value,
            "resolution": Resolution.SUPERSEDED.value,
            "service_success": Resolution.SUPERSEDED.is_service_success,
        },
        "gate": None,
        "model_calls": [{"purpose": "triage", "model": TRIAGE_MODEL}],
    }


def fx_stale() -> dict[str, Any]:
    """9. STALE. Authored, and labelled as reachable-in-principle only.

    `RiskState.STALE` is declared in B's state machine with legal transitions in
    and out, and nothing in `src/latch` ever enters it (CONTRACTS.md section 8).
    This fixture drives B's real `transition()` to show what the console does
    when it arrives — it does not claim a run produced it.
    """
    evt = event(
        "SG-CONN-4550",
        state="AT_RISK",
        slack=-1.4,
        no_itt=3.8,
        boxes=53,
        confidence="LOW",
        offset_min=16,
        inbound_vessel="SYNTHETIC PIL",
        outbound_vessel="SYNTHETIC FEEDER IX",
    )
    risk = evt.to_connection_risk()
    trace = Trace.for_risk(risk)
    state = RiskState.DETECTED

    trace.observation(
        f"{evt.assumptions.qualifier}: {evt.state.value}, {evt.affected_boxes} boxes, "
        f"{evt.current_plan_slack_hours:+.1f}h remaining margin "
        f"({evt.no_itt_slack_hours:+.1f}h if the transfer requirement were removed)",
        connection_type=evt.assumptions.connection_type.value,
        reason_codes=[c.value for c in evt.reason_codes],
        watcher_confidence=evt.watcher_confidence.value,
        priority=round(evt.priority, 2),
    )
    trace.observation("assumption basis for every figure in this trace", **evt.assumptions.as_dict())
    trace.tool_call("query_itt_slot", status="error", latency_ms=420, attempts=2)
    trace.error(
        "query_itt_slot",
        error_class="error",
        retries=1,
        recovery="no fallback available",
    )
    trace.tool_call("query_outbound_services", status="error", latency_ms=520, attempts=2)
    trace.error(
        "query_outbound_services",
        error_class="error",
        retries=1,
        recovery="no fallback available",
    )
    trace.observation(
        "upstream inventory unavailable and nothing stale to fall back on; "
        "proceeding would be inventing capacity"
    )
    state = transition(state, RiskState.STALE)
    trace.state_change("detected", state.value, "upstream data missing; gates tighten")

    return {
        "fixture_id": "09-stale",
        "title": "STALE — upstream data missing, gates tightened",
        "what_it_shows": (
            "Both read tools fail with nothing cached. The agent has nothing to "
            "propose and says so rather than guessing. Confidence is not "
            "computed at all, because a plan resting on nothing we can name is "
            "not a plan."
        ),
        "provenance": {
            "produced_by": "Trace + transition()",
            "authored": True,
            "authored_because": (
                "RiskState.STALE is declared in B's state machine and no code "
                "path enters it (CONTRACTS.md section 8). This fixture is "
                "reachable-in-principle, not the output of a run. It exists so "
                "the console has a defined rendering if B wires the state up; "
                "it is not evidence that the behaviour exists today."
            ),
            "model_responses": "none consulted",
            "data_basis": (
                "real vessel movement data + derived arrival estimates + "
                "synthetic transhipment connections"
            ),
        },
        "event": evt.to_dict()
        | {
            "inbound_terminal": evt.inbound_terminal.value,
            "outbound_terminal": evt.outbound_terminal.value,
            "terminal_resolution": evt.terminal_resolution.value,
            "inbound_vessel": evt.inbound_vessel,
            "outbound_vessel": evt.outbound_vessel,
            "source": evt.source,
        },
        "derived": derived_block(evt),
        "assumptions": evt.assumptions.as_dict(),
        "risk": risk_to_dict(risk),
        "trace": trace.as_dict(),
        "case_view": case_view(trace),
        "result": {
            "state": state.value,
            "resolution": None,
            "service_success": None,
        },
        "gate": None,
        "model_calls": [],
    }


# --- main -------------------------------------------------------------------

BUILDERS = (
    fx_safe,
    fx_watch,
    fx_at_risk_rescuable,
    fx_at_risk_not_rescuable,
    fx_failure_injection,
    fx_declined_approval,
    fx_lapsed_approval,
    fx_lapsed,
    fx_declined,
    fx_contention,
    fx_superseded,
    fx_stale,
)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print("capturing fixtures from B's pipeline:")

    bundles = []
    for build in BUILDERS:
        produced = build()
        for bundle in produced if isinstance(produced, list) else [produced]:
            bundles.append(bundle)
            write(f"{bundle['fixture_id']}.json", bundle)

    index = {
        "generated_by": "console/scripts/capture_fixtures.py",
        "data_basis": (
            "real vessel movement data + derived arrival estimates + "
            "synthetic transhipment connections"
        ),
        "model_responses": "scripted; no model was consulted",
        "policy": {
            "confidence_escalation_threshold": CONFIDENCE_ESCALATION_THRESHOLD,
            "deliberation_model": DELIBERATION_MODEL,
            "triage_model": TRIAGE_MODEL,
        },
        "fixtures": [
            {
                "fixture_id": b["fixture_id"],
                "file": f"{b['fixture_id']}.json",
                "title": b["title"],
                "connection_id": b["event"]["connection_id"],
                "severity": b["event"]["state"],
                "boxes": b["event"]["affected_boxes"],
                "state": b["result"]["state"],
                "resolution": b["result"]["resolution"],
                "service_success": b["result"]["service_success"],
                "authored": b["provenance"]["authored"],
                "confidence": (
                    b["case_view"]["confidence"]["value"]
                    if b["case_view"]["confidence"]
                    else None
                ),
                "required_role": b["gate"]["required_role"] if b["gate"] else None,
                "escalated": b["gate"]["escalated"] if b["gate"] else False,
                "usd": b["trace"]["cost"]["usd"],
            }
            for b in bundles
        ],
    }
    write("index.json", index)

    print()
    header = f"  {'fixture':26} {'state':12} {'conf':>6} {'role':13} {'usd':>9}"
    print(header)
    print(f"  {'-' * (len(header) - 2)}")
    for row in index["fixtures"]:
        conf = f"{row['confidence']:.4f}" if row["confidence"] is not None else "-"
        print(
            f"  {row['fixture_id']:26} {row['state']:12} {conf:>6} "
            f"{(row['required_role'] or '-'):13} {row['usd']:>9.4f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
