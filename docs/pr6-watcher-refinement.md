# Watcher refinement workstream (internally developed as PR #6)

## Purpose

This workstream is the final Data & Detection / Watcher refinement. It was
internally developed as PR #6; that label is not necessarily the current
GitHub pull-request number. It investigates:

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
| Historical refinement report | `17e5c49f66c0031c5ef347fc1b980b26660b7d8f7ffe73c0b3b9dc2cec253d9b` |
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

The modules in this workstream are offline diagnostic/evaluation tooling,
invoked only through `scripts/run_watcher_refinement.py` and
`scripts/run_terminal_prevention_challenge.py`. They are intentionally not
wired into Agent Core runtime, the demo runner, the console, or the production
Watcher path. This is a deliberate scope decision, not missing integration.

CI does not currently run the real-data regression: `.github/workflows/ci.yml`
sets `actions/checkout` to `lfs: false`, so
`tests/test_terminal_prevention_challenge.py::test_frozen_real_32_connection_benchmark_and_zero_opportunities_remain_unchanged`
skips when the 205 MB AIS CSV remains an LFS pointer. The smallest workflow
change would be `lfs: true` on that checkout, but it would add the dataset
download and real-data runtime to every CI run. This deadline fix therefore
documents the gap and leaves CI unchanged; a separate scheduled/manual
real-data job is the lower-risk follow-up if that cost is undesirable on every
pull request.

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

All five REFERENCE margins are shown below as end-to-end `TP/FP/TN/FN`
confusion matrices:

| Margin | T−6h | T−3h | T−1h |
|---:|---:|---:|---:|
| 0h | 2/0/23/7 | 2/0/23/7 | 3/0/23/6 |
| 1h | 2/0/23/7 | 2/0/23/7 | 3/0/23/6 |
| 2h | 2/0/23/7 | 2/0/23/7 | 3/0/23/6 |
| 3h | 2/1/22/7 | 2/3/20/7 | 3/3/20/6 |
| 4h | 2/1/22/7 | 3/3/20/6 | 4/3/20/5 |

Under REFERENCE, no alert is WATCH-only for 0h, 1h, or 2h: alerting begins
only when slack is non-positive. Consequently those three margins have
identical fixed-horizon confusion matrices at every tested horizon, including
on common support. The REFERENCE slice alone therefore provides no evidence
specifically supporting 2h. Margin separation occurs in other process-scenario
and horizon cells (and for 3h/4h within REFERENCE). The 2h margin is retained as
the existing configuration, not validated as optimal.

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
and an available Watcher assessment. These denominators answer different
questions: end-to-end measures behavior over the full outcome population,
including lack of availability, while common support compares the detectors
only where both can be evaluated.

At frozen REFERENCE 2h, T−1h:

| Detector | Recall | Precision | Alerts | False positives |
|---|---:|---:|---:|---:|
| Watcher | 33.3% | 100.0% | 3 | 0 |
| Inbound-delay baseline | 66.7% | 35.3% | 17 | 11 |

The corresponding common-support comparison is:

| Horizon | Detector | Support | TP/FP/TN/FN | Recall | Precision | False positives |
|---|---|---:|---:|---:|---:|---:|
| T−3h | Watcher | 18 | 2/0/14/2 | 50.0% | 100.0% | 0 |
| T−3h | Inbound-delay baseline | 18 | 4/10/4/0 | 100.0% | 28.6% | 10 |
| T−1h | Watcher | 24 | 3/0/18/3 | 50.0% | 100.0% | 0 |
| T−1h | Inbound-delay baseline | 24 | 6/11/7/0 | 100.0% | 35.3% | 11 |

On common support the inbound-delay baseline was more sensitive, while the
connection-aware Watcher remained more selective. This is a
recall/alert-burden trade-off, not Watcher superiority. The baseline remains
the frozen inbound-only reference-delay detector with a 15-minute threshold.

Because REFERENCE contains only nine infeasible connections, percentage
differences are highly uncertain and should be read as bounded benchmark
observations rather than statistically stable performance estimates.

## First-alert lead time

PR #6 reproduces the frozen PR #5 first-alert result before synthetic cutoff in
REFERENCE; it does not introduce a new lead-time statistic:

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
- p90 transitions per connection was at most 1;
- the maximum was 5 transitions on LOW/1h and LOW/2h; and
- corrected repeated-entry counts did not materially increase with wider
  margins.

At the retained 2h configuration, corrected churn is:

| Scenario | Connections with repeated entry | Total repeated entries | Median transitions | p90 transitions | Maximum transitions |
|---|---:|---:|---:|---:|---:|
| LOW | 2 | 2 | 0 | 1.0 | 5 |
| REFERENCE | 1 | 1 | 0 | 0.9 | 3 |
| CONSERVATIVE | 1 | 1 | 0 | 0.9 | 2 |

No hysteresis is added. Observed churn remained limited in this bounded
benchmark, including the corrected repeated-entry counts and reported maximum
transition tail.

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
This mathematical causal predicate is unchanged; no minimum operational
window is retroactively added. If a minimum actionable window is later wanted,
it should be a separate, configurable policy concept rather than a
redefinition of this predicate.

The concepts are deliberately independent and must never be treated as
equivalent.

### Retrospective challenge results

| Case | Category | Assessment available? | Prevention signal? | Key causal behavior |
|---|---|---:|---:|---|
| TPC-01 | Prevention opportunity | Yes | Yes | `CAUSALLY_ACTIONABLE` before cutoff |
| TPC-02 | Prevention opportunity | No | No | No causal assessment before cutoff |
| TPC-03 | Prevention opportunity | Yes | No | Alert after no-ITT slack became non-positive |
| TPC-04 | Prevention opportunity | Yes | No | Alert after no-ITT slack became non-positive |
| TPC-05 | Unrecoverable without ITT | No | No | No assessment; insufficiency not demonstrated |
| TPC-06 | Unrecoverable without ITT | Yes | Yes | Later insufficiency observed; first signal had only +0.001194h no-ITT slack |
| TPC-07 | Unrecoverable without ITT | Yes | No | No-ITT insufficiency observed before cutoff |
| TPC-08 | Unrecoverable without ITT | No | No | No assessment; insufficiency not demonstrated |
| TPC-09 | Feasible with ITT | Yes | No | Avoided a prevention signal before cutoff |
| TPC-10 | Feasible with ITT | Yes | No | Avoided a prevention signal before cutoff |
| TPC-11 | Feasible with ITT | Yes | No | Avoided a prevention signal before cutoff |
| TPC-12 | Feasible with ITT | No | No | No assessment; feasible discrimination not demonstrated |

Three of four curated retrospective-prevention cases received an alert before
cutoff. Only one reached the causal current-plan-infeasible/no-ITT-feasible
state; one had no assessment; and two alerts occurred after the prevention
window had already closed. These are curated capability counts, not operational
performance statistics. The result is consistent with the broader finding
that historical causal timing availability can limit early intervention.

The other curated categories remain separate: four cases are unrecoverable
even without ITT and four are feasible with ITT. They test whether the Watcher
can distinguish prevention from insufficient or unnecessary intervention.

TPC-V1-06 mathematically satisfies `current_plan_slack <= 0` and
`no_itt_slack > 0` at its first signal, but its remaining no-ITT margin is only
about 0.0012h (4.3 seconds). That is operationally negligible under this
synthetic benchmark and is not presented as strongly actionable.

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
