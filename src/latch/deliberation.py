"""Deliberation: enumerate options, then choose between them.

The split matters. **Code enumerates; the model ranks.** Candidate options are
built from what the tools actually returned, and the model is asked only to
choose among them and explain why. It is never asked what the options are, so
it cannot book a slot that does not exist — and a chosen id that is not on the
list is rejected rather than executed.

Confidence is computed from the provenance of the tool calls that produced
each option, so a plan resting on a stale cache read scores lower without
anyone deciding it should.
"""

from dataclasses import dataclass
from typing import Any

from latch.confidence import ConfidenceBreakdown, score
from latch.config import DELIBERATION_MAX_TOKENS, DELIBERATION_MODEL
from latch.events import RiskEvent
from latch.llm import ModelClient
from latch.models import (
    ActionKind,
    ConnectionRisk,
    Plan,
    PlanAction,
    Provenance,
    Rung,
    dataclasses_replace,
)
from latch.tools import (
    CacheEntry,
    FailurePlan,
    NoFailures,
    ToolResult,
    call,
    connection_density_score,
    itt_transit_minutes,
    query_itt_slot,
    query_outbound_services,
)

DELIBERATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "chosen_plan_id": {
            "type": "string",
            "description": "Exactly one id from the candidate list.",
        },
        "ranking": {
            "type": "array",
            "items": {"type": "string"},
            "description": "All candidate ids, best first.",
        },
        "rationale": {
            "type": "string",
            "description": "Two sentences at most. Why this one, over the others.",
        },
    },
    "required": ["chosen_plan_id", "ranking", "rationale"],
    "additionalProperties": False,
}

DELIBERATION_SYSTEM = """You choose between remediation options for container \
connections at risk at the Port of Singapore.

You are given candidate options already checked for feasibility against live \
inventory. Rank them and pick one. Every id you return must come from that list \
— do not invent options.

Two kinds of option appear:

  Rung 3, move    books an inter-terminal transfer. Resolves the connection \
inside PSA, at real cost and real emissions.
  Rung 4, offer   puts ranked options to the shipping line. The line owns the \
final decision about its own cargo; PSA cannot re-route it for them.

If any Rung 3 option resolves the connection, choose it. Rung 4 is for when \
nothing available resolves it internally. Handing the customer a decision you \
could have made yourself spends their attention and gains them nothing.

The exception is timing, not preference. Option count decays: where confirming \
an internal fix would take longer than the customer's remaining options will \
survive, go to Rung 4 while the choice is still real. A choice offered early is \
a decision; the same choice offered late is a notification.

Where Rung 3 options differ on speed, cost and emissions, say which tradeoff you \
made rather than leaving it implicit."""


@dataclass(frozen=True, slots=True)
class ExcludedOption:
    """An option the tools returned that the agent ruled out, and why.

    Filtering happens in code before the prompt is built, so the model never
    sees these and cannot explain them. Without recording them the reasoning
    is invisible: a trace showing only road options looks like an agent that
    never considered a barge, rather than one that considered and rejected it.
    """

    option_id: str
    rung: Rung
    reason: str


@dataclass(frozen=True, slots=True)
class DeliberationResult:
    plans: tuple[Plan, ...]
    chosen: Plan | None
    tool_results: tuple[ToolResult, ...]
    rationale: str
    advisories: tuple[Plan, ...] = ()
    excluded: tuple[ExcludedOption, ...] = ()
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    rejected_choice: str | None = None

    @property
    def options_alive(self) -> int:
        return len(self.plans)


def _gather(
    risk: ConnectionRisk,
    event: RiskEvent,
    failures: FailurePlan,
    itt_cache: CacheEntry | None,
) -> tuple[list[ToolResult], list[Any], list[Any]]:
    """Run the read tools. Returns results plus whatever each one produced."""
    results: list[ToolResult] = []

    itt = call(
        "query_itt_slot",
        lambda: query_itt_slot(
            risk.detected_at,
            risk.inbound.terminal,
            risk.outbound.terminal,
            event.affected_boxes,
        ),
        failures,
        max_retries=1,
        cache=itt_cache,
    )
    results.append(itt)

    outbound = call(
        "query_outbound_services",
        lambda: query_outbound_services(risk.detected_at, risk.outbound.terminal),
        failures,
    )
    results.append(outbound)

    return results, list(itt.value or []), list(outbound.value or [])


