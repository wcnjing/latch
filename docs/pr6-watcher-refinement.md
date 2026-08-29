# PR #6: Watcher refinement and terminal-prevention evidence

## Purpose

PR #6 is the final Data & Detection / Watcher refinement. It investigates:

- why early Watcher alerts are unavailable or missed;
- sensitivity to predeclared warning margins;
- trade-offs between the connection-aware Watcher and the inbound-only
  reference-delay baseline;
- alert stability before synthetic cutoff;
- retrospective terminal preventability; and
- causal terminal-prevention actionability.

The objective is diagnosis and reproducible capability evidence, not tuning a
threshold until it beats a baseline. PR #6 does not alter replay semantics,
UCID topology, process assumptions, the Watcher slack equation, the baseline,
or the frozen historical population.

## Frozen parent and reproducibility

The authoritative PR #5 experiment parent is commit
`2fad0f8be7c6856a03098049d05e1aac5b52d268`, together with its existing result
sections in `README.md` and
`Data Inspection/singapore_ais_dataset_assessment.md`.

| Evidence | SHA-256 |
|---|---|
| Historical refinement report | `aeb9c340b773d1ea60211971b18b613b186afbe64c85eda3cdf9e2393479bac8` |
| Terminal-prevention semantic report | `285c734784e604f74a1135b592b559f69b616c4cd20f8f2dca62080ec560b2ce` |

Relevant deterministic identities are:

| Identity | Digest |
|---|---|
| AIS dataset | `a46b6f6f68e5d7f2cc87b3eaa0fe2cc74373cf8e9788b2a3156c4f4644bfad7e` |
| Frozen population | `2cb9b23d006344f7f8e3d38b98ae030e727e846b83936a99a3272cfda5dd7291` |
| Frozen historical graph | `25c1a7a1f989da12f7a58729532797fc69777e53fcba2ba2d76fec182e5b60a2` |
| Frozen historical graph output | `0df7cd032f84ced28227a10cd8978524be46eaac1710ad5d86e9eccd8fcf3132` |
| Ordered historical UCIDs | `4a73724d162a139400eaf9e0e5714c7a92061b0267885b90f099d3c79d9d8266` |
| Historical scenario outcomes | `127c81e42f9c337f8d0f4abe20218080d18ee2c38718627fa48a844b992dc415` |
| Challenge selection input | `2d4730561c4cefb5880380a9a3c55a23c4446290e0c37a740291f98bc31fd679` |
| Retrospective challenge graph | `3d3c8fbd1a1a2832f81850b6f1fc2d66cebb675352a945e6a6d0ca45a41e9fa8` |
| Retrospective challenge set | `f968c7618ff253758977444c442ae81773d3f8cfae7bb3d8929b89a5db90410c` |
| Causal-actionability graph | `1cff5b02b8515dd0397018f80e601968852f92f8e8f6d9f2b3d9fa37c9192b91` |
| Causal-actionability set | `79740d0defee202f73fb3f9d42e3d79c466a7821385d76df879e19cefb6ad71a` |

Reports are timestamp-free and byte deterministic. Generate them only at a
caller-specified temporary path:

```bash
uv run python scripts/run_watcher_refinement.py \
  --output /tmp/watcher-refinement-report-v1.json

uv run python scripts/run_terminal_prevention_challenge.py \
  --output /tmp/terminal-prevention-challenge-v1.json

shasum -a 256 \
  /tmp/watcher-refinement-report-v1.json \
  /tmp/terminal-prevention-challenge-v1.json
```

The approximately 5.9 MB refinement report and temporary challenge reports are
not committed. Their generation commands, contracts, digests, and reviewed
findings are recorded instead.

## Evidence layers

PR #6 maintains three separate evidence layers. Their populations and claims
must not be merged.

### A. Frozen historical benchmark

Purpose: measure Watcher behaviour on the fixed synthetic historical
population.

| Item | LOW | REFERENCE | CONSERVATIVE |
|---|---:|---:|---:|
| Connections | 32 | 32 | 32 |
| Retrospectively infeasible | 7 | 9 | 9 |
| Retrospective prevention opportunities | 0 | 0 | 0 |

The same 32 connections, source-call population, graph, and UCIDs are reused in
every scenario. Zero prevention opportunities is the frozen empirical result;
the historical graph is not changed to create examples.

### B. Retrospective terminal-prevention challenge set

Purpose: a behavioural discrimination test over deliberately curated cases.

The separate `terminal-prevention-challenge-v1` contract is labelled:

> DELIBERATELY CURATED / DETERMINISTIC SYNTHETIC CHALLENGE SELECTION

It retains four cases in each category:

- `RETROSPECTIVE_PREVENTION_OPPORTUNITY`;
- `UNRECOVERABLE_WITH_NO_ITT`; and
- `FEASIBLE_WITH_ITT`.

The 12 cases are not appended to the historical benchmark. Their counts are
curated capability counts, not operational recall, precision, or prevalence.

