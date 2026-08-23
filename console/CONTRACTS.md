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

**Status of the nine requests.** Three have landed and are consumed: #1
(`6be7bb4`), then #7 and #9 together in `99a47b8`. The remaining six are open,
and the console builds against them as gaps rather than waiting: option cost
was the only one that blocked a panel.

#9 landing changed the console rather than just unblocking it. The workaround
described below — inferring "the line was never asked" from the absence of an
`external_gate` step, and captioning B's own metric with a caveat — is gone.
B records `reached_the_line` and the adapter reads it. The internal copy the
console had written under guessed keys now hangs off B's real resolutions,
`internally_declined` and `approval_lapsed`, and the outcome badge states what
happened instead of hedging about what B counts.

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

## 4a. `assumptions` survives neither direction, so `connection_type` is wrong on the wire

Found while generating C's fixtures, not by reading — the first trace
observation said `SAME_TERMINAL` for a Tuas to Pasir Panjang connection.

`Assumptions` (`events.py:57`) defaults every flag to synthetic and
`connection_type` to `SAME_TERMINAL`. `RiskEvent.to_dict()` never writes the
block and `from_dict()` never reads it, so **every event reconstructed from
JSON claims `SAME_TERMINAL` regardless of its terminals.**

This is not only C's problem. `runner.handle()` writes the value into the
first observation step of every trace:

```python
trace.observation(..., connection_type=assumptions.connection_type.value, ...)
```

and `cli.py` builds its events with `RiskEvent.from_dict`. So B's own
`uv run latch --events path/to.json` path writes a wrong `connection_type`
into the audit trail for every inter-terminal connection it processes. The
in-process path from `watcher.events_from_signals` is correct; only the JSON
path is affected.

**Console impact.** C's capture harness reattaches the assumptions the live
Watcher would have set (`replace(decoded, assumptions=...)`), mirroring
`watcher.py:154`, so no fixture contradicts itself on screen. That is a
workaround in C's generator, not a fix. See REQUEST TO A/B #7.

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

## 6. Ranked options — **LANDED**, was the largest gap

*Raised as REQUEST TO B #1. Closed by B in `6be7bb4`, "Serialise the options
the agent compared, with what each would cost".*

**What the gap was.** `Plan` (`models.py:232`) carried `cost_sgd`,
`emissions_kg_co2e`, `actions` and `provenance`, and B had no serialiser for
it. `trace.decision(...)` recorded four fields — rung, chosen, confidence,
rationale — for the chosen plan only. Cost and emissions were computed in
`build_candidates`, formatted into the model's prompt, and discarded. The
runners-up never left the process.

**What B added.** A new `options` trace step carrying every candidate:

```json
{ "type": "options", "candidates": [
  { "option_id": "...-r3-tuapas_1120", "rung": "rung_3_move",
    "detail": "barge, departs 05:37, 190m transit",
    "cost_sgd": 1054.0, "emissions_kg_co2e": 139.4, "chosen": true }, ... ] }
```

plus `cost_sgd` / `emissions_kg_co2e` on the `decision` step, and
`action_cost_sgd` / `action_emissions_kg_co2e` on the trace outcome for what
the executed action actually committed. `OptionRow` gained the two fields and
a `has_cost` property, and its `offered` status became `considered`.

This is the shape we asked for — option (a), keeping the runners-up — and it
is what makes a ranking legible as a ranking rather than an assertion about a
winner. The console now renders the road-against-barge comparison directly:
barge at S$1,054 and 139 kg CO2e taken over road at S$1,632 and 422 kg.

**Two things B got right that the console has to respect.**

1. **Operational cost and model cost are different units.** SGD for the move,
   USD for inference. B keeps them in differently named fields and has a test
   asserting they never meet. The console renders them in separate panels and
   never sums them.
2. **Zero is a real value on Rung 1 and Rung 4.** Neither moves a box, so their
   cost is genuinely zero rather than absent. B exposes `has_cost` rather than
   leaving a renderer to guess; the console shows "moves no cargo" there, which
   is different from the gap marker it shows when a field is missing.

**What is still not carried.** `PlanAction.kind`, `resources_required` and the
per-plan `provenance` list remain in-process only. The first two are not needed
on screen. The third is why the unverified-input field names still have to be
reconstructed from the trace (§12 and the confidence panel).

The `Missing` path in the adapter is kept rather than deleted, so a trace
captured before this commit still renders an honest gap instead of a zero.

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

**Measured.** Both predictions above are now confirmed against a real run.
`console/scripts/capture_fixtures.py` drives `runner.handle()` with
`ScriptedFailures({"query_itt_slot": [TIMEOUT, TIMEOUT]})` and an 8-minute-old
`CacheEntry` built from B's own `build_itt_inventory`. It produces:

```
confidence  0.6672   source=0.85 (cache) x age=0.938 (8m) x tool=0.90 (retried)
                     - unverified=0.05 (1 of 3) = 0.67
gate        rung_3_move, would_have_been "auto", required_role "vessel_ops",
            escalated true, reason "confidence 0.67 below 0.7"
```

