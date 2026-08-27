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
| **C** | csgohh | The operator console: overview, connection workflow, confidence and trace display | `console/` |

The seams between them are structural protocols, not imports, so no workstream
blocks on another's schedule. `src/latch/models.py` is the shared contract and
imports nothing from the rest of the package — **treat changes to it as
breaking, and announce them.**

## Run it

```bash
uv sync
uv run pytest                                  # 303 tests
uv run python scripts/run_scenarios.py         # 30 disruption scenarios, no model, instant
uv run latch --events fixtures/mock_events.json --model fake
```

Against the real AIS extract (needs `git lfs pull`):

```bash
uv run python scripts/eval_eta.py                      # arrival error vs observed crossings
uv run python scripts/eval_detection.py                # detection rate and decision lead time
uv run python scripts/run_historical.py --model local  # the agent on real timing, no API spend
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
  between the design sketch and A and B as they actually are. Four have landed;
  the remaining five are open and listed, with what each one blocks.

## Measured, not asserted

Everything here is computed against observed vessel behaviour. Nothing in this
section touches the synthetic connection layer, because scoring ourselves
against labels we wrote would not be a measurement.

### Arrival prediction

Error against observed boundary crossings: **0.37 h** at 1 hour of lead time,
**0.89 h** at 3 h, **2.76 h** at 6 h, **15.93 h** at 24 h. The bias is roughly
equal to the error at every horizon, because the median vessel spends **76.9 %
of its final 24 hours below one knot** — long-range error is queueing, not
kinematics. This is why the useful horizon is about six hours, and why
"improves with real PSA terminal data" is evidence rather than a wish.

### Detection

Of the vessel calls that arrived materially later than the plan in force, what
share had we flagged, and how often did we cry wolf. Full extract: 609,975
observations, 1,853 crossings, 260 scored calls, 25 % of which deteriorated.

| | detected | precision | false alarms |
|---|---|---|---|
| by T−1h | **78.5 %** | 68.0 % | 12.3 % |
| by T−3h | 58.5 % | 46.3 % | 22.6 % |
| by T−6h | **63.1 %** | 44.6 % | 26.2 % |

65 positives, so the intervals are wide and the 3 h and 6 h rows are not
separable. The false-alarm rate is quoted beside recall every time, and the
next paragraph is why.

**This measurement nearly shipped broken, and the failure is worth showing.**
The first version used the raw kinematic ETA as the reference and reported
100 % detection, 100 % precision and zero false alarms. That was not a good
detector: the raw estimate is optimistic by 7 h at 12 hours out and nearly 20 h
at 24 h, so *every* call "deteriorated", no negatives existed, and recall was
1.0 by construction. The perfect score was the tell. The reference is now
bias-corrected per lead bucket, and the correction is fitted on the earlier
half of the month and scored on the later half so it never sees the calls it is
judged on. See `latch/detection_eval`; `tests/test_detection_eval.py` keeps a
guard that reproduces the original bug.

Scope, and it belongs beside the number: this is deterioration against our own
calibrated estimate, not lateness against a berth window PSA published — the
extract carries no official schedule. It measures the early-warning layer. It
says nothing about whether the agent's decisions are good.

### Decision lead time

**Median 16.5 h** between the first alarm and the vessel's actual arrival
(p25 8.2 h, p75 21.2 h, n = 62).

This is what sits where "connections rescued" would go, and the substitution is
deliberate. Connections rescued requires a counterfactual — what would have
happened without LATCH — that no dataset contains, so any number in that slot
would be invented. Lead time is observed, and it is the claim the product
actually makes: not that boxes were saved, but that the decision reached the
line while options still existed.

### The agent on real timing

`run_historical.py --model local` runs the real model (qwen3:8b, local, no API
spend) over real October 2023 AIS rather than scripted responses. From 50,000
arrival updates: 6,766 risk events, **73.3 % of agent work avoided** by the
case registry's supersession, 25 admitted cases, 11 served.

Vessel timing there is real and every connection, terminal, box count and
cut-off is generated. It measures agent behaviour on realistic timing, not
containers saved.

### What we refuse to report

**Connection-risk accuracy.** We author the connection labels, so scoring
against them is grading our own homework.

**The vessel's own broadcast ETA as a baseline.** Vessels frequently broadcast
an ETA for their *next* port rather than Singapore, so beating it would prove
nothing.

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

### Stage 4 — Synthetic connection topology and UCIDs

`latch.synthetic` is a deterministic synthetic benchmark-generation layer.
PR #3 builds its synthetic connection graph from
`iter_retrospectively_segmented_arrival_updates`. The population is still
retrospectively segmented into accepted PR #2 calls because PR #2 does not
expose a completely live call-population primitive. The generator uses a
source `call_id` only to find that call's first `AVAILABLE` update, projects it
immediately into an outcome-free `SyntheticCallCandidate`, and discards later
predictions and all crossing, eligibility, and exclusion information.

Candidate ordering and seeded pairing use only the causal reference timestamp,
reference arrival, source observation row, boundary version, and source type.
Neither source call IDs nor anonymised vessel IDs affect ordering, rank, or
UCID. Vessel ID is retained only in `UCIDAssignment` for lineage and to prevent
a vessel connecting to itself.

A synthetic UCID identifies a fixed reference-arrival connection slot: port
`SGSIN`, origin and destination terminal, the immutable interval between the
inbound/outbound first-`AVAILABLE` causal reference arrivals, topology version,
and deterministic sequence/digest. This interval is not an official schedule,
berth window, cargo cutoff window, or PSA service window. Vessel-call
assignment, process sensitivity, cargo-ready/cut-off assumptions, transfer
duration, impact, and projected difficulty do not enter topology or identity.
Same-terminal connections use `NONE` with zero transfer duration;
inter-terminal connections use configured `ROAD` or `SEA`.

Topology quotas use only terminal direction, transfer mode, an optional raw
reference-arrival-gap band, impact, and exact count. A deterministic global
matching step allocates unique ordered candidate pairs across all requested
slots before process scenarios are projected. Difficulty is output metadata
and may differ by sensitivity scenario.

The committed fixture is intentionally only three connections, sufficient to
exercise the contract. Its explicit cells are not a production quota and make
no claim about PSA prevalence. PR #3 itself added no Watcher state, outcome
label, baseline, risk evaluation, performance metric, agent, UI, or API
integration.

The PR #4 assessment API now joins `latch.synthetic` connections to PR #2
causal updates without replacing the legacy runtime/demo path based on
`latch.connections`. Existing historical-run, demo, console, and deck figures
remain legacy outputs, not PR #4 historical experiment results.

Candidate-pair enumeration and SHA-256 ranking remain quadratic in the
candidate count for each quota cell. Generic unbounded historical CSV
generation remains disabled. The Phase 2 Watcher evaluation instead declares
a deterministic bounded source population and separate historical quota
configuration; it does not present the tiny contract fixture or a silent
sample as the full historical graph.

**TEST-ONLY SYNTHETIC FIXTURE VALUES. NOT PSA OPERATIONAL ESTIMATES OR
PREVALENCE.**

## PR #4 causal connection-risk Watcher

`latch.watcher.assess_connection` dynamically assesses a fixed PR #3 UCID
using only the latest `AVAILABLE` PR #2 inbound and outbound predictions known
at or before the requested assessment time. PR #2 timing is derived causally
from real AIS observations. The connection, terminal assignment, process
scenario, transfer assumptions, impact and optional box count supplied by PR
#3 are synthetic. They are not actual PSA connections or operational records.

For the one configured LOW, REFERENCE, or CONSERVATIVE process projection, the
Watcher recomputes live timing rather than reusing PR #3 reference-time
projections:

```text
inbound_cargo_ready_at = inbound_predicted_arrival + cargo_ready_offset
outbound_cargo_cutoff = outbound_predicted_arrival - cargo_cutoff_lead
current_plan_ready_at = inbound_cargo_ready_at + transfer_duration
current_plan_slack = outbound_cargo_cutoff - current_plan_ready_at
no_itt_slack = outbound_cargo_cutoff - inbound_cargo_ready_at
```

An available assessment is `SAFE` when slack is greater than the configured
warning margin, `WATCH` when it is positive and no greater than the margin,
and `AT_RISK` when it is zero or negative. `UNAVAILABLE` is a separate
assessment status meaning that one or both causal predictions are absent; it
is not a risk severity. Terminal prevention is marked avoidable exactly when
current-plan slack is negative and no-ITT slack is non-negative. Same-terminal
connections have zero transfer duration and cannot be terminal-prevention
cases.

The separate **derived reference-delay baseline** uses only the inbound
prediction and its first-available derived reference:

```text
delay = inbound_predicted_arrival - inbound_reference_arrival
alert = delay >= configured_reference_delay_threshold
```

Both thresholds and every process duration are experimental configuration,
not PSA or industry operating standards. The Watcher never substitutes a final
geofence crossing, future update, retrospective eligibility/quality result,
PR #3 reference-window timestamp, or final outcome. Historical `call_id` is
used only as an opaque join key; its membership was retrospectively segmented,
so this benchmark is not represented as a fully live call-discovery system.
Historical performance labels and metrics remain out of scope for PR #4.

## PR #5 Phase 2 causal historical Watcher evaluation

`latch.historical_eval` composes reset-confirmed PR #2 calls, the PR #3
synthetic generator, and `assess_connection()` without changing the legacy
historical runner. The new entry point is explicit:

```bash
uv run python scripts/run_historical.py --mode watcher-eval
```

The default bounded benchmark takes the first 256 accepted calls after sorting
by their first causal update and requests eight unique connections in each of
four declared topology/mode quota cells. Both bounds are CLI configuration.
This is a scalability decision around PR #3's current quadratic candidate-pair
enumeration, not an estimate of connection prevalence.

Updates replay in `(observed_at, source_row_number, call_id)` order. A
synthetic connection activates only after the later of its two candidate
observation cursors, so a same-timestamp candidate on a later source row is
not exposed early. Once active, the Watcher receives only the inbound and
outbound chronological prefixes accumulated so far. Legs join through
`assignment.inbound_source_call_id` and
`assignment.outbound_source_call_id`; vessel ID is lineage and a self-pair
guard, not the primary join.

The output records Watcher status, severity, slack, selected derived causal
arrival predictions, ages, reason codes, and the embedded derived
reference-delay baseline. Final `DerivedArrivalEvent` values are retained in a
separate evaluation-only population view and never enter `assess_connection()`.
No retrospective outcomes, accuracy metrics, agent runs, case-registry claims,
or legacy trace metrics are produced in this phase. The graph remains a
retrospectively constructed benchmark; causal activation does not make it a
true live call-discovery benchmark.

## PR #5 Phase 3 retrospective synthetic connection benchmark

Phase 3 adds a post-replay evaluation layer without changing the Phase 2
replay. `RetrospectiveConnectionOutcome` is frozen and structurally separate
from `CausalArrivalUpdate`, `ConnectionRiskAssessment`, `RiskEvent`, and the
causal replay state. It is created only after replay completes from the final
PR #2 derived crossings and the selected PR #3 process projection:

```text
retrospective_inbound_ready = final_inbound_derived_crossing
                               + cargo_ready_offset
                               + transfer_duration