def _viable(slot: Any, event: RiskEvent) -> bool:
    """Would this slot actually get the boxes there in time?

    `no_itt_slack_hours` is the slack with the transfer removed; putting a
    transfer back costs its transit time. A slot that arrives after the cutoff
    is not an option, however cheap it is.
    """
    spare_min = event.no_itt_slack_hours * 60.0 - itt_transit_minutes(slot.mode)
    return spare_min > 0


def build_candidates(
    risk: ConnectionRisk,
    event: RiskEvent,
    itt_slots: list[Any],
    outbound: list[Any],
    provenance: tuple[Provenance, ...],
) -> tuple[list[Plan], list[Plan], list[ExcludedOption]]:
    """Enumerate options. Returns (actionable, advisory, excluded).

    The three-way split matters. Rung 1 is an *advisory*: it surfaces a number
    to a planner and changes nothing about this connection on its own. Offered
    as a peer of Rung 3 and Rung 4 it can be selected as **the** action, which
    leaves the boxes exactly where they were while someone reads a score.

    So advisories are emitted alongside whatever action is chosen, never
    instead of one. The model only ever chooses among things that actually move
    cargo or hand the decision to someone who can.
    """
    actionable: list[Plan] = []
    advisory: list[Plan] = []
    excluded: list[ExcludedOption] = []
    breakdown: ConfidenceBreakdown = score(provenance)

    # Rung 1 — only when preventing the transfer would genuinely save it.
    # Offered otherwise, it is noise the planner learns to ignore.
    if event.itt_is_the_problem:
        density = connection_density_score(
            f"{risk.inbound.terminal.value}-candidate",
            connections_served=event.affected_boxes,
            connections_stranded=0,
        )
        advisory.append(
            Plan(
                plan_id=f"{risk.risk_id}-r1-prevent",
                risk_id=risk.risk_id,
                rung=Rung.INFORM,
                actions=(
                    PlanAction(
                        ActionKind.SURFACE_DENSITY_SCORE,
                        target=risk.outbound.terminal.value,
                        detail=(
                            f"co-locating would recover "
                            f"{event.itt_cost_hours:.1f}h of slack "
                            f"(density {density['density_score']:.2f})"
                        ),
                    ),
                ),
                rationale="",
                provenance=provenance,
                confidence=breakdown.confidence,
            )
        )

    # Rung 3 — one plan per viable slot. Road and barge differ on time,
    # cost and emissions, so the choice is real rather than decorative.
    for slot in itt_slots:
        if not _viable(slot, event):
            transit = itt_transit_minutes(slot.mode)
            window = event.no_itt_slack_hours * 60.0
            excluded.append(
                ExcludedOption(
                    option_id=slot.slot_id,
                    rung=Rung.MOVE,
                    reason=(
                        f"{slot.mode.value} transit is {transit}m against a "
                        f"{window:.0f}m window; arrives after the cutoff"
                    ),
                )
            )
            continue
        actionable.append(
            Plan(
                plan_id=f"{risk.risk_id}-r3-{slot.slot_id}",
                risk_id=risk.risk_id,
                rung=Rung.MOVE,
                actions=(
                    PlanAction(
                        ActionKind.BOOK_ITT_LEG,
                        target=slot.resource_key,
                        detail=(
                            f"{slot.mode.value}, departs "
                            f"{slot.departs_at:%H:%M}, "
                            f"{itt_transit_minutes(slot.mode)}m transit"
                        ),
                    ),
                ),
                rationale="",
                cost_sgd=round(slot.cost_sgd * event.affected_boxes, 2),
                emissions_kg_co2e=round(
                    slot.emissions_kg_co2e * event.affected_boxes, 2
                ),
                resources_required=(slot.resource_key,),
                provenance=provenance,
                confidence=breakdown.confidence,
            )
        )

    # Rung 4 — always available while any outbound service is still callable.
    # This is the floor, not the failure case.
    if outbound:
        actionable.append(
            Plan(
                plan_id=f"{risk.risk_id}-r4-offer",
                risk_id=risk.risk_id,
                rung=Rung.OFFER,
                actions=(
                    PlanAction(
                        ActionKind.OFFER_OPTIONS_TO_LINE,
                        target="line",
                        detail=f"{len(outbound)} outbound services still callable",
                    ),
                ),
                rationale="",
                resources_required=(),
                provenance=provenance,
                confidence=breakdown.confidence,
                options_alive=len(outbound),
            )
        )

    return actionable, advisory, excluded


