"""The disruption scenario suite.

Thirty cases with known-correct outcomes, including — deliberately — cases
where escalating is right and acting is wrong. A suite whose answer is always
"act" tests nothing except that the agent is willing to act.

**The suite measures two different things depending on which model runs it,
and conflating them would make the reported number meaningless.**

    PolicyModel   Always takes the top-ranked candidate. Removes judgement
                  entirely, so what is under test is the rails: viability
                  filtering, gate policy, lock arbitration, state legality,
                  degradation under tool failure. Fully deterministic, runs
                  in CI, and a failure here is a bug.

    local/hosted  Real judgement. What is under test is whether the model
                  picks well among options the rails already validated. A
                  failure here is a prompt problem, not a bug.

Report them separately. "28/30" means nothing without saying which.
"""

from dataclasses import dataclass, field
from typing import Any

from latch.events import RiskEvent
from latch.llm import ModelResponse
from latch.models import ApprovalRole, Resolution, Rung
from latch.state import RiskState
from latch.tools import ScriptedFailures, ToolStatus


class PolicyModel:
    """A deterministic stand-in that always takes the top-ranked candidate.

    Reads the candidate list out of the prompt rather than being handed the
    plan ids, so it exercises the same path a real model does — including the
    guard that rejects a chosen id which is not on the list.
    """

    def __init__(self, triage_keeps: bool = True) -> None:
        self.triage_keeps = triage_keeps
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
            data: dict[str, Any] = {
                "worth_deliberating": self.triage_keeps,
                "reason": "policy baseline: defer to the deterministic rails",
            }
        else:
            candidates = [
                line.strip().split()[0]
                for line in prompt.splitlines()
                if line.startswith("  ") and "[rung_" in line
            ]
            data = {
                "chosen_plan_id": candidates[0] if candidates else "",
                "ranking": candidates,
                "rationale": "policy baseline: top-ranked candidate",
            }

        return ModelResponse(
            data=data,
            # Deliberately not the model name it stands in for: a trace must
            # never claim a model call that did not happen.
            model="policy-baseline",
            input_tokens=len(system + prompt) // 4,
            output_tokens=len(str(data)) // 4,
        )


@dataclass(frozen=True, slots=True)
class Expectation:
    """What a scenario asserts. Every field is optional.

    Scenarios assert only what they are actually testing — over-specifying
    turns an unrelated change into thirty red tests and trains people to
    update expectations without reading them.
    """

    resolution: Resolution | None = None
    rung: Rung | None = None
    escalated: bool | None = None
    role: ApprovalRole | None = None
    state: RiskState | None = None
    reached_customer: bool | None = None
    used_model: bool | None = None
    min_excluded: int | None = None


@dataclass(frozen=True, slots=True)
class Scenario:
    scenario_id: str
    family: str
    description: str
    payload: dict[str, Any]
    expect: Expectation
    why_it_matters: str
    failures: dict[str, list[ToolStatus]] = field(default_factory=dict)
    approvals: str = "auto"
    customer: str = "silent"
    itt_cache_age_min: float | None = None

    @property
    def event(self) -> RiskEvent:
        return RiskEvent.from_dict(self.payload)

    def failure_plan(self) -> ScriptedFailures | None:
        return ScriptedFailures(self.failures) if self.failures else None


@dataclass(frozen=True, slots=True)
class Check:
    field_name: str
    expected: Any
    actual: Any

    @property
    def passed(self) -> bool:
        return self.expected == self.actual


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    scenario: Scenario
    checks: tuple[Check, ...]
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.error is None and all(c.passed for c in self.checks)

    @property
    def failures(self) -> tuple[Check, ...]:
        return tuple(c for c in self.checks if not c.passed)

    def summary(self) -> str:
        if self.error:
            return f"ERROR {self.error}"
        if self.passed:
            return "ok"
        return "; ".join(
            f"{c.field_name}: expected {c.expected!r}, got {c.actual!r}"
            for c in self.failures
        )


# --- running ----------------------------------------------------------------


def _effective_rung(trace) -> Rung | None:
    """What rung did this actually end at?

    An external gate means Rung 4 regardless of what was deliberated, because
    reaching the line *is* the outcome. Otherwise take the last recorded
    decision.
    """
    if any(s.type == "external_gate" for s in trace.steps):
        return Rung.OFFER
    decisions = [s for s in trace.steps if s.type == "decision"]
    if not decisions:
        return None
    return Rung(decisions[-1].payload["rung"])


