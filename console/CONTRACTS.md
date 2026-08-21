# CONTRACTS — where the real shapes differ from the sketch

**Workstream C.** Written before any UI code, from A's and B's source as it
actually is on `feat/c-console-confidence` (base: local `main` @ `b1f620b`,
whose tree matches `origin/main` @ `347f89c`).

Types transcribed to [`console/src/contracts/latch.ts`](src/contracts/latch.ts).
Every claim below cites the file and line it came from. Nothing here is
inferred from naming.

The provisional sketch we agreed earlier was:

```
{ connection_id, state, current_plan_slack_hours, no_itt_slack_hours,
  avoidable_by_terminal_prevention, affected_boxes, confidence,
  reason_codes[] }
```

**Headline: the sketch is exact — but it describes only one of the five shapes
the console consumes, and it is the shape furthest from the screen.** It is
`RiskEvent.to_dict()` (`src/latch/events.py:264`), the A→B wire format. Every
field matches, including the `confidence` key name. Nothing needs to change
there.

The divergences are all downstream of it, in the shapes the console actually
renders: B's internal risk model, B's plans, the trace, and B's own console
view model. Those are covered below.

---

## 1. The five shapes the console consumes

| # | Shape | Emitter | Serialised? | Fixture |
|---|---|---|---|---|
| 1 | `RiskEvent` | A → B wire, `events.py:264` | yes | `fixtures/mock_events.json` |
| 2 | `ConnectionRisk` | B internal, `serde.py:risk_to_dict` | yes | `fixtures/risks.json` |
| 3 | `Plan` (ranked options) | `deliberation.py` | **no serialiser exists** | — |
| 4 | `Trace` | `trace.py:Trace.as_dict` | yes | `fixtures/traces.json` |
| 5 | `case_view` | `console.py:179` | yes | `fixtures/console_views.json` |

Shape 5 is B's own C-facing seam and is the primary source for the console.
Shape 4 is the fallback for everything shape 5 drops. Shape 3 does not reach
the console at all — see §6.

---

## 2. Rung 2 does not exist

The brief describes a four-rung ladder: PREVENT / ABSORB / MOVE / ACCEPT.

`models.py:64-74` has **three** rungs:

```python
class Rung(StrEnum):
    INFORM = "rung_1_inform"   # berth planner decides
    MOVE   = "rung_3_move"     # vessel ops decides
    OFFER  = "rung_4_offer"    # the shipping line decides
```

with the comment: *"Rung 2 (absorb / resequence discharge) was cut: it needs a
stowage and crane model we would get wrong. The gap in the numbering is
intentional and should stay visible."*

`AMEND_DISCHARGE_ORDER` survives in `ActionKind` (`models.py:96`) but nothing
constructs a plan that uses it.

Rung 4 is also not "ACCEPT / damage control". It is **OFFER**: ranked options
go to the shipping line, and the line decides. The three exits
(`models.py:Resolution`) are `CUSTOMER_DECIDED`, `CUSTOMER_DECLINED_ALL`,
`WINDOW_LAPSED_NO_RESPONSE`, and only the last is treated as a service failure
(`Resolution.is_service_success`).

**Console impact.** The ladder renders three rungs with a visible gap where
rung 2 would be, labelled as cut and why. Rung 4 is labelled OFFER, not
ACCEPT. Rendering four rungs, or calling rung 4 "accept", would misdescribe
the system on screen.

---

## 3. Rung 1 is advisory but *not* the "least autonomous" rung

The governing principle in the brief is "autonomy is inversely proportional to
value", with rung 1 the most valuable and least autonomous.

The Gate Controller (`gates.py:37`) implements something more specific:

```python
LADDERS = {
    Rung.INFORM: (BERTH_PLANNER,),
    Rung.MOVE:   (AUTO, VESSEL_OPS, DUTY_MANAGER),
    Rung.OFFER:  (VESSEL_OPS, DUTY_MANAGER),
}
```

