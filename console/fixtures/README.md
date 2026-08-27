# Console fixtures

Captured by running B's real pipeline. Regenerate with:

```bash
npm run fixtures
```

or directly:

```bash
uv run python console/scripts/capture_fixtures.py
```

**These are not the repo's top-level `fixtures/`.** Those are hand-scripted by
`scripts/make_fixtures.py` and state a confidence value and an escalation path
that `confidence.score()` and `gates.evaluate()` do not produce — see
CONTRACTS.md §10. The console does not read them.

## How these are produced

`capture_fixtures.py` imports A and B read-only and calls `runner.handle()` on
a real `RiskEvent`, with deterministic failure injection from B's own
`ScriptedFailures` and cache entries built from B's own `build_itt_inventory`.
Confidence values, gate escalations, excluded options, lock claims and state
transitions are all computed by B's code. If `gates.py` or `confidence.py`
changes and the script still runs, these fixtures are still true.

Each file is a bundle: the `RiskEvent`, B's `ConnectionRisk`, the full `Trace`,
B's own `case_view`, the `GateDecision` (which B never serialises), and the
`RiskEvent` derived properties. The adapter reads the bundle; nothing else does.

Each event is serialized with the current `RiskEvent.to_dict()` contract.
These historical console scenarios genuinely lack all four PR #2 causal
arrival values, so they remain `timing_resolution: legacy_slack_fallback` and
the UI labels their display-only vessel times as reconstructed. The generator
does not relabel them as causal. `LATCH_SRC=/path/to/src` points the capture at
a different checkout of A and B.

## What is real and what is not

Honest in both directions, and both facts are on screen in the console:

- **Timing in these fixtures:** the source scenario is labelled AIS replay,
  but these legacy payloads do not carry the four causal arrival values. The
  vessel times displayed by B are reconstructed from event slack and are not
  observed timings. A production `derived_causal_arrival` event would instead
  carry all four causal AIS-derived estimates explicitly.
- **Simulated:** which box connects to which outbound vessel, the terminal
  assignments, the box counts, the loading cut-offs, and the entire ITT slot
  inventory. Every event carries `terminal_resolution: simulated`, which lowers
  the agent's confidence — the synthetic origin is enforced by the pipeline,
  not asserted in a caption.
- **Scripted:** no model was consulted. `ScriptedDeliberator` stands in for the
  model seam, ranking by the policy in B's own deliberation system prompt.
  Token counts use B's `FakeModel` formula and are priced at `config.PRICING`.
  These traces measure the pipeline, not the agent.

Anywhere the console describes its own data it says: **real vessel movement
data + derived arrival estimates + synthetic transhipment connections.**

## The fixtures

| File | Severity | Ends at | Confidence | Gate | What it is for |
|---|---|---|---|---|---|
| `01-safe.json` | SAFE | `dismissed` | — | — | The funnel. Dismissed by `triage.prefilter` with no model call at either end |
| `02-watch.json` | WATCH | `resolved` | 1.0000 | auto | Live data, small volume, inside policy. The contrast case |
| `03-at-risk-rescuable.json` | AT_RISK | `resolved` | 0.8000 | Vessel Ops | `itt_is_the_problem` — a Rung 1 advisory alongside the Rung 3 move, plus two barge legs code ruled out |
| `04-at-risk-not-rescuable.json` | AT_RISK | `resolved` | 1.0000 | Duty Manager | Negative margin even without the transfer. Rung 4, and the line never answers |
| `05-failure-injection.json` | AT_RISK | `resolved` | **0.6672** | **auto → Vessel Ops** | The centrepiece. See below |
| `06-lapsed.json` | AT_RISK | `resolved` | 0.8000 | Vessel Ops | Nobody signed. `RiskState.LAPSED`, then the default action fires |
| `07-customer-declined.json` | AT_RISK | `resolved` | 1.0000 | Vessel Ops | The line declined everything — and was served |
| `08-superseded.json` | AT_RISK | `superseded` | — | — | The estimate improved mid-deliberation. Partly authored, see below |
| `09-stale.json` | AT_RISK | `stale` | — | — | Both read tools failed with nothing cached. Authored, see below |
| `10-contention-winner.json` | AT_RISK | `resolved` | 1.0000 | auto | Claims the contested slot and commits it |
| `11-contention-loser.json` | AT_RISK | `resolved` | 1.0000 | — | Finds it committed, goes to `LOST_LOCK`, re-deliberates, falls to Rung 4 |