retrospective_outbound_cutoff = final_outbound_derived_crossing
                                - cargo_cutoff_lead
retrospective_slack = retrospective_outbound_cutoff
                      - retrospective_inbound_ready
```

`retrospective_slack <= 0` is `INFEASIBLE`; positive slack is `FEASIBLE`.
This means **connection infeasible under this synthetic process scenario**.
It is not an observed missed PSA connection, actual cargo outcome, actual UCID
outcome, or real PSA ground truth. The separate no-ITT counterfactual is:

```text
retrospective_no_itt_slack = final_outbound_derived_crossing
                             - cargo_cutoff_lead
                             - (final_inbound_derived_crossing
                                + cargo_ready_offset)
```

An infeasible transferred scenario with positive no-ITT slack is labelled only
as a **synthetic terminal-prevention opportunity**, never as a connection
actually saved.

Scoring is connection-level, not assessment-row-level. For each UCID and each
default horizon T−6h, T−3h, and T−1h, evaluation time is the retrospective
synthetic cut-off minus the horizon. The scorer selects the latest causal
assessment with `assessed_at <= evaluation_time`; it never looks forward. No
such row means unavailable, not SAFE. The horizon list is configurable with
`--evaluation-horizons-hours`, while those three values are frozen defaults.

The primary Watcher alert is `WATCH` or `AT_RISK`; `SAFE` is negative. With
the default experimental configuration, `AT_RISK` means causal scenario slack
at or below zero, `WATCH` means positive slack at or below the two-hour warning
margin, and `SAFE` means more than two hours. The reference-delay baseline is
the already embedded PR #4 result from the exact same selected assessment and
inbound prediction; its default threshold is a derived inbound delay of at
least 15 minutes. It is not the calibrated baseline in `eval_detection.py`.

Every horizon retains a five-way connection-level result (TP, FP, TN, FN,
unavailable). The end-to-end view treats unavailable as no alert, including as
FN for an infeasible scenario, and states that convention explicitly. The
common-support view scores both detectors only where both are available. Since
the baseline is embedded in the same assessment, supports coincided in this
run. Recall, precision, false-alarm rate, specificity, and F1 are `null` when
their denominators are zero; accuracy is not a headline metric.

### Default bounded benchmark result

The following figures are from the **retrospective synthetic connection
benchmark**, not production performance. The deterministic input was 1,382
accepted PR #2 calls, bounded to the first 256; 237 produced first-available
PR #3 candidates. Four quota cells generated 32 connections: 16 same-terminal
and 16 inter-terminal, with 16 `none`, 8 `road`, and 8 `sea` transfer modes.
All 32 had valid outcomes and none was excluded from scoring. Under the
REFERENCE scenario, 23 were feasible and 9 infeasible synthetic scenarios.
The replay produced 1,202 causal assessments across all 32 activated UCIDs.

Availability is fixed-horizon coverage, rather than Phase 2's
activation-conditioned event-triggered unavailable fraction:

| Horizon | Available | Unavailable | Coverage | Reason |
|---|---:|---:|---:|---|
| T−6h | 12 | 20 | 37.5% | no assessment at/before horizon |
| T−3h | 18 | 14 | 56.2% | no assessment at/before horizon |
| T−1h | 24 | 8 | 75.0% | no assessment at/before horizon |

REFERENCE raw confusion counts and end-to-end rates are:

| Horizon | Detector | TP | FP | TN | FN | Unavailable | Recall | Precision | FAR | Specificity | F1 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| T−6h | Watcher | 2 | 0 | 10 | 0 | 20 | 22.2% | 100.0% | 0.0% | 100.0% | 36.4% |
| T−6h | reference-delay | 1 | 6 | 4 | 1 | 20 | 11.1% | 14.3% | 26.1% | 73.9% | 12.5% |
| T−3h | Watcher | 2 | 0 | 14 | 2 | 14 | 22.2% | 100.0% | 0.0% | 100.0% | 36.4% |
| T−3h | reference-delay | 4 | 10 | 4 | 0 | 14 | 44.4% | 28.6% | 43.5% | 56.5% | 34.8% |
| T−1h | Watcher | 3 | 0 | 18 | 3 | 8 | 33.3% | 100.0% | 0.0% | 100.0% | 50.0% |
| T−1h | reference-delay | 6 | 11 | 7 | 0 | 8 | 66.7% | 35.3% | 47.8% | 52.2% | 46.2% |

Because unavailable is separated in the raw counts but imputed negative in
the displayed end-to-end rates, raw TP+FP+TN+FN is the available support. On
common/available support, Watcher recall was 100.0%, 50.0%, and 50.0% with
precision 100.0% at T−6h/T−3h/T−1h. Baseline recall was 50.0%, 100.0%, and
100.0%; precision was 14.3%, 28.6%, and 35.3%.

Paired disagreements on common support were:

| Horizon | Label | Both alert | Watcher only | Baseline only | Neither |
|---|---|---:|---:|---:|---:|
| T−6h | INFEASIBLE | 1 | 1 | 0 | 0 |
| T−6h | FEASIBLE | 0 | 0 | 6 | 4 |
| T−3h | INFEASIBLE | 2 | 0 | 2 | 0 |
| T−3h | FEASIBLE | 0 | 0 | 10 | 4 |
| T−1h | INFEASIBLE | 3 | 0 | 3 | 0 |
| T−1h | FEASIBLE | 0 | 0 | 11 | 7 |

Before the retrospective synthetic cut-off, Watcher first alerted on 6/9
infeasible scenarios (median 1.76h lead, p25 0.56h, p75 10.06h); the baseline
alerted on 7/9 (median 3.66h, p25 2.24h, p75 4.62h). This is synthetic decision
time, not proof of operational rescue. Watcher churn had median 0 transitions,
p90 0.9, 28/32 (87.5%) connections with zero transitions, and none above the
descriptive `>4` threshold. There were 0/9 synthetic terminal-prevention
opportunities.

The stable PR #3 LOW/REFERENCE/CONSERVATIVE abstraction permits sensitivity
on exactly the same UCIDs and source population. LOW produced 25 feasible/7
infeasible scenarios, REFERENCE 23/9, and CONSERVATIVE 23/9. Fixed-horizon
availability was respectively 12/19/28, 12/18/24, and 11/13/19 at
T−6h/T−3h/T−1h. Separate full scorecards are written in the JSON report; no
connection population is regenerated between scenarios.

Run the scorecard and optionally write its deterministic, timestamp-free,
versioned JSON manifest with:

```bash
uv run python scripts/run_historical.py --mode watcher-eval \
  --output historical-watcher-report.json
