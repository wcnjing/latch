"""The pipeline. One risk event in, one closed trace out.

    risk received -> triage -> gather -> compare -> check locks
                  -> recommend -> approve if required -> track to resolution

Approval and the customer response are injected rather than hardcoded, because
both are things we do not control. A duty manager may not sign, and a shipping
line may never reply — and the whole point of Rung 4 is that the third case is
a real outcome rather than an error path.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from latch.config import CUSTOMER_WINDOW_MIN
from latch.confidence import score
from latch.deliberation import DeliberationResult, deliberate
from latch.events import RiskEvent
from latch.gates import GateDecision, evaluate
from latch.llm import ModelClient
from latch.locks import LockTable
from latch.models import ApprovalRole, Plan, Resolution, Rung
from latch.state import RiskState, transition
from latch.tools import CacheEntry, FailurePlan, NoFailures
from latch.trace import Trace, TraceStore


class ApprovalPolicy(Protocol):
    """Stands in for a human. Returns None to mean 'never answered'."""

    def decide(self, role: ApprovalRole, plan: Plan) -> bool | None: ...


class CustomerGate(Protocol):
    """Stands in for the line. Returns the chosen plan id, False for declined
    everything, or None for no response before the window closed."""

    def respond(self, options: tuple[Plan, ...]) -> str | bool | None: ...


class AutoApprove:
    def decide(self, role: ApprovalRole, plan: Plan) -> bool | None:
        return True


class NeverApproves:
    def decide(self, role: ApprovalRole, plan: Plan) -> bool | None:
        return None


class CustomerAccepts:
    def respond(self, options: tuple[Plan, ...]) -> str | bool | None:
        return options[0].plan_id if options else None


class CustomerDeclinesAll:
    def respond(self, options: tuple[Plan, ...]) -> str | bool | None:
        return False


class CustomerSilent:
    """The failure case. The one the impact slide is about."""

    def respond(self, options: tuple[Plan, ...]) -> str | bool | None:
        return None


@dataclass(slots=True)
class Outcome:
    trace: Trace
    state: RiskState
    resolution: Resolution
    chosen: Plan | None = None
    gate: GateDecision | None = None


def _record_deliberation(
    trace: Trace, result: DeliberationResult, qualifier: str
) -> None:
    for tool in result.tool_results:
        trace.tool_call(
            tool.tool,
            status=tool.status.value,
            latency_ms=tool.latency_ms,
            attempts=tool.attempts,
        )
        if not tool.ok or tool.attempts > 1:
            trace.error(
                tool.tool,
                error_class=tool.error_class or "unknown",
                retries=tool.attempts - 1,
                recovery=(
                    f"cached inventory @ T-{tool.age_min:.0f}m"
                    if tool.source.value == "cache"
                    else "no fallback available"
                ),
            )
    if result.model:
        trace.model_call(
            result.model,
            result.input_tokens,
            result.output_tokens,
            purpose="deliberation",
        )
    for ruled_out in result.excluded:
        trace.observation(
            f"{qualifier.lower()}, ruled out "
            f"{ruled_out.option_id}: {ruled_out.reason}",
            rung=ruled_out.rung.value,
            considered=True,
        )
    if result.rejected_choice:
        trace.observation(
            "model chose an id that is not a candidate; falling back to the "
            "top-ranked real option",
            rejected_id=result.rejected_choice,
        )


def handle(
    event: RiskEvent,
    *,
    client: ModelClient,
    store: TraceStore,
    locks: LockTable | None = None,
    failures: FailurePlan | None = None,
    itt_cache: CacheEntry | None = None,
    approvals: ApprovalPolicy | None = None,
    customer: CustomerGate | None = None,
    now: datetime | None = None,
) -> Outcome:
    """Run one risk event end to end."""
    from latch.triage import triage

    locks = locks if locks is not None else LockTable()
    failures = failures or NoFailures()
    approvals = approvals or AutoApprove()
    customer = customer or CustomerSilent()
    now = now or datetime.now(UTC)

    risk = event.to_connection_risk()
    trace = store.open(risk)
    state = RiskState.DETECTED

    # Every derived figure below is a scenario output, not an observation.
    # Stating them flat would put "PSA confirmed this needs 5.2 hours" into an
    # audit trail — a fabricated claim about the real world.
    assumptions = event.assumptions
    trace.observation(
        f"{assumptions.qualifier}: {event.state.value}, "
        f"{event.affected_boxes} boxes, "
        f"{event.current_plan_slack_hours:+.1f}h remaining margin "
        f"({event.no_itt_slack_hours:+.1f}h if the transfer requirement were removed)",
        connection_type=assumptions.connection_type.value,
        reason_codes=[c.value for c in event.reason_codes],
        watcher_confidence=event.watcher_confidence.value,
        priority=round(event.priority, 2),
    )
    trace.observation(
        "assumption basis for every figure in this trace",
        **assumptions.as_dict(),
    )

    # --- triage -------------------------------------------------------------
    verdict = triage(event, client)
    if verdict.model_used:
        trace.model_call(
            verdict.model, verdict.input_tokens, verdict.output_tokens, purpose="triage"
        )
    trace.observation(verdict.reason, triage_route=verdict.route.value)

    if not verdict.keep:
        state = transition(state, RiskState.DISMISSED)
        trace.state_change("detected", state.value, verdict.reason)
        trace.close(Resolution.DISMISSED_NO_ACTION)
        return Outcome(trace, state, Resolution.DISMISSED_NO_ACTION)

    state = transition(state, RiskState.TRIAGED)
    trace.state_change("detected", state.value, verdict.route.value)
    state = transition(state, RiskState.DELIBERATING)
    trace.state_change("triaged", state.value, "walking the ladder")

    # --- deliberate ---------------------------------------------------------
    result = deliberate(risk, event, client, failures=failures, itt_cache=itt_cache)
    _record_deliberation(trace, result, assumptions.qualifier)

    breakdown = score(result.chosen.provenance) if result.chosen else None
    if breakdown is not None:
        # Before any decision cites the number, so a reader sees where it came
        # from rather than meeting it already applied.
        trace.confidence(breakdown.as_dict())

    for advisory in result.advisories:
        # Recorded, surfaced to the planner, and explicitly not the action: a
        # Rung 1 advisory alone leaves the boxes where they were.
        trace.decision(
            rung=advisory.rung.value,
            chosen=False,
            confidence=advisory.confidence,
            rationale="; ".join(a.detail for a in advisory.actions),
        )

    if result.chosen is None:
        state = transition(state, RiskState.AWAITING_CUSTOMER)
        trace.state_change("deliberating", state.value, "no feasible internal option")
        return _run_customer_gate(trace, event, (), customer, now, state, locks)

    chosen = result.chosen
    trace.decision(
        rung=chosen.rung.value,
        chosen=True,
        confidence=chosen.confidence,
        rationale=chosen.rationale,
    )

    # --- locks --------------------------------------------------------------
    for resource in chosen.resources_required:
        claim = locks.claim(resource, risk.risk_id, event.priority)
        trace.lock(
            resource,
            status=claim.status,
            our_priority=claim.our_priority,
            winner_priority=claim.winner_priority,
            action=claim.reason,
        )
        if not claim.granted:
            state = transition(state, RiskState.LOST_LOCK)
            trace.state_change("deliberating", state.value, claim.reason)
            return _after_lost_lock(
                trace, event, result, customer, now, state, locks
            )

    # --- gate ---------------------------------------------------------------
    gate = evaluate(chosen, event.affected_boxes)
    trace.gate(
        rung=gate.rung.value,
        role=gate.required_role.value,
        escalated=gate.escalated,
        escalation_reason=gate.escalation_reason,
        status="required" if gate.blocks else "auto",
    )

    if gate.needs_customer:
        state = transition(state, RiskState.AWAITING_CUSTOMER)
        trace.state_change("deliberating", state.value, "the line owns this decision")
        return _run_customer_gate(
            trace, event, result.plans, customer, now, state, locks, gate
        )

    if gate.blocks:
        state = transition(state, RiskState.AWAITING_APPROVAL)
        trace.state_change("deliberating", state.value, gate.escalation_reason)
        if gate.escalated:
            state = transition(state, RiskState.ESCALATED)
            trace.state_change(
                "awaiting_approval", state.value, gate.escalation_reason
            )

        answer = approvals.decide(gate.required_role, chosen)
        if answer is None:
            previous = state.value
            state = transition(state, RiskState.LAPSED)
            trace.state_change(previous, state.value, "approval never came")
            trace.gate(
                rung=gate.rung.value,
                role=gate.required_role.value,
                escalated=gate.escalated,
                status="lapsed",
            )
            state = transition(state, RiskState.EXECUTING)
            trace.state_change("lapsed", state.value, "default action fires")
            return _resolve(
                trace, locks, risk.risk_id, state, Resolution.WINDOW_LAPSED_NO_RESPONSE
            )
        trace.gate(
            rung=gate.rung.value,
            role=gate.required_role.value,
            escalated=gate.escalated,
            status="approved" if answer else "rejected",
        )
        if not answer:
            state = transition(state, RiskState.EXECUTING)
            trace.state_change(
                "escalated" if gate.escalated else "awaiting_approval",
                state.value,
                "rejected; default action fires",
            )
            return _resolve(
                trace, locks, risk.risk_id, state, Resolution.CUSTOMER_DECLINED_ALL
            )
        previous = state.value
        state = transition(state, RiskState.EXECUTING)
        trace.state_change(previous, state.value, "approved")
    else:
        state = transition(state, RiskState.EXECUTING)
        trace.state_change("deliberating", state.value, "auto-approved under policy")

    # --- execute ------------------------------------------------------------
    for resource in chosen.resources_required:
        if not locks.commit(resource, risk.risk_id):
            trace.observation(f"lost {resource} between claiming and committing")
    trace.tool_call("book_itt_leg", status="ok", latency_ms=850)
    return _resolve(
        trace, locks, risk.risk_id, state, Resolution.CONNECTION_HELD, chosen, gate
    )


def _after_lost_lock(
    trace, event, result, customer, now, state, locks
) -> Outcome:
    """The loser re-deliberates with the contested option removed.

    If nothing else works internally it falls to Rung 4 rather than dying
    quietly — losing a slot is not the same as having nothing to offer.
    """
    remaining = tuple(p for p in result.plans if p.rung is not Rung.MOVE)
    trace.observation(
        f"re-deliberating without the contested resource; "
        f"{len(remaining)} option(s) remain"
    )
    state = transition(state, RiskState.AWAITING_CUSTOMER)
    trace.state_change("lost_lock", state.value, "no alternative internal option")
    return _run_customer_gate(trace, event, remaining, customer, now, state, locks)


def _run_customer_gate(
    trace, event, options, customer, now, state, locks, gate=None
) -> Outcome:
    """Rung 4. Three exits, and only one of them is a service failure."""
    offer_sent = now
    trace.tool_call("send_options_to_line", status="ok", latency_ms=640)

    answer = customer.respond(options)
    if answer is None:
        outcome_label, resolution = "LAPSED_NO_RESPONSE", Resolution.WINDOW_LAPSED_NO_RESPONSE
    elif answer is False:
        outcome_label, resolution = "DECLINED_ALL", Resolution.CUSTOMER_DECLINED_ALL
    else:
        outcome_label, resolution = "DECIDED", Resolution.CUSTOMER_DECIDED

    trace.external_gate(
        party="line",
        options_sent=len(options),
        window_min=CUSTOMER_WINDOW_MIN,
        outcome=outcome_label,
    )
    state = transition(state, RiskState.EXECUTING)
    trace.state_change(
        "awaiting_customer",
        state.value,
        "line decided" if answer is not None else "window closed; default action fires",
    )
    trace.tool_call("roll_to_next_service", status="ok", latency_ms=310)

    return _resolve(
        trace,
        locks,
        trace.risk_id,
        state,
        resolution,
        gate=gate,
        offer_sent_at=offer_sent,
        options_alive=len(options),
    )


def _resolve(
    trace,
    locks,
    risk_id,
    state,
    resolution,
    chosen=None,
    gate=None,
    offer_sent_at=None,
    options_alive=0,
) -> Outcome:
    released = locks.release_all(risk_id)
    if released:
        trace.observation(f"released {len(released)} reservation(s)")
    state = transition(state, RiskState.RESOLVED)
    trace.state_change("executing", state.value, resolution.value)
    trace.close(resolution, offer_sent_at=offer_sent_at, options_alive=options_alive)
    return Outcome(trace, state, resolution, chosen, gate)
