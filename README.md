# LATCH — agent core

Look-Ahead Transhipment Connection Handler. This repository is **workstream B**:
the agent core, plus the shared contracts A and C build against.

Most containers moving through Singapore are connecting between ships, often at
different terminals. When a vessel slips, those connections fail quietly — and
by the time anyone can act, the choice has already been made for them. LATCH
detects connections losing slack, resolves what it can internally, and gets the
shipping line a real choice while options still exist.

## Run it

```bash
uv sync
uv run pytest
```

## Historical AIS Data & Replay

LATCH uses one month of real Singapore AIS vessel-movement data to test its historical early-warning pipeline.

### Dataset

* **Source:** *AIS Data from 11 ports around the globe* (Singapore subset)
* **Period:** October 2023
* **Records:** 609,975 AIS observations
* **Vessels:** 5,879 anonymised vessel IDs
* **File:** `Data Inspection/Singapore_anonymized.csv`
* **SHA-256:** `a46b6f6f68e5d7f2cc87b3eaa0fe2cc74373cf8e9788b2a3156c4f4644bfad7e`

The AIS dataset provides real timestamped vessel positions and movement information. It does **not** contain PSA's actual container connections, terminal assignments, loading cutoffs, or operational outcomes.

Our historical evaluation therefore separates:

* **Real:** AIS vessel movement and timestamps
* **Derived:** vessel trajectories, arrival-boundary crossings, and causal ETA estimates
* **Synthetic / assumed:** transhipment connections, terminal assignments, container volumes, transfer times, and loading cutoffs

### Stage 2 — Historical Replay Feasibility

The replay prototype currently derives vessel-approach events from a configurable, non-official Singapore arrival boundary.

Current results:

* **5,879** vessels assessed
* **694** vessels crossed the exploratory boundary
* **611** usable derived arrival events
* Median pre-event history: **27 observations / 30.22 hours**
* **89 automated tests passing**

This confirms that the AIS dataset provides sufficient historical event volume to proceed with synthetic connection generation and Watcher evaluation.

> **Important:** Derived geofence events are used for prototype evaluation and are not claimed to be actual PSA vessel arrivals or berth events.

### Stage 3 — Validated Calls & Causal Arrival Updates

The replay now requires two consecutive observations beyond a configurable
2 km outside reset before a vessel can create another call, assigns
deterministic call IDs, and retains both available and ineligible causal
updates. Long gaps begin a new reference segment, and Watcher-facing updates
exclude retrospective crossing outcomes. On the full dataset, 1,853 raw
crossings produced 1,382 reset-confirmed calls: 471 crossings were suppressed
before reset, 886 calls were usable, and 496 were excluded with explicit
reasons. The boundary (`exploratory-circle-v1`), calls, reference arrivals,
and outcomes remain derived and non-official.

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

## Two design points worth knowing

**Confidence is computed, never self-reported.** The model may reason about its
certainty in a rationale; it may never write the number. The formula is
`source × age_decay × tool_outcome − unverified_penalty`, each factor taken
from the weakest input in the plan, with weights frozen in `config.py`.
`ConfidenceBreakdown.explain()` prints the derivation on one line. Combined with
the Gate Controller's policy table, this is what lets the system claim the agent
can neither self-authorise nor self-certify.

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