```

The JSON includes configuration and limits, seed and quota definitions,
Watcher thresholds, all process assumptions and horizons, composition,
availability, raw/end-to-end/common-support metrics, paired comparisons,
lead-time and churn statistics, terminal-prevention opportunities, scenario
sensitivity, digests, and explicit provenance/limitations. It does not alter
legacy `run_historical.py` figures, `eval_eta.py`, `eval_detection.py`, or
`TraceStore` service-rate evidence.

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

Stated here as plainly as it is stated on the slide, and on the console header
where it cannot be cropped out of a screen recording.

| Layer | Status |
|---|---|
| Vessel movement | **Real.** One month of Singapore AIS positions, speeds and timestamps — [Mendeley, CC BY 4.0](https://doi.org/10.17632/r37vwd493d.1). See [COMPLIANCE.md](COMPLIANCE.md) |
| Arrival estimates | **Derived** from that movement by position and current speed alone, causally. Error measured above, not assumed |
| Terminal assignment | Carried on every call as `TerminalResolution`: berth, terminal, inferred, or simulated. On the historical path it is `simulated`, and the console surfaces that per connection |
| Connection graph | Synthetic. Generated from real liner service rotations with parameters frozen before evaluation |
| PR #3 synthetic benchmark | Deterministic `latch.synthetic` contract fixture generated from first-available causal AIS references and frozen quota cells; PR #4 assesses it through a separate causal API and does not replace `latch.connections` or existing runtime/demo results |
| Box counts and cut-offs | Synthetic. No public source exists |
| ITT inventory | Synthetic — no public dataset of Singapore inter-terminal capacity exists |
| Model responses | Scripted in the captured console fixtures, so those traces measure the pipeline rather than the agent. `--model local` runs the real model; see *The agent on real timing* above |
| Every write action | Stubbed. Interfaces are modelled on `COPRAR` / `IFTMBF` / `IFTSAI` message semantics; the contribution is the decision layer, and execution is deliberately out of scope |

`TerminalResolution` is not decoration. It travels with every vessel call and
feeds the confidence calculation, so the provenance of the inter-terminal split
lowers the agent's own certainty rather than being a caption.

**One thing we do not have.** There is no official scheduled arrival, berth
assignment or port-call record anywhere in this repository. The AIS extract
does not contain them, and the vessel's own broadcast ETA is frequently for its
next port. `POLL_INTERVAL_SEC` and the `oceans_x.vessel_movements` source
string in fixtures name the feed a production deployment would use; **no
OCEANS-X data was obtained or used here**, and every "real" claim above rests
on the Mendeley extract alone.

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
uv run python scripts/run_historical.py --mode watcher-eval  # PR #2 + #3 + #4 diagnostics
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
