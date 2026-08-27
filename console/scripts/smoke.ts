/**
 * Adapter smoke check. Runs `toViewModel` over every captured fixture and
 * prints what the console would show, asserting the things that would
 * silently rot after a fixture regeneration:
 *
 *   - the unverified-field list this adapter reconstructs still matches B's
 *     own `unverified_inputs` count
 *   - the confidence waterfall still lands on B's computed value
 *   - every reason code and every timeline step has operator English
 *   - service success still agrees with `Resolution.is_service_success`
 *
 *   npm run smoke
 */
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  TIMING_RESOLUTION_LABEL,
  byCriticality,
  toViewModel,
} from '../src/adapters/toViewModel';
import type { FixtureBundle } from '../src/adapters/types';
import type { TimingResolution } from '../src/contracts/latch';

const here = dirname(fileURLToPath(import.meta.url));
const dir = join(here, '..', 'fixtures');

const bundles = readdirSync(dir)
  .filter((f) => f.endsWith('.json') && f !== 'index.json')
  .sort()
  .map((f) => JSON.parse(readFileSync(join(dir, f), 'utf8')) as FixtureBundle);

let problems = 0;
const fail = (msg: string) => {
  problems += 1;
  console.log(`  !! ${msg}`);
};

const timingResolutionError = (value: unknown): string | null =>
  value === 'derived_causal_arrival' || value === 'legacy_slack_fallback'
    ? null
    : `timing_resolution must be derived_causal_arrival or legacy_slack_fallback; got ${String(value)}`;

// Runtime JSON is not protected by the FixtureBundle compile-time type. Keep
// these cases beside the guard so removing either accepted failure regresses
// the smoke check itself.
for (const invalid of [undefined, 'unknown_timing_resolution']) {
  if (timingResolutionError(invalid) === null) {
    fail(`timing_resolution runtime guard accepted ${String(invalid)}`);
  }
}

for (const vm of bundles.map(toViewModel).sort(byCriticality)) {
  const c = vm.confidence;
  console.log(
    `${vm.id.padEnd(14)} ${vm.severityLabel.padEnd(8)} ${vm.stateLabel.padEnd(13)}` +
      `boxes=${String(vm.boxes).padStart(3)} prio=${String(Math.round(vm.priority)).padStart(4)} ` +
      `conf=${c ? c.value.toFixed(4) : '   -  '} ` +
      `gate=${(vm.gate?.requiredRoleLabel ?? '-').padEnd(21)}` +
      `rescue=${vm.rescuableByRemovingItt ? 'Y' : 'n'} steps=${vm.timeline.length}`,
  );

  if (vm.gate?.escalation) {
    const e = vm.gate.escalation;
    console.log(
      `               autonomy ${e.wouldHaveBeenLabel} -> ${e.becameLabel}  (${e.reasons.join('; ')})`,
    );
  }
  if (c?.degradations.length) {
    for (const d of c.degradations) {
      console.log(`               ${d.tool} ${d.what} x${d.attempts} -> ${d.fallback}`);
    }
  }

  if (c && !c.unverifiedFieldsReconciled) {
    fail(
      `${vm.id}: reconstructed ${c.unverifiedFields.length} unverified field(s), ` +
        `B counted ${c.unverifiedCount}`,
    );
  }
  if (c) {
    const last = c.waterfall.at(-1);
    if (!last || Math.abs(last.running - c.value) > 0.0002) {
      fail(`${vm.id}: waterfall ends at ${last?.running}, B computed ${c.value}`);
    }
  }
  for (const r of vm.reasons) if (!r.title) fail(`${vm.id}: unmapped reason code ${r.code}`);
  for (const t of vm.timeline) if (!t.title) fail(`${vm.id}: timeline step ${t.seq} has no title`);
  const rawTimingResolution = (vm.raw.event as { timing_resolution?: unknown }).timing_resolution;
  const rawTimingError = timingResolutionError(rawTimingResolution);
  if (rawTimingError !== null) {
    fail(`${vm.id}: ${rawTimingError}`);
  } else {
    const timingResolution = rawTimingResolution as TimingResolution;
    for (const [legName, leg] of [
      ['inbound', vm.inbound],
      ['outbound', vm.outbound],
    ] as const) {
      if (leg.timingResolution !== timingResolution) {
        fail(`${vm.id}: ${legName} timingResolution does not match raw RiskEvent value`);
      }
      if (!leg.timingProvenanceLabel.trim()) {
        fail(`${vm.id}: ${legName} timingProvenanceLabel is empty`);
      }
      if (leg.timingProvenanceLabel !== TIMING_RESOLUTION_LABEL[timingResolution]) {
        fail(`${vm.id}: ${legName} vessel timing provenance label is incorrect`);
      }
    }
  }
  const timingFields = [
    vm.raw.event.inbound_reference_arrival,
    vm.raw.event.inbound_predicted_arrival,
    vm.raw.event.outbound_reference_arrival,
    vm.raw.event.outbound_predicted_arrival,
  ];
  if (
    rawTimingResolution === 'legacy_slack_fallback' &&
    timingFields.some((value) => value !== undefined)
  ) {
    fail(`${vm.id}: legacy timing fixture carries causal arrival fields`);
  }
  if (
    rawTimingResolution === 'derived_causal_arrival' &&
    timingFields.some((value) => typeof value !== 'string' || value.length === 0)
  ) {
    fail(`${vm.id}: derived causal timing fixture is missing an arrival field`);
  }
  // Two independent B serialisation sites — `case_view()` and the trace's own
  // outcome block. The adapter reads the first; if they diverge, the console
  // renders one of them while the metrics are computed from the other.
  if (vm.outcome && vm.outcome.serviceSuccess !== vm.raw.trace.outcome.service_success) {
    fail(`${vm.id}: case_view and trace.outcome disagree on service success`);
  }
  // The console's transcribed copy of B's classification, checked against the
  // value B actually sent. This is the assertion that should have caught the
  // internal/customer split, and could not: an unguarded lookup in the adapter
  // crashed before the loop reached it.
  if (vm.outcome?.serviceSuccessReconciled === false) {
    fail(
      `${vm.id}: B says service_success=${vm.outcome.serviceSuccess} for ` +
        `${vm.outcome.resolution}; SERVICE_SUCCESS_RESOLUTIONS says otherwise`,
    );
  }
  // A gap badge on a captured fixture means B stopped sending a field the
  // adapter needs. Honest on screen, but never correct here: these bundles
  // come straight out of `runner.handle()`.
  if (vm.outcome?.badge === 'outcome not recorded') {
    fail(
      `${vm.id}: resolved ${vm.outcome.resolution} but B did not send the ` +
        `flags needed to classify it (service_success / reached_the_line / ` +
        `agent_fault / excluded_from_metric)`,
    );
  }
  if (vm.outcome?.badge === 'system fault') fail(`${vm.id}: agent fault in a fixture`);
  if (vm.gate?.rung.advisoryOnly && vm.approval?.actionable) {
    fail(`${vm.id}: rung 1 must not offer an approve control`);
  }
}

console.log(`\n${bundles.length} fixtures, ${problems} problem(s)`);
process.exit(problems ? 1 : 0);
