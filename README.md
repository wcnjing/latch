# LATCH

**Look-Ahead Transhipment Connection Handler.** PSA Code Sprint 2.0.

Most containers moving through Singapore are connecting between ships, often at
different terminals. When a vessel slips, those connections fail quietly — and
by the time anyone can act, the choice has already been made for them. LATCH
detects connections losing slack, resolves what it can internally, and gets the
shipping line a real choice while options still exist.

The claim is narrow on purpose. PSA cannot control when a vessel arrives, so
the system does not measure connections saved. It measures whether the customer
held a live decision before the window closed — including when they used it to
decline everything. A box that rolls after the line chose to roll it is a
served customer. A box that rolls because nobody was reachable is not.

## The three workstreams

| | Owner | What it is | Where |
|---|---|---|---|
| **A** | Dustie Tang | Real AIS ingestion, validated vessel calls, causal arrival updates, and the risk events B consumes | `src/latch/replay.py`, `watcher.py`, `Data Inspection/` |
| **B** | wcnjing | The agent core: triage, deliberation, gates, locks, the append-only trace | `src/latch/`, `tests/`, `scripts/` |
| **C** | csgohh | The operator console and the confidence display | `console/` |

The seams between them are structural protocols, not imports, so no workstream
blocks on another's schedule. `src/latch/models.py` is the shared contract and
imports nothing from the rest of the package — **treat changes to it as
breaking, and announce them.**

## Run it

```bash
uv sync
uv run pytest                                  # 284 tests
uv run python scripts/run_scenarios.py         # 30 disruption scenarios, no model, instant
uv run latch --events fixtures/mock_events.json --model fake
```

The console (workstream C):

```bash
cd console && npm install && npm run dev       # http://localhost:5173
```

Two suites, measuring two different things, reported separately. The scenario
suite on `PolicyModel` removes judgement entirely and tests the rails — a
failure there is a bug. Running it with `--model local` or `--model anthropic`
tests whether the model chooses well among options the rails already
validated — a failure there is a prompt problem.

## Where to look first

- **What is real and what is invented** — the table below, and it is the first
  thing worth reading. The honest answer is more interesting than the pitch.
- **[COMPLIANCE.md](COMPLIANCE.md)** — every model, dependency, licence and
  data source, including the two MPL-2.0 transitives we chose to declare
  rather than bury.
- **[Data Inspection/singapore_ais_dataset_assessment.md](Data%20Inspection/singapore_ais_dataset_assessment.md)**
  — what the AIS data does and does not contain, written before anything was
  built on it.
- **[console/CONTRACTS.md](console/CONTRACTS.md)** — nine divergences C found
  between the design sketch and A and B as they actually are. Three have
  landed; the rest are open and listed.

## Measured, not asserted

Three numbers we can defend, and one we cannot:

- **ETA error against observed crossings**: 0.37 h at 1 hour of lead time,
  0.89 h at 3 h, 2.76 h at 6 h, 15.93 h at 24 h. The bias is roughly equal to
  the error at every horizon, because the median vessel spends **76.9 % of its
  final 24 hours below one knot** — long-range error is queueing, not
  kinematics. This is why the useful horizon is about six hours, and why
  "improves with real PSA terminal data" is evidence rather than a wish.
- **Case registry**: 74.6 % of agent work was redundant before supersession
  was added.
- **Cost per risk**: computed from real token counts inside each trace, not
  averaged after the fact.
- **Connection-risk accuracy is unmeasurable by construction** and we do not
  report it. We author the connection labels, so scoring ourselves against
  them would be scoring our own homework.



## Historical AIS Data & Replay

LATCH uses one month of real Singapore AIS vessel-movement data to test its historical early-warning pipeline.

### Dataset

