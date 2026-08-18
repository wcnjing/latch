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