### C. Causal-actionability capability set

Version: `causal-actionability-capability-v1`

Label:

> DELIBERATELY CURATED CAUSAL-ACTIONABILITY CAPABILITY SET

Purpose: verify that LATCH can represent, from causal replay values, the state:

```text
current_plan_slack <= 0
and no_itt_slack > 0
```

The REFERENCE search found 5,051 qualifying candidate configurations and
selected the first four deterministic ranks. The number 5,051 describes only
configurations found during deliberate challenge search. It is not prevalence,
an actual opportunity count, a PSA connection percentage, or expected
operational frequency.

## Causal and retrospective separation

The refinement evaluator has a one-way structure:

```text
updates observed at or before assessment time
    -> causal support, prediction selection, slack, state, baseline, history
    -> evaluation-only join of final outcome, retrospective slack and labels
```

At a fixed horizon, a leg has support only when an AVAILABLE causal prediction
for its assigned source call was observed no later than the evaluation
timestamp. Final crossings, completed-call eligibility, outcome category, and
future observations cannot establish causal support or change an earlier
assessment.

Prediction age at the selected assessment is kept separate from the age of the
latest support at the evaluation horizon. The baseline is embedded in the same
assessment and must use the exact inbound prediction selected by the Watcher on
common support.

## Causal coverage diagnosis

Early missed alerts were predominantly associated with missing causal leg
support. At REFERENCE T−6h, 7 of 9 retrospectively infeasible connections were
blocked by missing causal support:

- 2 had neither leg supported; and
- 5 had inbound support but lacked outbound support.

At T−3h, 5 of 9 still lacked sufficient causal support; at T−1h, 3 of 9 did.
These are horizon-specific connection counts. They are preferable to summing
the same connection repeatedly across scenarios, margins, and horizons.

Missing causal support means that the historical AIS-derived replay did not
yet contain sufficient timing information for both vessel legs. It does not
mean that the synthetic connection definition or its assigned legs were
missing. The synthetic pairing determines which two legs are required; it
cannot create or remove historical AIS observations.

For an infeasible, non-alerted connection, PR #6 assigns one deterministic
reason:

1. `NO_EITHER_LEG_SUPPORT`
2. `NO_INBOUND_SUPPORT`
3. `NO_OUTBOUND_SUPPORT`
4. `ASSESSMENT_NOT_EMITTED_WITH_COMMON_SUPPORT`
5. `WATCHER_UNAVAILABLE`
6. `POLICY_SAFE_ABOVE_WARNING_MARGIN`
7. `POLICY_INCONSISTENT`
8. `OTHER`

The fourth and seventh reasons are invariant warnings rather than SAFE policy
decisions. Neither occurred in the historical run.

## Warning-margin sensitivity

The predeclared experimental grid was evaluated in declaration order:

```text
0h, 1h, 2h, 3h, 4h
```

These values are not PSA thresholds or industry standards. Every value was
reported; no preferred value was selected after observing the results.

For every available causal assessment, experimental state was reclassified
from causal current-plan slack only:

```text
slack <= 0       -> AT_RISK
0 < slack <= M   -> WATCH
slack > M        -> SAFE
```

Changing `M` could change WATCH versus SAFE, alert entry, and churn. It could
not change calls, pairing, terminal assignment, UCID, topology, predictions,
slack, process assumptions, retrospective outcomes, graph digest, or baseline.

REFERENCE end-to-end examples show the sensitivity trade-off:

| Horizon | Margin | Recall | Precision | False positives |
|---|---:|---:|---:|---:|
| T−3h | 2h | 22.2% | 100.0% | 0 |
| T−3h | 4h | 33.3% | 50.0% | 3 |
| T−1h | 2h | 33.3% | 100.0% | 0 |
| T−1h | 4h | 44.4% | 57.1% | 3 |

The 2h warning margin is retained, not proven optimal. The reasons are limited
to these reviewed findings:

- wider margins did not provide a consistent sensitivity improvement;
- wider margins introduced additional false positives in several cells;
- many early misses were driven by causal data availability; and
- post-hoc benchmark tuning would be inappropriate.

No Watcher default changes and no new detector policy follow from the
sensitivity study.

## Watcher and baseline trade-off

End-to-end scoring includes every valid historical outcome and treats an
unavailable detector as not alerted. Common support requires both causal legs
and an available Watcher assessment; these denominators remain separate.

At frozen REFERENCE 2h, T−1h:

| Detector | Recall | Precision | Alerts | False positives |
|---|---:|---:|---:|---:|
| Watcher | 33.3% | 100.0% | 3 | 0 |
| Inbound-delay baseline | 66.7% | 35.3% | 17 | 11 |

The inbound-delay baseline was more sensitive, while the connection-aware
Watcher was more selective. This is a recall/alert-burden trade-off, not
universal Watcher superiority. The baseline remains the frozen inbound-only
reference-delay detector with a 15-minute threshold.

