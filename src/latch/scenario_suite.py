"""The thirty scenarios.

Data, not logic. Each carries `why_it_matters` because a scenario whose point
nobody remembers gets its expectation "fixed" the first time it goes red.
"""

from latch.models import ApprovalRole, Resolution, Rung
from latch.scenarios import Expectation, Scenario
from latch.state import RiskState
from latch.tools import ToolStatus


def payload(
    cid: str,
    *,
    state: str = "AT_RISK",
    slack: float = -1.8,
    no_itt: float = 2.4,
    avoidable: bool = True,
    boxes: int = 84,
    confidence: str = "MEDIUM",
    codes: tuple[str, ...] = ("INBOUND_ETA_SLIP", "INTER_TERMINAL_TRANSFER_TIME"),
) -> dict:
    return {
        "connection_id": cid,
        "state": state,
        "current_plan_slack_hours": slack,
        "no_itt_slack_hours": no_itt,
        "avoidable_by_terminal_prevention": avoidable,
        "affected_boxes": boxes,
        "confidence": confidence,
        "reason_codes": list(codes),
    }


SUITE: tuple[Scenario, ...] = (
    # --- triage: most events are not risks -------------------------------
    Scenario(
        "T-01", "triage", "SAFE with a wide window",
        payload("T-01", state="SAFE", slack=9.6, no_itt=13.8, boxes=12),
        Expectation(
            resolution=Resolution.DISMISSED_NO_ACTION,
            state=RiskState.DISMISSED,
            used_model=False,
        ),
        "A SAFE event must cost nothing. If it reaches a model the funnel is "
        "not a funnel.",
    ),
    Scenario(
        "T-02", "triage", "Large delay, ample slack",
        payload("T-02", state="SAFE", slack=7.2, no_itt=11.0, boxes=40),
        Expectation(resolution=Resolution.DISMISSED_NO_ACTION, used_model=False),
        "Six hours late against thirty hours of slack is a large delay and no "
        "risk. Triggering on magnitude instead of consumed slack would fire here.",
    ),
    Scenario(
        "T-03", "triage", "Below the volume floor",
        payload("T-03", slack=-2.0, boxes=3),
        Expectation(resolution=Resolution.DISMISSED_NO_ACTION, used_model=False),
        "Three boxes past the window: any move costs more than the miss. "
        "Acting here would be worse than doing nothing.",
    ),
    Scenario(
        "T-04", "triage", "Already blown, large volume",
        payload("T-04", slack=-1.8, boxes=84),
        Expectation(used_model=False),
        "Eighty-four boxes past the window does not need a small model's "
        "opinion on whether it is serious. Free at both ends.",
    ),
    Scenario(
        "T-05", "triage", "The ambiguous middle",
        payload("T-05", state="WATCH", slack=3.1, no_itt=7.4, boxes=47),
        Expectation(used_model=True),
        "Thinning but not blown, moderate volume. The only place a judgement "
        "is actually being made, and the only place the model should be spent.",
    ),
    # --- prevention: is Rung 1 a live option ------------------------------
    Scenario(
        "P-01", "prevention", "Transfer is the whole problem",
        payload("P-01", slack=-1.8, no_itt=2.4, avoidable=True),
        Expectation(),
        "Removing the transfer would save it outright, so prevention belongs "
        "on the list.",
    ),
    Scenario(
        "P-02", "prevention", "Transfer is not the problem",
        payload("P-02", slack=-3.2, no_itt=-0.9, avoidable=False),
        Expectation(rung=Rung.OFFER),
        "Negative even without the transfer. Offering prevention here would "
        "be noise the planner learns to ignore.",
    ),
    Scenario(
        "P-03", "prevention", "Flag set but slack already positive",
        payload("P-03", state="WATCH", slack=2.0, no_itt=6.0, avoidable=True),
        Expectation(),
        "The flag says avoidable but nothing needs avoiding. Trusting the flag "
        "over the arithmetic would raise a pointless advisory.",
    ),
    # --- internal fix: Rung 3 -------------------------------------------
    Scenario(
        "M-01", "internal_fix", "Wide window, both modes viable",
        payload("M-01", state="WATCH", slack=-0.5, no_itt=9.0, boxes=30),
        Expectation(rung=Rung.MOVE, resolution=Resolution.CONNECTION_HELD),
        "Enough time for either mode. A real choice between cost, emissions "
        "and speed rather than a forced hand.",
    ),
    Scenario(
        "M-02", "internal_fix", "Only road arrives in time",
        payload("M-02", slack=-1.8, no_itt=2.4, boxes=84),
        Expectation(rung=Rung.MOVE, min_excluded=1),
        "Barge is cheaper and cleaner and arrives after the cutoff. The "
        "exclusion has to appear in the trace or the agent looks like it never "
        "considered it.",
    ),
    Scenario(
        "M-03", "internal_fix", "Small volume, high confidence",
        payload("M-03", slack=-0.5, no_itt=6.0, boxes=15, confidence="HIGH"),
        Expectation(
            rung=Rung.MOVE, escalated=False, role=ApprovalRole.AUTO
        ),
        "Everything is clean and small. If this needs a signature the gate is "
        "too tight and people will start rubber-stamping.",
    ),
    Scenario(
        "M-04", "internal_fix", "Same shape, large volume",
        payload("M-04", slack=-0.5, no_itt=6.0, boxes=84, confidence="HIGH"),
        Expectation(rung=Rung.MOVE, escalated=True, role=ApprovalRole.VESSEL_OPS),
        "Only the volume changed. Acting alone here is wrong — eighty-four "
        "boxes is a person's decision.",
    ),
    Scenario(
        "M-05", "internal_fix", "Barely viable window",
        payload("M-05", slack=-0.2, no_itt=1.1, boxes=25),
        Expectation(rung=Rung.MOVE),
        "Sixty-six minutes against a fifty-five minute road transit. Tight, "
        "but real — an off-by-one in the viability check shows up here.",
    ),
    # --- nothing works internally: Rung 4 --------------------------------
    Scenario(
        "O-01", "no_internal_option", "Negative even without the transfer",
        payload("O-01", slack=-3.2, no_itt=-0.9, avoidable=False, boxes=61),
        Expectation(rung=Rung.OFFER, reached_customer=True),
        "Nothing internal can fix it. Escalating is right and acting is wrong.",
    ),
    Scenario(
        "O-02", "no_internal_option", "Window shorter than any transit",
        payload("O-02", slack=-0.5, no_itt=0.5, boxes=40),
        Expectation(rung=Rung.OFFER, reached_customer=True),
        "Thirty minutes against a fifty-five minute minimum. Fabricating an "
        "internal fix here would be the worst possible failure.",
    ),
    Scenario(
        "O-03", "no_internal_option", "Large volume, no option",
        payload("O-03", slack=-4.0, no_itt=-2.0, avoidable=False, boxes=120),
        Expectation(rung=Rung.OFFER, role=ApprovalRole.DUTY_MANAGER),
        "A hundred and twenty boxes with nothing to offer internally still "
        "needs senior sign-off before going to the customer.",
    ),
    Scenario(
        "O-04", "no_internal_option", "Low watcher confidence, no option",
        payload(
            "O-04", slack=-3.0, no_itt=-1.0, avoidable=False,
            boxes=30, confidence="LOW",
        ),
        Expectation(rung=Rung.OFFER),
        "A LOW from the Watcher must reach the gate rather than being "
        "discarded at the boundary.",
    ),
    # --- gate policy: where escalating is right ---------------------------
    Scenario(
        "G-01", "gate_policy", "Low watcher confidence tightens the gate",
        payload("G-01", slack=-0.5, no_itt=6.0, boxes=20, confidence="LOW"),
        Expectation(escalated=True),
        "Same volume and cost as an auto-approved case; only the Watcher's own "
        "certainty differs. If this auto-approves, A's confidence is decorative.",
    ),
    Scenario(
        "G-02", "gate_policy", "High confidence, small, cheap",
        payload("G-02", slack=-0.5, no_itt=6.0, boxes=12, confidence="HIGH"),
        Expectation(escalated=False, role=ApprovalRole.AUTO),
        "The control for G-01.",
    ),
    Scenario(
        "G-03", "gate_policy", "Approval never comes",
        payload("G-03", slack=-0.5, no_itt=6.0, boxes=84),
        Expectation(
            resolution=Resolution.APPROVAL_LAPSED,
            state=RiskState.RESOLVED,
        ),
        "Nobody signs. Doing nothing is also a decision and must be traced as "
        "one rather than leaving the risk open forever. Specifically an "
        "internal one: the line was never asked, so this is not a lapsed "
        "customer window and must not be reported as one.",
        approvals="never",
    ),
    Scenario(
        "G-04", "gate_policy", "Rung 1 never blocks",
        payload("G-04", state="WATCH", slack=1.0, no_itt=8.0, boxes=200,
                confidence="LOW"),
        Expectation(),
        "Enormous volume and the worst possible confidence. An advisory still "
        "must not require a signature — escalating it would train people to "
        "ignore the gate.",
    ),
    Scenario(
        "G-05", "gate_policy", "Volume and confidence compound",
        payload("G-05", slack=-0.5, no_itt=6.0, boxes=90, confidence="LOW"),
        Expectation(escalated=True, role=ApprovalRole.DUTY_MANAGER),
        "Two independent reasons to escalate should reach further up the "
        "ladder than either alone.",
    ),
    Scenario(
        "G-06", "gate_policy", "Customer gate cannot be escalated past",
        payload("G-06", slack=-3.0, no_itt=-1.0, avoidable=False, boxes=25),
        Expectation(reached_customer=True),
        "No level of internal seniority can decide for the line. The gate has "
        "to leave the building.",
    ),
    # --- degradation under failure ---------------------------------------
    Scenario(
        "D-01", "degradation", "Slot query times out, cache saves it",
        payload("D-01", slack=-0.5, no_itt=6.0, boxes=20, confidence="HIGH"),
        Expectation(escalated=True),
        "The §7.1 baseline. Nobody lowers the confidence — it falls out of the "
        "cache read, and the gate tightens on its own.",
        failures={"query_itt_slot": [ToolStatus.TIMEOUT, ToolStatus.TIMEOUT]},
        itt_cache_age_min=8.0,
    ),
    Scenario(
        "D-02", "degradation", "Slot query fails with no cache",
        payload("D-02", slack=-0.5, no_itt=6.0, boxes=20),
        Expectation(rung=Rung.OFFER),
        "No inventory and nothing stale to fall back on. Proceeding on an "
        "assumed default would be inventing capacity.",
        failures={"query_itt_slot": [ToolStatus.ERROR, ToolStatus.ERROR]},
    ),
    Scenario(
        "D-03", "degradation", "Both read tools fail",
        payload("D-03", slack=-2.0, no_itt=1.0, boxes=30),
        Expectation(reached_customer=True),
        "Total blindness. The agent has nothing to offer and has to say so "
        "rather than crash or guess.",
        failures={
            "query_itt_slot": [ToolStatus.ERROR, ToolStatus.ERROR],
            "query_outbound_services": [ToolStatus.ERROR, ToolStatus.ERROR],
        },
    ),
    Scenario(
        "D-04", "degradation", "Retry succeeds on the second attempt",
        payload("D-04", slack=-0.5, no_itt=6.0, boxes=20, confidence="HIGH"),
        Expectation(rung=Rung.MOVE),
        "A single transient timeout should not change the outcome, only the "
        "confidence. Over-reacting to one blip would make the system useless.",
        failures={"query_itt_slot": [ToolStatus.TIMEOUT]},
    ),
    # --- the customer gate: three exits, one failure ----------------------
    Scenario(
        "C-01", "customer_gate", "Line chooses in time",
        payload("C-01", slack=-3.0, no_itt=-1.0, avoidable=False, boxes=30),
        Expectation(resolution=Resolution.CUSTOMER_DECIDED),
        "Served.",
        customer="accepts",
    ),
    Scenario(
        "C-02", "customer_gate", "Line declines everything",
        payload("C-02", slack=-3.0, no_itt=-1.0, avoidable=False, boxes=30),
        Expectation(resolution=Resolution.CUSTOMER_DECLINED_ALL),
        "The box still rolls, and this is still a success. Scoring it as a "
        "failure would punish the system for the customer's own decision.",
        customer="declines",
    ),
    Scenario(
        "C-03", "customer_gate", "Nobody answers",
        payload("C-03", slack=-3.0, no_itt=-1.0, avoidable=False, boxes=30),
        Expectation(resolution=Resolution.WINDOW_LAPSED_NO_RESPONSE),
        "The only one of the three that is a service failure. If C-02 and C-03 "
        "score the same, the product has no thesis.",
        customer="silent",
    ),
)

assert len({s.scenario_id for s in SUITE}) == len(SUITE), "duplicate scenario id"