def _actuals(outcome, trace) -> dict[str, Any]:
    return {
        "resolution": outcome.resolution,
        "state": outcome.state,
        "rung": _effective_rung(trace),
        "escalated": outcome.gate.escalated if outcome.gate else False,
        "role": outcome.gate.required_role if outcome.gate else None,
        "reached_customer": any(s.type == "external_gate" for s in trace.steps),
        "used_model": any(
            s.type == "model_call" and s.payload.get("purpose") == "triage"
            for s in trace.steps
        ),
        "min_excluded": sum(
            1 for s in trace.steps
            if s.type == "observation" and s.payload.get("considered")
        ),
    }


def run_scenario(scenario: Scenario, client: Any) -> ScenarioResult:
    """Run one scenario and check only what it claims to test."""
    from latch.runner import (
        AutoApprove,
        CustomerAccepts,
        CustomerDeclinesAll,
        CustomerSilent,
        NeverApproves,
        handle,
    )
    from latch.locks import LockTable
    from latch.tools import CacheEntry
    from latch.trace import TraceStore

    approvals = {"auto": AutoApprove, "never": NeverApproves}[scenario.approvals]()
    customer = {
        "silent": CustomerSilent,
        "accepts": CustomerAccepts,
        "declines": CustomerDeclinesAll,
    }[scenario.customer]()

    cache = (
        CacheEntry(value=[], age_min=scenario.itt_cache_age_min)
        if scenario.itt_cache_age_min is not None
        else None
    )

    try:
        outcome = handle(
            scenario.event,
            client=client,
            store=TraceStore(),
            locks=LockTable(),
            failures=scenario.failure_plan(),
            itt_cache=cache,
            approvals=approvals,
            customer=customer,
        )
    except Exception as exc:  # a scenario that crashes is a failing scenario
        return ScenarioResult(scenario, (), error=f"{type(exc).__name__}: {exc}")

    actual = _actuals(outcome, outcome.trace)
    checks: list[Check] = []
    for name in (
        "resolution", "rung", "escalated", "role", "state",
        "reached_customer", "used_model",
    ):
        expected = getattr(scenario.expect, name)
        if expected is not None:
            checks.append(Check(name, expected, actual[name]))

    if scenario.expect.min_excluded is not None:
        checks.append(
            Check(
                "min_excluded",
                True,
                actual["min_excluded"] >= scenario.expect.min_excluded,
            )
        )

    return ScenarioResult(scenario, tuple(checks))


@dataclass(frozen=True, slots=True)
class SuiteReport:
    results: tuple[ScenarioResult, ...]
    model_label: str

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def accuracy(self) -> float:
        return self.passed / self.total if self.total else 0.0

    def misses(self) -> tuple[ScenarioResult, ...]:
        return tuple(r for r in self.results if not r.passed)

    def by_family(self) -> dict[str, tuple[int, int]]:
        tally: dict[str, list[int]] = {}
        for result in self.results:
            entry = tally.setdefault(result.scenario.family, [0, 0])
            entry[1] += 1
            if result.passed:
                entry[0] += 1
        return {k: (v[0], v[1]) for k, v in tally.items()}

    def render(self) -> str:
        lines = [
            f"{self.passed}/{self.total} ({self.accuracy:.0%}) on {self.model_label}",
            "",
        ]
        for family, (ok, total) in sorted(self.by_family().items()):
            flag = "" if ok == total else "  <-"
            lines.append(f"  {family:22} {ok:2}/{total:<2}{flag}")

        misses = self.misses()
        if misses:
            lines += ["", f"misses ({len(misses)}):"]
            for result in misses:
                lines.append(f"  {result.scenario.scenario_id}  {result.scenario.description}")
                lines.append(f"      {result.summary()}")
                lines.append(f"      why it matters: {result.scenario.why_it_matters}")
        else:
            lines += ["", "no misses"]
        return "\n".join(lines)


def run_suite(client: Any, model_label: str, suite=None) -> SuiteReport:
    from latch.scenario_suite import SUITE

    scenarios = suite if suite is not None else SUITE
    return SuiteReport(
        tuple(run_scenario(s, client) for s in scenarios), model_label
    )