## First-alert lead time

Before synthetic cutoff in REFERENCE:

| Detector | Caught | Missed | Median first-alert lead |
|---|---:|---:|---:|
| Watcher | 6/9 | 3/9 | 1.76h |
| Inbound-delay baseline | 7/9 | 2/9 | 3.66h |

Each distribution is conditional on the connections caught by that detector.
It is therefore not a pure like-for-like timing shift over one shared caught
population, and synthetic lead time is not proof of an operational rescue.

## Alert stability

Across tested scenario/margin cells:

- median state transitions per connection was 0;
- p90 transitions per connection was at most 1; and
- wider margins did not materially increase repeated alert entries.

PR #6 therefore introduces no hysteresis. The evidence did not justify adding
stateful detector behaviour to solve a churn problem that was not observed.

## Retrospective preventability versus causal actionability

`RETROSPECTIVE_PREVENTION_OPPORTUNITY` means:

```text
transfer_duration > 0
and retrospective_current_plan_slack <= 0
and retrospective_no_itt_slack > 0
```

Using final synthetic outcome timing, the connection fails with ITT but would
be feasible without ITT. This is an evaluation-only counterfactual and is not,
by itself, an actionable early-warning opportunity.

`CAUSAL_PREVENTION_SIGNAL` means that at one available replay assessment:

```text
current_plan_slack <= 0
and no_itt_slack > 0
```

Only information available at that replay moment participates. It means the
current plan is predicted infeasible while removing ITT restores positive
predicted slack. The report records the first such signal, lead to cutoff,
causal slack values, recovered slack, and the corresponding AT_RISK state.

The concepts are deliberately independent and must never be treated as
equivalent.

### Retrospective challenge results

| Case | Watcher result before cutoff | Actionability classification |
|---|---|---|
| TPC-01 | Alert and causal prevention signal | `CAUSALLY_ACTIONABLE` |
| TPC-02 | No causal assessment | `NO_CAUSAL_ASSESSMENT_BEFORE_CUTOFF` |
| TPC-03 | Alert after causal no-ITT slack was non-positive | `ALERTED_AFTER_PREVENTION_WINDOW_CLOSED` |
| TPC-04 | Alert after causal no-ITT slack was non-positive | `ALERTED_AFTER_PREVENTION_WINDOW_CLOSED` |

Three of four curated retrospective-prevention cases received an alert before
cutoff. Only one reached the causal current-plan-infeasible/no-ITT-feasible
state; one had no assessment; and two alerts occurred after the prevention
window had already closed. These are curated capability counts, not operational
performance statistics. The result is consistent with the broader finding
that historical causal timing availability can limit early intervention.

The other curated categories remain separate: four cases are unrecoverable
even without ITT and four are feasible with ITT. They test whether the Watcher
can distinguish prevention from insufficient or unnecessary intervention.

### Causal-actionability capability cases

All four selected cases reached the qualifying causal state under unchanged
REFERENCE assumptions:

| Case | Route/mode | First causal signal | Lead | Current/no-ITT slack | Recovered |
|---|---|---|---:|---:|---:|
| CAP-01 | Pasir Panjang→Tuas / sea | 2023-10-01 22:14:57Z | 1.00h | −1.29h / +0.71h | 2h |
| CAP-02 | Pasir Panjang→Tuas / sea | 2023-10-01 15:36:10Z | 55.63h | −1.48h / +0.52h | 2h |
| CAP-03 | Pasir Panjang→Tuas / sea | 2023-10-01 09:14:50Z | 67.76h | −0.55h / +1.45h | 2h |
| CAP-04 | Tuas→Pasir Panjang / road | 2023-10-02 05:33:48Z | 0.69h | −0.32h / +0.68h | 1h |

The set tests whether the signal can exist and be represented correctly. It
does not prove that an intervention would ultimately be required, that
removing ITT would guarantee the final connection outcome, or that the causal
prediction would remain unchanged as later vessel observations arrive.

This limitation is visible in the retrospective metadata: CAP-01 is
retrospectively unrecoverable, while CAP-02 through CAP-04 are retrospectively
feasible with ITT. That is legitimate because retrospective outcome and causal
assessment are deliberately independent.

## Final technical decisions and claim boundary

PR #6 retains:

- the 2h Watcher warning margin;
- the 15-minute baseline threshold;
- LOW, REFERENCE, and CONSERVATIVE process assumptions;
- the frozen 32-connection historical benchmark;
- replay and UCID topology semantics;
- the existing Watcher slack equation; and
- no hysteresis.

PR #6 does not claim that 2h is optimal, that the Watcher universally beats
the baseline, that a challenge case represents a real PSA connection, that a
container was rescued, or that 5,051 configurations estimate real-world
preventability. All terminal assignments, pairings, transfer processes,
cutoffs, outcomes, and challenge populations remain synthetic or experimental.