Rung 1 has a **single-entry ladder**, and `gates.py:79` skips every escalation
criterion for it — volume, cost and confidence are all ignored. `GateDecision.blocks`
returns False for rung 1 unconditionally. So rung 1 never escalates and never
blocks; it notifies a berth planner who was already going to decide.

**Console impact.** A rung 1 row must not render an approve/decline control or
a countdown. It renders as a notification with a named recipient. Showing an
approval affordance there would imply an authority the system does not claim.

---

## 4. `RiskEvent.to_dict()` drops six fields that `from_dict()` reads

`events.py:264` writes 8 keys (+2 optional). `events.py:234` reads **six more**:
`inbound_terminal`, `outbound_terminal`, `terminal_resolution`,
`inbound_vessel`, `outbound_vessel`, `source`.

The live Watcher (`watcher.py:154`) sets all six on the in-process object. They
survive `from_dict` but not `to_dict`, so a round trip through JSON loses them.
`to_dict` also never writes `assumptions`, which `from_dict` does not read
either — the assumption block only travels in-process.

**Console impact.** Terminal names, vessel names and the synthetic/real
provenance marker cannot be read from an event JSON file. They are recoverable
from the trace `trigger` block (`trace.py:Trace.for_risk`) for terminals and
`terminal_resolution`, but **vessel names are recoverable from neither**. See
REQUEST TO A/B #5.

---

## 5. Four of the six reason codes are unreachable

`events.py:ReasonCode` declares six. `watcher.py:136` emits at most two:

```python
if breakdown.eta_slip_min > ETA_SLIP_TOLERANCE_MIN:   # 15.0 min
    codes.append(ReasonCode.INBOUND_ETA_SLIP)
if connection.requires_transfer:
    codes.append(ReasonCode.INTER_TERMINAL_TRANSFER_TIME)
```

`OUTBOUND_CUTOFF_ADVANCED`, `BERTH_CONGESTION`, `YARD_CONGESTION` and
`DISCHARGE_SEQUENCE` appear only in `fixtures/mock_events.json`, which is
hand-written, not Watcher output.

**Console impact.** The console will render plain-English text for all six
(the brief asks for operator English, not enum strings), but the two the
Watcher actually emits are the only ones a live run can produce. The other four
are reachable only from hand-authored fixtures, and the console must not
present them as evidence of detection capability we have.

Also worth stating plainly: `avoidable_by_terminal_prevention` is **not** the
"removing the ITT would rescue this" flag. `watcher.py:170` sets it to
`connection.requires_transfer` — a statement that a transfer is on the critical
path, nothing more. The rescue judgement is `RiskEvent.itt_is_the_problem`
(`events.py:187`), which is derived:

```python
avoidable_by_terminal_prevention and no_itt_slack_hours > 0
                                 and current_plan_slack_hours <= 0
```

The console's "removing the ITT would rescue this" flag must use
`itt_is_the_problem`. Using the raw boolean would flag every inter-terminal
connection, including the safe ones.

---

## 6. Ranked options never reach the console — largest gap

The brief asks the connection detail panel for *"B's ranked options with rung,
cost (SGD), emissions delta (kgCO2e), rationale and confidence"*.

`Plan` (`models.py:232`) carries all of that: `rung`, `cost_sgd`,
`emissions_kg_co2e`, `rationale`, `confidence`, `actions`, `provenance`,
`resources_required`, `options_alive`.

**There is no serialiser for `Plan` anywhere in B.** `grep` for `asdict`
across `src/latch` returns only `console.py` (panel/ladder/approvals) and
`replay.py`. `runner.handle()` returns an in-process `Outcome`; the only thing
that crosses the wire is the trace.

What the trace records about a plan is `trace.decision(...)`
(`trace.py:168`) — four fields:

```python
rung, chosen, confidence, rationale
```

No `plan_id`. No `cost_sgd`. No `emissions_kg_co2e`. No `actions`. And only
for the chosen plan plus rung-1 advisories (`runner.py`), never for the
runners-up. `DeliberationResult.plans` holds the full ranking; it is discarded
when `handle()` returns.

