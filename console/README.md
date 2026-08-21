# LATCH — Operator Console (workstream C)

The screen a port operations controller watches: what is at risk, what the
agent proposes, how much to trust it, and where to approve or decline.

Fixture-driven, no backend. React + Vite + TypeScript + Tailwind.

## Run it

```bash
npm install
npm run dev
```

Then open http://localhost:5173.

| Command | What it does |
|---|---|
| `npm run dev` | Dev server on :5173 |
| `npm run build` | Typecheck and production build |
| `npm run typecheck` | Types only |
| `npm run fixtures` | Re-capture fixtures by running B's pipeline (needs Python) |
| `npm run smoke` | Run the adapter over every fixture and assert it still holds |

`npm run fixtures` needs Python 3.13 and imports `latch` from `../src`. It
does not modify anything in A's or B's code.

## What you are looking at

**Data basis: real vessel movement data + derived arrival estimates +
synthetic transhipment connections.** One month of real Singapore AIS data
gives the vessel timing. Which box connects to which outbound vessel, the
terminal assignments, the box counts, the loading cut-offs and the whole ITT
slot inventory are simulated. Model responses in the shipped fixtures are
scripted — no model was consulted — so the traces measure the pipeline, not
the agent. All three facts are stated in the console header, not in this file
only.

Where a measured figure belongs and A's evaluation has not run, the console
renders a visible `PLACEHOLDER` rather than a number.

## The demo

Press **Play the failure-injection run**. The console replays a captured trace
one step at a time:

1. `query_itt_slot` times out, retries, times out again
2. it falls back to slot inventory read from cache 8 minutes ago
3. confidence lands at **0.6672**, below the 0.70 policy threshold
4. the Gate Controller escalates the approval from **auto** to **Vessel
   Operations** — nobody chose to, the number fell out of the run
5. playback pauses and hands you the decision, with a countdown

Approve, decline, or let it lapse. Each of the three continues into a
*separately captured run of the same event*, so whichever you pick the console
plays a real trace rather than describing one.

Playback is deterministic and touches no API, so a recording is repeatable.
Any connection in the queue can be replayed from the dropdown.

## Layout

- **Left — risk queue.** Every connection by criticality, with state, slack,
  boxes, confidence band, and a flag when removing the inter-terminal transfer
  would rescue it.
- **Centre — connection detail.** Vessel timing, current-plan slack against
  no-ITT slack, reason codes in operator English, the ladder, B's ranked
  options, the outcome, and what the decision cost.
- **Right — trust.** Approval panel, confidence, the gate, and the execution
  trace.

## Reading the console honestly

Three things it deliberately does *not* do:

1. **It does not invent fields.** Where B carries no value the console shows a
   gap marker naming the request that would close it. Option cost (SGD) and
   emissions (kgCO2e) are the visible example: B computes both and discards
   them before the trace, and the console will not recompute them from the
   per-box constants and attribute the result to the agent.
2. **It does not correct B silently.** When B's `service_success` counts an
   outcome the customer took no part in, the console shows B's value and the
   caveat side by side.
3. **It does not hide authored fixtures.** Two of the eleven are partly
   authored, because the states they show are not reachable through
   `runner.handle()`. Both say so on screen.

See [CONTRACTS.md](CONTRACTS.md) for every place A's and B's real shapes differ
from the design sketch, and the nine requests raised against them.

## Structure

```
src/
  contracts/latch.ts      A's and B's real shapes, transcribed from the Python
  adapters/
    types.ts              the view model — no A/B types leak past here
    toViewModel.ts        the ONLY module that touches A/B shapes
  data/fixtures.ts        fixture loading; swap this for a live feed
  store/useConsole.ts     queue, selection, trace playback
  components/             presentation only
scripts/
  capture_fixtures.py     runs B's pipeline and captures the fixtures
  smoke.ts                runs the adapter over every fixture
fixtures/                 captured output — see fixtures/README.md
```

Everything downstream of `toViewModel.ts` consumes the view model, so replacing
fixtures with a live feed is a change to `data/fixtures.ts` and the adapter,
and to nothing else.

## Dependencies

Three packages ship in the bundle: `react`, `react-dom`, `scheduler`. No GPL,
AGPL or LGPL anywhere in the tree. Full accounting in
[DEPENDENCIES.md](DEPENDENCIES.md).