`05b` and `05c` are the other two branches of the failure-injection run, and
are held out of the risk queue because they share a connection id with `05` —
two rows for one connection is exactly what the queue must not do. They are
what the approval panel's decline and auto-decline play instead:

| File | Approval | Ends at |
|---|---|---|
| `05-failure-injection.json` | approved | `connection_held` |
| `05b-approval-declined.json` | declined by Vessel Ops | `customer_declined_all` |
| `05c-approval-lapsed.json` | nobody signed | `window_lapsed_no_response` |

Same event, same 0.6672, same escalation. The only variable is the human, so
whichever the operator picks the console continues into a recorded trace.

`04` and `07` are the pair worth designing around. Both end with a rolled box.
`Resolution.is_service_success` is false for one and true for the other, and
making that difference legible is the most valuable thing on the screen.

## 05 — the failure-injection run

`ScriptedFailures({"query_itt_slot": [TIMEOUT, TIMEOUT]})` with an 8-minute-old
`CacheEntry`. What B produces:

```
tool_call  query_itt_slot  cached_fallback  10000ms  attempts=2
error      query_itt_slot  timeout  retries=1  recovery="cached inventory @ T-8m"
confidence 0.6672
           source=0.85 (cache) x age=0.938 (8m) x tool=0.90 (retried)
           - unverified=0.05 (1 of 3) = 0.67
gate       rung_3_move  would_have_been=auto  required_role=vessel_ops
           escalated=true  reason="confidence 0.67 below 0.7"
```

Nobody lowers the confidence. It falls out of the cache read, and
`gates.evaluate()` escalates the approval from *auto* to a named human on its
own. That transition — `auto → Vessel Operations`, because confidence fell
below 0.70 — is the single most important frame in the demo video.

The confidence is **0.6672**, not the 0.61 in the original design doc and not
the 0.6172 in the repo's scripted fixture. 0.6672 is what the code computes.

## 10 and 11 — one slot, two connections

Both share a single `LockTable`, so the contention is real: `SG-CONN-4562`
claims `itt_slot:tuapas_1120` and commits it, and `SG-CONN-4571` finds it taken
at priority 96 against 152, moves to `LOST_LOCK`, re-deliberates with the
option removed, and falls to Rung 4.

One limitation, stated because it would otherwise look like the Lock Table only
handles the easy case. `runner.handle()` takes a risk from detection to
resolution without yielding, so two deliberations never interleave in one
process. The reachable contention here is therefore `incumbent_committed` —
capacity already consumed, which must not be booked twice. Priority preemption
of an *uncommitted* reservation needs concurrent deliberation and is covered by
B's own tests rather than by a captured fixture. Neither is simulated here.

## 08 and 09 are partly authored, and say so

Both carry `provenance.authored: true` and an `authored_because` string, which
the console renders rather than hides.

- **`08-superseded.json`** — the two `AdmissionDecision` records are genuine
  `CaseRegistry` output. The trace is C's, because `runner.handle()` is atomic
  and never yields a trace mid-flight (CONTRACTS.md §9). Every state move still
  goes through B's `transition()`, which raises on an illegal move.
- **`09-stale.json`** — `RiskState.STALE` is declared in B's state machine and
  no code path enters it (CONTRACTS.md §8). This fixture shows what the console
  does if B wires it up. It is not evidence that the behaviour exists today.

## Regeneration is byte-stable

The fixture harness freezes `trace.py::_now` to a deterministic fixture record
clock. Those `at` values are **not** scenario time: the console orders by
`seq` and takes duration from `latency_ms`. Running the normal fixture command
twice produces byte-identical files.

After regenerating, run the adapter check:

```bash
npm run smoke
```

It re-derives the unverified-input field list from each trace and asserts it
still matches B's own `unverified_inputs` count, that each confidence waterfall
still lands on B's computed value, and that no enum reaches the screen without
operator English.