Cost and emissions *are* computed — `deliberation.py:build_candidates`
multiplies `slot.cost_sgd` and `slot.emissions_kg_co2e` by `affected_boxes` —
and they are put in the model's prompt (`deliberation.py:_prompt`). They are
then thrown away.

**Console impact.** Until REQUEST TO B #1 lands, the options table renders
what genuinely exists: rung, rationale, confidence, and the ruled-out options
with their reasons (which *are* traced, as `observation` steps with
`considered: true`). The cost and emissions columns render an explicit
`not carried in trace` marker rather than a number. We will not recompute them
in the adapter from `ITT_COST_PER_BOX_SGD × boxes` — that would be the console
inventing a figure and attributing it to the agent.

---

## 7. There is no 15-minute approval timeout

The brief specifies a visible countdown to a 15-minute timeout with
auto-decline.

Grepping `config.py`, `gates.py` and `runner.py` for `deadline`, `expires`, or
any approval-window constant returns **nothing**. What exists:

- `CUSTOMER_WINDOW_MIN = 180` (`config.py`) — three hours, and it is the
  **external** window put to the shipping line at rung 4, not an internal
  approval timeout.
- `LOCK_TTL_SEC = 180` — lock reservation expiry, unrelated.
- `GateStep.latency_s` (`trace.py:219`) — how long an approval **took**,
  recorded after the fact. Not a deadline.

The LAPSED path is real (`runner.py`, `state.py:LAPSED`), but it fires when the
injected `ApprovalPolicy.decide()` returns `None`. There is no clock: `handle()`
takes an optional `now` and never compares it to anything.

**Console impact.** The countdown is a console-side timer, and it must be
labelled as such. It is honest as an interaction design (the operator does have
a window) but it is not reading a deadline out of B. The auto-decline
consequence the panel states up front — falls to rung 4, the line is asked —
matches `runner.py`'s actual LAPSED behaviour, so the *consequence* copy is
accurate even though the *timer* is ours. Both facts go on screen.

---

## 8. `STALE` is declared and unreachable

`state.py:26` defines `RiskState.STALE` with two inbound transitions
(`DETECTED → STALE`, `DELIBERATING → STALE`) and two outbound.

Nothing in `src/latch` ever calls `transition(..., RiskState.STALE)`.
`grep -rn "RiskState.STALE" src/latch` returns only `state.py`. The only other
`STALE` in the codebase is `QualityFlag.STALE_OBSERVATION` in A's `replay.py`,
which is a per-AIS-observation data-quality flag and a different concept.

**Console impact.** Step 4 of the brief asks the console to distinguish STALE.
The state is legal and renderable, but no live run reaches it. The STALE
fixture is therefore authored by C driving `transition()` directly, and it is
labelled in the fixture file as reachable-in-principle, not produced by a run.

---

## 9. `SUPERSEDED` is decided outside the trace

`runner.handle()` has no supersession path. The decision lives in
`cases.py:CaseRegistry.admit()`, which runs **before** `handle()` and returns
an `AdmissionDecision` naming the trace to close. No trace step is written by
the registry.

So a runner-produced trace never contains `state_change → superseded`.
`make_fixtures.py:scenario_superseded` writes that step by hand.

**Console impact.** Supersession is a relationship between two cases, and the
console needs both trace ids to render "this replaced that". `AdmissionDecision`
carries `superseded_trace_id` but is not serialised. See REQUEST TO B #4.

---

## 10. The confidence number in the shipped fixture is not reproducible from a run

`fixtures/README.md` describes `cr_0001` as "confidence drops to 0.62". The
brief says 0.61. Neither is what the pipeline produces.

`fixtures/traces.json` `cr_0001` is scripted by `make_fixtures.py`, which hands
`score()` three hand-written `Provenance` objects, two of them
`verified=False`, giving `0.85 × 0.9375 × 0.90 − 0.10 = 0.6172`.