against the shipped fixture's 0.6172 and `vessel_ops -> duty_manager`.

**Console impact.** C's fixtures come from that harness, so every number on
screen is reproducible by running B's code, and none is tuned toward 0.61.
`console/fixtures/` is the console's source; `fixtures/` (B's) is not read by
the console at all.

**For B:** `fixtures/traces.json` and `fixtures/console_views.json` state a
confidence and an escalation path that `confidence.score()` and
`gates.evaluate()` do not produce. `make_fixtures.py` predates both being
wired together and scripts them by hand. Either regenerate `cr_0001` by
running the pipeline, or delete the scenario — but a fixture that disagrees
with the code it documents is worse than no fixture, and this one is the
scenario the submission leans on. Logged as REQUEST TO B #8.

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
9. **An internal approval that lapses is recorded as
   `WINDOW_LAPSED_NO_RESPONSE`** — the same resolution used when the shipping
   line never replies (`runner.py`, the `answer is None` branch). The line was
   never asked in that case, and `is_service_success` is false either way, so a
   missing internal signature is counted in the north-star metric as a customer
   service failure. Confirmed on the `06-lapsed` fixture: the trace has a
   `gate` step with `status: "lapsed"` and no `external_gate` step at all.
   The console distinguishes the two on screen by checking for an
   `external_gate` step rather than trusting the resolution name. Worth B's
   attention — it is a metric question, not a rendering one.
10. **An internal rejection is recorded as `CUSTOMER_DECLINED_ALL`**, and that
    resolution *is* a service success (`models.py:Resolution.is_service_success`).
    Captured on `05b-approval-declined`: Vessel Operations declines an
    escalated transfer, the line is never contacted, there is no
    `external_gate` step — and the run closes `customer_declined_all`,
    `service_success: true`.

    Together with item 9 this means the north-star metric currently counts an
    internal decline as a customer served, and a missing internal signature as
    a customer failed. Both are decisions nobody outside PSA participated in.
    Logged as REQUEST TO B #9.

---

## REQUEST TO A/B

Ordered by how much the console loses without them.

### ~~REQUEST TO B #1 — serialise the ranked options~~ — **LANDED** `6be7bb4`

Delivered as option (a), a new `options` trace step keeping the runners-up.
Consumed through the adapter only; no component changed shape. See §6.

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

### REQUEST TO A/B #7 — carry `assumptions` on the wire

`to_dict()` should write the assumption block and `from_dict()` should read it,
the way the other enrichment keys should (§4). Until then every JSON-sourced
event mislabels `connection_type`, including in B's own CLI path, and the error
lands in the audit trail rather than staying at the boundary.

Cheapest correct fix if the block is not wanted on the wire: derive
`connection_type` in `from_dict` from `inbound_terminal != outbound_terminal`
rather than defaulting it.

**Landed in `99a47b8`**, taking the derivation route. B derives all four
provenance flags as well, defaulting to synthetic when the payload is silent,
and resolves the contradictory case — identical terminals alongside
`avoidable_by_terminal_prevention` — toward `INTER_TERMINAL` deliberately.

### REQUEST TO B #8 — regenerate or delete the `cr_0001` fixture

`fixtures/traces.json` disagrees with a real run on both the confidence value
and the escalation path (§10). C does not consume it, so nothing is blocked —
but it is the scenario the submission leans on, and a judge who runs the
pipeline will get different numbers from the ones in the repo.

### REQUEST TO B #9 — separate internal approval outcomes from customer outcomes

`runner.handle()` reuses the two customer resolutions for internal approval
outcomes (§12 items 9 and 10):

| What happened | Resolution recorded | `is_service_success` |
|---|---|---|
| Vessel Ops declined; the line was never asked | `customer_declined_all` | **true** |
| Nobody signed; the line was never asked | `window_lapsed_no_response` | false |

Neither involved the customer, so neither should move a metric about serving
the customer. Asking for two new resolutions — `internally_declined` and
`approval_lapsed` — or, if the enum should stay small, exclusion from the
north-star denominator the way `DISMISSED_NO_ACTION` and `SUPERSEDED` already
are.

This is the only finding on the list that changes a reported number rather
than a rendering.

**Landed in `99a47b8`**, as the two new resolutions rather than as exclusion
from the denominator — the right call, because an internal decline is a real
failure to serve, just not the line's. B additionally serialises
`reached_the_line` and `agent_fault` through `case_view()`, which let the
console delete its inference entirely.

Two notes for whoever reads this next. The console's `Resolution` union is an
exhaustive `Record`, so adding the members to `latch.ts` made `tsc` name every
table that needed an arm — but only after the union was updated by hand, and
nothing forced that. Until it was, the adapter crashed on the new values
rather than degrading, and `npm run smoke` never reached the assertion written
to catch exactly this. Fixture JSON is cast at the boundary, not validated;
that is the gap that let a contract change land as a runtime crash.

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