* **Dataset:** [*AIS Data from 11 ports around the globe*, version 1](https://doi.org/10.17632/r37vwd493d.1) (Singapore subset)
* **DOI:** `10.17632/r37vwd493d.1`
* **Contributors:** Andreas Hadjipieris, Neofytos Dimitriou, and Ognjen Arandjelovic
* **Original collection source:** AISStream.io API
* **Licence:** [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/)
* **Period:** October 2023
* **Records:** 609,975 AIS observations
* **Vessels:** 5,879 anonymised vessel IDs
* **File:** `Data Inspection/Singapore_anonymized.csv`
* **SHA-256:** `a46b6f6f68e5d7f2cc87b3eaa0fe2cc74373cf8e9788b2a3156c4f4644bfad7e`

The AIS dataset provides real timestamped vessel positions and movement
information. This project uses anonymised vessel identifiers supplied by the
dataset and modifies/transforms the Singapore source data through chronological
sorting, AIS unavailable/sentinel handling, exploratory geofence segmentation,
deterministic derived call identities, and position-derived arrival estimates.
Those derived fields are not official PSA records. The dataset does **not**
contain PSA's actual container connections, terminal assignments, loading
cutoffs, or operational outcomes.

Our historical evaluation therefore separates:

* **Real:** AIS vessel movement and timestamps
* **Derived:** vessel trajectories, arrival-boundary crossings, and causal ETA estimates
* **Synthetic / assumed:** transhipment connections, terminal assignments, container volumes, transfer times, and loading cutoffs

### Stage 2 — Historical Replay Feasibility

The replay prototype currently derives vessel-approach events from a configurable, non-official Singapore arrival boundary.

Current results:

* **5,879** vessels assessed
* **694** vessels crossed the exploratory boundary
* **611** benchmark-eligible derived arrival events under the initial Stage 2 rule
* Median pre-event history: **27 observations / 30.22 hours**
* This initial gate was superseded by the reset-confirmed Stage 3 call analysis below

This confirms that the AIS dataset provides sufficient historical event volume to proceed with synthetic connection generation and Watcher evaluation.

> **Important:** Derived geofence events are used for prototype evaluation and are not claimed to be actual PSA vessel arrivals or berth events.

### Stage 3 — Validated Calls & Causal Arrival Updates

The replay now requires two consecutive observations beyond a configurable
2 km outside reset before a vessel can create another call, assigns
deterministic call IDs, and retains both available and ineligible causal
updates. Long gaps begin a new reference segment. On the full dataset, 1,853
raw crossings produced 1,382 reset-confirmed accepted calls: 471 crossings
were suppressed before reset, 886 calls were benchmark-eligible, and 496 were
benchmark-excluded with explicit reasons. All accepted retrospectively
segmented calls contain 35,379 updates (6,766 `AVAILABLE`, 28,613
`INELIGIBLE`); the explicitly selected benchmark population contains 30,832
updates (6,303 `AVAILABLE`, 24,529 `INELIGIBLE`).

`iter_retrospectively_segmented_arrival_updates` exposes the unfiltered
historical stream for every accepted call. Its update values are causal, but
call membership is assigned retrospectively after a crossing is observed; it
is not a fully live call-membership stream.
`iter_eligible_benchmark_updates` applies the separate, explicit retrospective
benchmark selection. Neither stream places crossing outcomes or eligibility on
`CausalArrivalUpdate`.

PR #2 predicts vessel arrival timing. A later Watcher will predict whether a
synthetic inbound-to-outbound container connection is feasible, whose positive
and negative evaluation labels will be **connection feasible** and
**connection infeasible**—not “vessel crossed the boundary” and “vessel did not
cross the boundary.” This benchmark is conditioned on reset-confirmed, derived
boundary-crossing calls. It does not evaluate scheduled calls that were
cancelled, diverted, disappeared from AIS coverage, or did not cross the
exploratory boundary during the data window. Unclosed approaches are not
manufactured into negative outcomes.

The boundary (`exploratory-circle-v1`), calls, reference arrivals, and outcomes
remain derived and non-official. The complete suite passes **105 tests**.

See the appended Stage 3 findings in
[`Data Inspection/singapore_ais_dataset_assessment.md`](Data%20Inspection/singapore_ais_dataset_assessment.md).

### Git LFS

The AIS CSV is approximately 205 MB, so it is stored using **Git LFS** rather than normal Git storage.

After cloning the repository, install and initialise Git LFS:

```bash
brew install git-lfs
git lfs install
git lfs pull
```

You can verify that the dataset is managed by LFS with:

```bash
git lfs ls-files
```

The checksum above can be used to verify that the exact dataset used in our experiments has been retrieved.

## What is real and what is not

Stated here as plainly as it is stated on the slide.

| Layer | Status |
|---|---|
| Vessel timing | Real, from OCEANS-X — subject to the day-1 data gate |
| Terminal assignment | Carried on every call as `TerminalResolution`: berth, terminal, inferred, or simulated |
| Connection graph | Synthetic, generated from real liner service rotations, parameters frozen before evaluation |
| ITT inventory | Synthetic — no public dataset of Singapore ITT capacity exists |
| Every write action | Stubbed. Interfaces are modelled on `COPRAR` / `IFTMBF` message semantics; the contribution is the decision layer, and the execution layer is deliberately out of scope |

`TerminalResolution` is not decoration. It travels with every vessel call and
feeds the confidence calculation, so the provenance of the inter-terminal split
is mechanical rather than rhetorical.

## Contracts

Workstream A produces `ConnectionRisk`. Workstream C renders `Trace` and
supplies the production `ConfidenceEngine`. Both live in `models.py` and
`confidence.py` — **treat changes as breaking and announce them.**

```
A ──ConnectionRisk──▶  agent core  ──Trace──▶ C
                            ▲
                            └──ConfidenceEngine── C
```

| Module | Owns |
|---|---|
| `models.py` | Frozen contracts. Zero internal imports. |
| `state.py` | Risk lifecycle as a validated transition table |
| `trace.py` | Append-only execution trace, cost included per decision |
| `confidence.py` | Deterministic confidence from provenance |
| `locks.py` | Reservation store for contested resources |
| `tools/` | Stubbed integrations plus deterministic failure injection |
| `events.py` | The A → B contract, and the adapter into the internal model |
| `triage.py` | Decides what deserves the expensive model |
| `deliberation.py` | Enumerates options, then asks the model to rank them |
| `gates.py` | Approval policy. Takes no model client, by construction |
| `runner.py` | The pipeline, end to end |
| `llm.py` | Model seam: `FakeModel` for tests, `AnthropicModel` for real runs |

## The pipeline

```
risk event ─▶ triage ─▶ gather ─▶ compare ─▶ check locks
           ─▶ recommend ─▶ approve if required ─▶ track to resolution
```

Run it:

```bash
uv run latch --model local                      # qwen3:8b via ollama, free
uv run latch --model anthropic                  # billed
uv run latch --customer accepts --approvals never
uv run latch --events path/to/watcher_output.json
```

Three model paths behind one `ModelClient` protocol, so nothing above the seam
knows which ran. The CLI always names the one it used — a run that quietly
used scripted responses and then reported numbers would be worse than no
numbers.

| Path | Cost | Use for |
|---|---|---|
| `fake` | none | Tests and CI. Deterministic, refuses to improvise |
| `local` | zero at the margin | Iteration and triage. `qwen3:8b` via Ollama |
| `anthropic` | billed | Deliberation, where rationale quality is read |

Local inference needs Ollama (MIT) and an Apache-2.0 model — neither copyleft,
both declarable under the competition T&Cs:

```bash
brew install ollama && ollama serve &
ollama pull qwen3:8b        # or set LATCH_LOCAL_MODEL
```

## The combined pipeline

Workstream A derives arrival timing from real AIS. Workstream B decides what
to do about a connection at risk. They meet in exactly one place.

```
 A ─ replay.py ──────────────────────────────────────────────────┐
     real AIS observations                                       │
       -> boundary crossings, reset-confirmed                    │
       -> causal ETA (position + speed at that instant only)     │
       -> CausalArrivalUpdate                                    │
                                                                 ▼
 B ─ connections.py    synthetic connection, hashed from call id
     watcher.py        CausalArrivalUpdate + connection -> RiskEvent
     cases.py          one connection, one live case
     triage.py         is this worth the expensive model
     deliberation.py   enumerate options, model ranks them
     gates.py          who must approve (no model client, by construction)
     locks.py          arbitrate contested slots
     runner.py         the ladder, end to end
       -> Trace  ──────────────────────────────────────────────▶ C
```

`CausalArrivalUpdate` satisfies B's `ArrivalSignal` protocol structurally, so
no conversion code exists between the two. A can rename or extend that type
and the bridge keeps working; only `watcher.py` would ever need to change.

Run the whole chain:

```bash
uv run python scripts/run_historical.py --limit 20000   # A's output -> agent decisions
uv run python scripts/demo.py --from-ais                # one real vessel, narrated
```

### Which stream B consumes, and why

A publishes two. B takes the **unfiltered** one.

| stream | contents | B uses it |
|---|---|---|
| `iter_retrospectively_segmented_arrival_updates` | every accepted call | ✅ |
| `iter_eligible_benchmark_updates` | benchmark-eligible calls only | ❌ |

The benchmark filter is retrospective: a call appears there only if the
episode later turned out clean. Feeding that to the agent would mean it only
ever sees risks that resolved well — survivorship dressed up as a live feed.
The filtered stream is right for scoring A's predictions and wrong for
driving B's decisions.

### Where the boundary between real and invented falls

Both halves run in one process, so it is worth being exact about which is
which. A owns everything above the line; B owns everything below it.

| | Real | Ours |
|---|---|---|
| A | vessel positions, speeds, timestamps; observed boundary crossings | the boundary itself, the ETA method |
| B | — | connections, terminals, box counts, cutoffs, transfer times |

Every `RiskEvent` B emits from this chain carries `TerminalResolution.SIMULATED`
and an `Assumptions` block, both of which travel into the trace and lower the
agent's own confidence. The split is enforced by the pipeline rather than
asserted in a slide.

## The A → B contract

A emits the agreed event format; `RiskEvent.to_connection_risk()` adapts it
into the internal model. When A swaps mock output for the live Watcher, and
later enriches it with vessel and terminal detail, **only the adapter
changes** — the agent logic never touches the wire format.

```json
{
  "connection_id": "DEMO-001",
  "state": "AT_RISK",
  "current_plan_slack_hours": -1.8,
  "no_itt_slack_hours": 2.4,
  "avoidable_by_terminal_prevention": true,
  "affected_boxes": 84,
  "confidence": "MEDIUM",
  "reason_codes": ["INBOUND_ETA_SLIP", "INTER_TERMINAL_TRANSFER_TIME"]
}
```

The two slack figures are the useful part. Their gap is what the transfer is
costing, and when removing it would save the connection outright, Rung 1
becomes a live option instead of advisory noise. `fixtures/mock_events.json`
carries four cases that exercise genuinely different paths: SAFE, WATCH,
AT_RISK-but-avoidable, and AT_RISK-with-nothing-that-works.

> **Two fields are both called confidence and they are not the same thing.**
> `RiskEvent.confidence` is how sure A is that this is a risk at all.
> `Plan.confidence` is how much to trust a specific plan. A's is an *input*
> to B's — a HIGH from the Watcher cannot make a plan built on stale cache
> data trustworthy.

## Two design points worth knowing

**Confidence is computed, never self-reported.** The model may reason about its
certainty in a rationale; it may never write the number. The formula is
`source × age_decay × tool_outcome − unverified_penalty`, each factor taken
from the weakest input in the plan, with weights frozen in `config.py`.
`ConfidenceBreakdown.explain()` prints the derivation on one line. Combined with
the Gate Controller's policy table, this is what lets the system claim the agent
can neither self-authorise nor self-certify.

**Code enumerates options; the model only ranks them.** Candidates are built
from what the tools actually returned, so the agent cannot book a slot that
does not exist — and a chosen id that is not on the candidate list is rejected
rather than executed. The Gate Controller goes further: it imports no model
client and has no channel through which to be persuaded, which is what makes
"the agent cannot self-authorise" a property of the code rather than a claim
about the prompt.

**Failures are injected from a plan, not sampled at random.** The recorded demo
has to replay identically on every take, and a scenario suite whose failures
move between runs cannot be reported as an accuracy figure. `ScriptedFailures`
drives the demo; `SeededFailures` drives the suite.

## The state diagram

Generated from the transition table so the deck cannot drift from the machine
that actually ran:

```bash
uv run python -c "from latch.state import mermaid; print(mermaid())"
```

## Cut ladder

`tests/test_locks.py::test_contention_arbitrates_on_priority_not_arrival` is a
**day-6 entry gate**. If it is not passing by end of day 6, the Lock Table is
cut and the system ships handling one risk at a time — and says so on the slide.
Cutting on day 11, after the build time is already spent, recovers nothing.