A real run of the same scenario through `deliberate()` builds provenance from
`event.provenance()` plus one entry per `ToolResult` (`deliberation.py`). With
a `HIGH` watcher confidence and one cache fallback, exactly **one** input is
unverified, not two, so the penalty is `0.05` and the result is `0.6672`.

The gate escalation also differs. `make_fixtures.py` scripts
`vessel_ops → duty_manager` (two ladder steps). Running `gates.evaluate()` on
34 boxes with a sub-threshold confidence trips **one** criterion, giving ladder
index 1: `auto → vessel_ops`. That is the brief's "auto-approve escalates to
human approval", and the scripted fixture is not it.

**Console impact.** C's fixtures are generated by running B's real pipeline
(`runner.handle` with `ScriptedFailures` + `CacheEntry`), not by copying the
scripted ones, so every number on screen is reproducible from B's code. The
exact confidence value is whatever the run produces and is not tuned toward
0.61. This is written up in `console/fixtures/README.md` with the command.

---

## 11. What `case_view()` drops relative to the raw trace

`console.py:179` is B's C-facing seam and is the right primary source, but it
omits several things the brief asks for. All are present in the raw trace:

| Needed by | Missing from `case_view` | Present in trace as |
|---|---|---|
| Trace timeline (step 2.4) | every step | `steps[]` |
| Tool latency + status | — | `tool_call` steps |
| Errors, retries, recovery | — | `error` steps |
| Per-decision token cost | only the roll-up `cost` | `model_call` steps, one `usd` each |
| Lock contention | — | `lock` steps |
| State machine history | — | `state_change` steps |
| Reason codes | — | first `observation` step payload |
| Assumption block | — | second `observation` step payload |

`ladder_view()` (`console.py:121`) also mislabels rung-1 advisories: it sets
`status="advisory"` only via `"chosen" if chosen else "advisory"`, so any
non-chosen `decision` step becomes "advisory" regardless of rung. In practice
only rung-1 advisories are traced with `chosen=False`, so it is correct today
by coincidence rather than by construction.

**Console impact.** The adapter reads `case_view` for the summary/confidence/
approvals and the raw trace for the timeline. Both come from the same fixture
generation run, so they cannot disagree.

---

## 12. Smaller divergences, recorded so they are not rediscovered

1. **`TraceStep.as_dict()` spreads the payload flat** (`trace.py`), so a step is
   `{seq, type, at, ...payload}`, not `{seq, type, at, payload}`. The
   discriminant is `type`.
2. **The `gate` recorder renames its parameter**: `trace.gate(role=...)` writes
   the key `required_role`.
3. **Trace timestamps are wall-clock at record time**, taken from
   `datetime.now(UTC)` inside `_append`. They are *not* scenario time. In
   `fixtures/traces.json` all nineteen steps of `cr_0001` share the same
   millisecond. The console must order by `seq` and must not render `at` as
   elapsed scenario time. Latency comes from `tool_call.latency_ms`.
4. **`decision_lead_time_h` is null unless an offer was sent** — `close()` only
   sets `offer_sent_at` on the rung-4 path.
5. **`options_alive_at_send` is 0 for every non-rung-4 case**, not "unknown".
6. **`Plan.confidence` and `RiskEvent.watcher_confidence` are different
   quantities** and `events.py:12-18` says so explicitly. A HIGH from the Watcher
   cannot make a plan built on stale cache trustworthy. Two different widgets.
7. **`ConfidencePanel.headline` and `.crosses_threshold` are Python properties**,
   so `asdict()` does not include them — but `case_view` adds `confidence_headline`
   separately. `crosses_threshold` is not serialised; the console recomputes it
   as `value < threshold`, both of which are in the payload.
8. **`WaterfallStep.cost`** is likewise a property and absent from the JSON.

---

## REQUEST TO A/B

Ordered by how much the console loses without them.

### REQUEST TO B #1 — serialise the ranked options *(blocking for step 2.2)*