def _prompt(risk: ConnectionRisk, event: RiskEvent, plans: list[Plan]) -> str:
    lines = [
        f"Connection {event.connection_id}: {event.affected_boxes} boxes.",
        f"Short by {event.slack_deficit_hours:.1f}h under the current plan.",
        f"The inter-terminal transfer is costing {event.itt_cost_hours:.1f}h.",
        f"Removing it would save the connection: {event.itt_is_the_problem}.",
        f"Watcher confidence: {event.watcher_confidence.value}.",
        "",
        "Candidates:",
    ]
    for plan in plans:
        detail = "; ".join(a.detail for a in plan.actions if a.detail)
        lines.append(
            f"  {plan.plan_id} [{plan.rung.value}] {detail}"
            f" | cost SGD {plan.cost_sgd:,.0f}"
            f" | {plan.emissions_kg_co2e:,.0f} kg CO2e"
        )
    return "\n".join(lines)


def deliberate(
    risk: ConnectionRisk,
    event: RiskEvent,
    client: ModelClient,
    *,
    failures: FailurePlan | None = None,
    itt_cache: CacheEntry | None = None,
) -> DeliberationResult:
    """Walk the ladder and produce a ranked set of options."""
    failures = failures or NoFailures()
    tool_results, itt_slots, outbound = _gather(risk, event, failures, itt_cache)

    provenance = tuple(
        [event.provenance()]
        + [
            r.provenance(r.tool, verified=r.ok and r.attempts == 1)
            for r in tool_results
        ]
    )
    plans, advisories, excluded = build_candidates(
        risk, event, itt_slots, outbound, provenance
    )

    if not plans:
        return DeliberationResult(
            plans=(),
            chosen=None,
            tool_results=tuple(tool_results),
            rationale="No feasible option: no viable transfer and no outbound "
            "service still callable.",
            advisories=tuple(advisories),
            excluded=tuple(excluded),
        )

    response = client.complete_json(
        model=DELIBERATION_MODEL,
        system=DELIBERATION_SYSTEM,
        prompt=_prompt(risk, event, plans),
        schema=DELIBERATION_SCHEMA,
        max_tokens=DELIBERATION_MAX_TOKENS,
        purpose="deliberation",
    )

    by_id = {p.plan_id: p for p in plans}
    chosen_id = str(response.data["chosen_plan_id"])
    rejected: str | None = None

    if chosen_id not in by_id:
        # The model picked something that does not exist. Fall back to the
        # first candidate rather than executing a fiction, and keep the bad id
        # so the trace records that it happened.
        rejected = chosen_id
        chosen_id = plans[0].plan_id

    ranking = [pid for pid in response.data.get("ranking", []) if pid in by_id]
    ordered = [by_id[pid] for pid in ranking]
    ordered += [p for p in plans if p.plan_id not in set(ranking)]

    rationale = str(response.data["rationale"])
    chosen = dataclasses_replace(by_id[chosen_id], rationale=rationale)

    return DeliberationResult(
        plans=tuple(ordered),
        chosen=chosen,
        tool_results=tuple(tool_results),
        rationale=rationale,
        advisories=tuple(advisories),
        excluded=tuple(excluded),
        model=response.model,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        rejected_choice=rejected,
    )