The detail panel cannot show cost or emissions for any option, and cannot show
the runners-up at all. Everything needed already exists on `Plan`; it just has
no encoder.

Asking for: a `plan_to_dict(plan)` in `serde.py`, and either
(a) a new trace step `options` carrying the ranked list once per deliberation,
or (b) extra keys on the existing `decision` step: `plan_id`, `cost_sgd`,
`emissions_kg_co2e`, `actions`, `rank`.

(a) is preferable — it keeps the runners-up, which is what makes the ranking
legible as a ranking rather than an assertion.

Until then the console renders `cost` and `emissions` as
`not carried in trace`. It will not recompute them.

### REQUEST TO B #2 — an approval deadline on the gate step

`GateStep` has `latency_s` (elapsed, after the fact) but no deadline. The
console's countdown is currently its own timer.

Asking for: `expires_at` (ISO-8601) and `window_min` on the `gate` step when
`status` is `required` or `pending`, plus a policy constant for the internal
approval window in `config.py` — the way `CUSTOMER_WINDOW_MIN` already exists
for the external one. Then the LAPSED transition can fire from a clock instead
of from an injected `None`, and the countdown reads a real deadline.

### REQUEST TO A #3 — emit `SlackBreakdown` on the event

`watcher.py:65` builds exactly the numbers the connection detail panel wants —
`cargo_ready`, `outbound_cutoff`, `transfer_h`, `eta_slip_min`, and both slack
figures — with the comment *"the arithmetic, kept so the console can show its
working"*. `to_risk_event` then discards it.

Asking for: a `slack_breakdown` block on `RiskEvent.to_dict()`. Without it the
console can show the two slack figures but not the arithmetic that produced
them, which is the difference between a number and a checkable number.

### REQUEST TO B #4 — trace the supersession link

Asking for: a `superseded_by` / `supersedes` field on `Trace.as_dict()`'s
`outcome` block, or a `state_change` step written into the *old* trace when
`CaseRegistry` closes it. Today the relationship exists only in
`AdmissionDecision`, which is never serialised, so the console can show a case
is superseded but not what replaced it.

### REQUEST TO A/B #5 — vessel names and call timing on the wire

`ConnectionRiskWire` (`serde.py`) has full `VesselCallWire` records with
`scheduled` / `estimated` for both legs. The trace does not — `trigger` has
terminals and `eta_deviation_min` and nothing else.

The runner never emits `ConnectionRiskWire`, so a live console consuming traces
has no vessel names and no inbound/outbound timing.

Asking for: either `handle()` also emits the `risk_to_dict()` payload alongside
the trace, or `Trace.trigger` gains `inbound_vessel`, `outbound_vessel`,
`inbound_estimated`, `outbound_scheduled`.

Also for A: `RiskEvent.to_dict()` should write the six enrichment keys its own
`from_dict()` already reads (§4). That is a one-line-per-key change and makes
the wire format round-trip.

### REQUEST TO B #6 — reach `STALE`, or delete it

`RiskState.STALE` is unreachable (§8). The brief asks the console to render it
and B's docstring says gates tighten there. Either `handle()` should enter it
when upstream data is missing, or the state should come out of the machine so
the console is not rendering a state that cannot occur.

Low priority for the demo; high priority for not shipping a diagram that
claims a behaviour we do not have.

---

## What the console will *not* do

Stated up front so it does not have to be re-argued in review:

- No derived field is invented in a component. The adapter
  (`src/adapters/toViewModel.ts`) is the only module that touches these shapes,
  and anything it cannot source is rendered as an explicit gap marker, not as a
  blank and not as a plausible default.
- No performance figure is asserted. Detection rate and connections-rescued
  render as visible `PLACEHOLDER` — A's evaluation has not run.
- Anywhere the UI describes its own data it says: **real vessel movement data +
  derived arrival estimates + synthetic transhipment connections.** The
  `terminal_resolution: simulated` marker that A stamps on every live event
  (`watcher.py:191`) is surfaced, not hidden.
